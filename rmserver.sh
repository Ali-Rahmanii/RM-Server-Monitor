#!/usr/bin/env bash
#
# RM Server Monitor — اسکریپت اصلی مدیریت سیستم مرکزی (Core).
# اجرا: bash rmserver.sh   (برای گزینه‌های نصب/سرویس/حذف با sudo اجرا کن)
# یا از هرجایی با دستور سراسری: rmmonitor  (سیم‌لینکی که setup.sh می‌سازد)
#
set -uo pipefail

VERSION="v1.0.0"

# این اسکریپت معمولاً از راه یک symlink در /usr/local/bin/rmmonitor صدا
# زده می‌شود — $BASH_SOURCE در آن حالت به مسیر symlink اشاره می‌کند نه
# مسیر واقعی فایل، پس صریحاً symlink را دنبال می‌کنیم تا SCRIPT_DIR
# همیشه به /opt/RM-Server-Monitor (یا هرجا واقعاً کلون شده) برسد.
_resolve_script_dir() {
    local src="${BASH_SOURCE[0]}"
    while [[ -h "${src}" ]]; do
        local dir
        dir="$(cd -P "$(dirname "${src}")" && pwd)"
        src="$(readlink "${src}")"
        [[ "${src}" != /* ]] && src="${dir}/${src}"
    done
    cd -P "$(dirname "${src}")" && pwd
}
SCRIPT_DIR="$(_resolve_script_dir)"
CORE_SERVICE_NAME="monitorbot-core"
CORE_SERVICE_FILE="/etc/systemd/system/${CORE_SERVICE_NAME}.service"
VENV_DIR="${SCRIPT_DIR}/.venv"
ENV_FILE="${SCRIPT_DIR}/.env"

# ══════════════════════════════════════════════════════════════════
#  رنگ‌ها
# ══════════════════════════════════════════════════════════════════
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'
CYAN='\033[0;36m'; MAGENTA='\033[0;35m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

log()  { echo -e "${GREEN}[rmserver]${RESET} $*"; }
warn() { echo -e "${YELLOW}[rmserver] هشدار:${RESET} $*"; }
err()  { echo -e "${RED}[rmserver] خطا:${RESET} $*" >&2; }
die()  { err "$*"; exit 1; }

check_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        die "این عملیات نیاز به دسترسی root دارد. دوباره با sudo اجرا کن: sudo bash rmserver.sh"
    fi
}

pause() { echo ""; read -rp "برای ادامه Enter بزن..." _; }

load_env_var() {
    local key="$1" file="$2" default="${3:-}"
    local val
    val="$(grep -E "^${key}=" "${file}" 2>/dev/null | tail -n1 | cut -d'=' -f2-)"
    echo "${val:-$default}"
}

# ══════════════════════════════════════════════════════════════════
#  هدر / بنر
# ══════════════════════════════════════════════════════════════════
print_banner() {
    clear
    echo -e "${CYAN}${BOLD}"
    cat <<'BANNER'
 ██████╗ ███╗   ███╗
 ██╔══██╗████╗ ████║
 ██████╔╝██╔████╔██║
 ██╔══██╗██║╚██╔╝██║
 ██║  ██║██║ ╚═╝ ██║
 ╚═╝  ╚═╝╚═╝     ╚═╝
BANNER
    echo -e "${RESET}${MAGENTA}${BOLD}     S E R V E R   M O N I T O R${RESET}"
    echo -e "${DIM}     ─────────────────────────────────────${RESET}"
    echo -e "${BOLD}     Developer:${RESET} ${CYAN}Ali Rahmani${RESET}"
    echo -e "${BOLD}     Telegram :${RESET} ${CYAN}@a_alirahmani${RESET}"
    echo -e "${BOLD}     GitHub   :${RESET} ${CYAN}https://github.com/Ali-Rahmanii/RM-Server-Monitor${RESET}"
    echo -e "${DIM}     ─────────────────────────────────────${RESET}"
    echo -e "     ${YELLOW}Version ${VERSION}${RESET}   ${DIM}·${RESET}   هر جا بودی، این منو را با تایپ ${BOLD}rmmonitor${RESET} باز کن"
    echo ""
}

print_menu() {
    echo -e "${BOLD}منوی اصلی:${RESET}"
    echo -e "  ${GREEN}1)${RESET} نصب سیستم مرکزی (Core) — venv + پکیج‌ها + systemd service"
    echo -e "  ${GREEN}2)${RESET} شروع/توقف/ری‌استارت سرویس Core"
    echo -e "  ${GREEN}3)${RESET} به‌روزرسانی سیستم (git pull + پکیج‌ها + ری‌استارت + به‌روزرسانی همه‌ی ایجنت‌ها)"
    echo -e "  ${GREEN}4)${RESET} حذف کامل (سرویس Core + دیتابیس)"
    echo -e "  ${RED}0)${RESET} خروج"
    echo ""
}

# ══════════════════════════════════════════════════════════════════
#  ابزارهای مشترک
# ══════════════════════════════════════════════════════════════════
ensure_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        log "python3 پیدا نشد — تلاش برای نصب خودکار..."
        if command -v apt-get >/dev/null 2>&1; then
            apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip
        elif command -v dnf >/dev/null 2>&1; then
            dnf install -y -q python3 python3-pip
        elif command -v yum >/dev/null 2>&1; then
            yum install -y -q python3 python3-pip
        else
            die "python3 پیدا نشد و نصب خودکار روی این توزیع ممکن نیست."
        fi
    fi
    if ! python3 -m venv --help >/dev/null 2>&1; then
        if command -v apt-get >/dev/null 2>&1; then
            log "نصب python3-venv..."
            apt-get update -qq && apt-get install -y -qq python3-venv
        fi
    fi
}

service_exists() {
    [[ -f "${CORE_SERVICE_FILE}" ]]
}

# ══════════════════════════════════════════════════════════════════
#  1) نصب سیستم مرکزی
# ══════════════════════════════════════════════════════════════════
install_core() {
    check_root
    ensure_python

    if [[ ! -x "${VENV_DIR}/bin/pip" ]]; then
        log "ساخت virtualenv در ${VENV_DIR}..."
        python3 -m venv "${VENV_DIR}"
    fi
    if [[ ! -x "${VENV_DIR}/bin/pip" ]]; then
        die "ساخت virtualenv ناموفق بود. آیا python3-venv نصب است؟"
    fi

    log "نصب پکیج‌های پایتون..."
    "${VENV_DIR}/bin/pip" install --upgrade pip -q
    "${VENV_DIR}/bin/pip" install -r "${SCRIPT_DIR}/requirements.txt" -q

    if [[ ! -f "${ENV_FILE}" ]]; then
        if [[ -f "${SCRIPT_DIR}/.env.example" ]]; then
            cp "${SCRIPT_DIR}/.env.example" "${ENV_FILE}"
            warn "فایل .env از روی نمونه ساخته شد. حتماً WEB_PASSWORD و TELEGRAM_BOT_TOKEN را در ${ENV_FILE} ویرایش کن."
        else
            die "نه .env و نه .env.example پیدا شد — یکی را دستی بساز."
        fi
    fi

    local web_port
    web_port="$(load_env_var WEB_PORT "${ENV_FILE}" 8000)"

    if command -v systemctl >/dev/null 2>&1; then
        log "ساخت systemd service..."
        cat > "${CORE_SERVICE_FILE}" <<SERVICE_EOF
[Unit]
Description=Monitorbot Core (dashboard + scheduler + telegram bot)
After=network.target

[Service]
Type=simple
WorkingDirectory=${SCRIPT_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/python ${SCRIPT_DIR}/main.py
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
SERVICE_EOF
        systemctl daemon-reload
        systemctl enable --now "${CORE_SERVICE_NAME}"
        sleep 2
        if systemctl is-active --quiet "${CORE_SERVICE_NAME}"; then
            log "سرویس ${CORE_SERVICE_NAME} فعال است."
        else
            err "سرویس بالا نیامد. لاگ: journalctl -u ${CORE_SERVICE_NAME} -n 50"
        fi
    else
        warn "systemctl پیدا نشد — سیستم را دستی با «${VENV_DIR}/bin/python main.py» اجرا کن."
    fi

    echo ""
    log "نصب کامل شد. داشبورد: http://<IP-سرور>:${web_port}"
}

# ══════════════════════════════════════════════════════════════════
#  2) مدیریت سرویس Core
# ══════════════════════════════════════════════════════════════════
manage_service() {
    if ! command -v systemctl >/dev/null 2>&1; then
        err "systemctl روی این سیستم موجود نیست."
        pause; return
    fi
    if ! service_exists; then
        err "سرویس ${CORE_SERVICE_NAME} هنوز نصب نشده — اول گزینه‌ی 1 را اجرا کن."
        pause; return
    fi

    echo -e "${BOLD}مدیریت سرویس Core:${RESET}"
    echo "  1) Start"
    echo "  2) Stop"
    echo "  3) Restart"
    echo "  4) Status"
    echo "  0) بازگشت"
    read -rp "> " sub
    case "${sub}" in
        1) check_root; systemctl start "${CORE_SERVICE_NAME}" && log "شروع شد." ;;
        2) check_root; systemctl stop "${CORE_SERVICE_NAME}" && log "متوقف شد." ;;
        3) check_root; systemctl restart "${CORE_SERVICE_NAME}" && log "ری‌استارت شد." ;;
        4) systemctl status "${CORE_SERVICE_NAME}" --no-pager || true ;;
        0) return ;;
        *) err "گزینه نامعتبر." ;;
    esac
    pause
}

# ══════════════════════════════════════════════════════════════════
#  3) به‌روزرسانی کامل سیستم
# ══════════════════════════════════════════════════════════════════
update_system() {
    log "شروع به‌روزرسانی..."

    if [[ -d "${SCRIPT_DIR}/.git" ]]; then
        log "دریافت آخرین نسخه از گیت..."
        (cd "${SCRIPT_DIR}" && git pull) || warn "git pull ناموفق بود — با نسخه‌ی فعلی ادامه می‌دهیم."
    else
        warn "این پوشه یک git repo نیست — از git pull صرف‌نظر شد."
    fi

    if [[ -x "${VENV_DIR}/bin/pip" ]]; then
        log "به‌روزرسانی پکیج‌های پایتون..."
        "${VENV_DIR}/bin/pip" install --upgrade -r "${SCRIPT_DIR}/requirements.txt" -q
    else
        warn "virtualenv پیدا نشد — اول گزینه‌ی 1 (نصب) را اجرا کن."
    fi

    if command -v systemctl >/dev/null 2>&1 && service_exists; then
        check_root
        log "ری‌استارت سرویس Core..."
        systemctl restart "${CORE_SERVICE_NAME}"
        sleep 2
    fi

    if [[ -f "${ENV_FILE}" ]]; then
        local web_port web_user web_pass
        web_port="$(load_env_var WEB_PORT "${ENV_FILE}" 8000)"
        web_user="$(load_env_var WEB_USERNAME "${ENV_FILE}" admin)"
        web_pass="$(load_env_var WEB_PASSWORD "${ENV_FILE}" changeme)"

        log "درخواست به‌روزرسانی همه‌ی ایجنت‌های ثبت‌شده (از راه SSH) از طریق API..."
        local response
        response="$(curl -s -u "${web_user}:${web_pass}" -X POST "http://127.0.0.1:${web_port}/api/update-agents" 2>/dev/null)"
        if [[ -z "${response}" ]]; then
            warn "پاسخی از API دریافت نشد — آیا سرویس Core بالاست؟"
        elif command -v python3 >/dev/null 2>&1; then
            echo "${response}" | python3 -m json.tool 2>/dev/null || echo "${response}"
        else
            echo "${response}"
        fi
    else
        warn "فایل .env پیدا نشد — به‌روزرسانی ایجنت‌ها رد شد."
    fi

    echo ""
    log "به‌روزرسانی تمام شد."
}

# ══════════════════════════════════════════════════════════════════
#  4) حذف کامل
# ══════════════════════════════════════════════════════════════════
uninstall_core() {
    check_root
    echo -e "${RED}${BOLD}این عملیات سرویس Core را حذف می‌کند.${RESET}"
    read -rp "برای تایید عبارت yes را تایپ کن: " confirm
    if [[ "${confirm}" != "yes" ]]; then
        warn "لغو شد."
        pause; return
    fi

    if command -v systemctl >/dev/null 2>&1; then
        systemctl stop "${CORE_SERVICE_NAME}" 2>/dev/null || true
        systemctl disable "${CORE_SERVICE_NAME}" 2>/dev/null || true
    fi
    if [[ -f "${CORE_SERVICE_FILE}" ]]; then
        rm -f "${CORE_SERVICE_FILE}"
        command -v systemctl >/dev/null 2>&1 && systemctl daemon-reload
        log "سرویس Core حذف شد."
    fi

    read -rp "دیتابیس (monitorbot.db) هم حذف شود؟ تمام تاریخچه از بین می‌رود [y/N]: " del_db
    if [[ "${del_db}" =~ ^[Yy]$ ]]; then
        rm -f "${SCRIPT_DIR}/monitorbot.db" "${SCRIPT_DIR}/monitorbot.db-wal" "${SCRIPT_DIR}/monitorbot.db-shm"
        log "دیتابیس حذف شد."
    fi

    read -rp "پوشه‌ی virtualenv (.venv) هم حذف شود؟ [y/N]: " del_venv
    if [[ "${del_venv}" =~ ^[Yy]$ ]]; then
        rm -rf "${VENV_DIR}"
        log "virtualenv حذف شد."
    fi

    echo ""
    log "حذف کامل شد. فایل‌های سورس دست‌نخورده باقی ماندند (فقط سرویس/دیتابیس/venv حذف شد)."
}

# ══════════════════════════════════════════════════════════════════
#  حلقه‌ی اصلی منو
# ══════════════════════════════════════════════════════════════════
main_loop() {
    while true; do
        print_banner
        print_menu
        read -rp "یک گزینه انتخاب کن: " choice
        case "${choice}" in
            1) install_core; pause ;;
            2) manage_service ;;
            3) update_system; pause ;;
            4) uninstall_core; pause ;;
            0) echo -e "${CYAN}خدانگهدار!${RESET}"; exit 0 ;;
            *) err "گزینه نامعتبر."; pause ;;
        esac
    done
}

main_loop
