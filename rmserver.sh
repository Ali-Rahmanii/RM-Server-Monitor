#!/usr/bin/env bash
#
# RM Server Monitor — main Core management script.
# Almost everything here touches root-owned files/services, so run it
# with sudo: sudo bash rmserver.sh
# Or from anywhere via the global command: sudo rmmonitor  (symlink created by setup.sh)
#
set -uo pipefail

VERSION="v1.0.0"

# This script is usually invoked through a symlink at
# /usr/local/bin/rmmonitor — $BASH_SOURCE then points at the symlink,
# not the real file, so we explicitly resolve it to make sure
# SCRIPT_DIR always lands on the real install directory
# (e.g. /opt/RM-Server-Monitor), no matter how it was launched.
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
DB_FILE="${SCRIPT_DIR}/monitorbot.db"
BACKUP_DIR="${SCRIPT_DIR}/backups"

# ══════════════════════════════════════════════════════════════════
#  GTA Sunset / Vice City color palette (256-color ANSI)
# ══════════════════════════════════════════════════════════════════
C_PURPLE='\033[38;5;93m'
C_VIOLET='\033[38;5;129m'
C_MAGENTA='\033[38;5;165m'
C_PINK='\033[38;5;201m'
C_HOTPINK='\033[38;5;213m'
C_ORANGE='\033[38;5;208m'
C_AMBER='\033[38;5;214m'
C_YELLOW='\033[38;5;220m'
RED='\033[0;31m'; GREEN='\033[0;32m'; DIM='\033[2m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${GREEN}[rmserver]${RESET} $*"; }
warn() { echo -e "${C_YELLOW}[rmserver] warning:${RESET} $*"; }
err()  { echo -e "${RED}[rmserver] error:${RESET} $*" >&2; }
die()  { err "$*"; exit 1; }

check_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        die "This action needs root. Re-run with sudo: sudo bash rmserver.sh"
    fi
}

pause() { echo ""; read -rp "Press Enter to continue..." _; }

load_env_var() {
    local key="$1" file="$2" default="${3:-}"
    local val
    val="$(grep -E "^${key}=" "${file}" 2>/dev/null | tail -n1 | cut -d'=' -f2-)"
    echo "${val:-$default}"
}

# ══════════════════════════════════════════════════════════════════
#  banner — bordered box with computed centering (not hand-counted
#  spaces), so it stays perfectly aligned no matter what
# ══════════════════════════════════════════════════════════════════
BANNER_WIDTH=62

# متن ساده (بدون کد رنگ) را داخل عرض ثابت وسط‌چین می‌کند. برای رشته‌های
# حاوی کاراکترهای چندبایتی یونیکد (بلوک‌های ASCII art)، عرض واقعی را
# صریح به‌عنوان آرگومان دوم بده — چون ${#text} بسته به locale ممکن است
# بایت بشمارد نه کاراکتر، و وسط‌چینی را به‌هم می‌ریزد.
_center() {
    local text="$1" visual_len="${2:-${#1}}" pad left right
    pad=$(( BANNER_WIDTH - visual_len ))
    (( pad < 0 )) && pad=0
    left=$(( pad / 2 ))
    right=$(( pad - left ))
    printf '%*s%s%*s' "${left}" "" "${text}" "${right}" ""
}

_hr() {
    local line="" i
    for (( i = 0; i < BANNER_WIDTH; i++ )); do line+="═"; done
    echo -e "${C_VIOLET}${1}${line}${2}${RESET}"
}

_box_line() {
    local content_color="$1" text="$2" visual_len="${3:-}" centered
    if [[ -n "${visual_len}" ]]; then
        centered="$(_center "${text}" "${visual_len}")"
    else
        centered="$(_center "${text}")"
    fi
    echo -e "${C_VIOLET}║${RESET}${content_color}${centered}${RESET}${C_VIOLET}║${RESET}"
}

_box_blank() {
    local spaces
    printf -v spaces '%*s' "${BANNER_WIDTH}" ""
    echo -e "${C_VIOLET}║${RESET}${spaces}${C_VIOLET}║${RESET}"
}

print_banner() {
    clear
    _hr "╔" "╗"
    _box_blank
    _box_line "${C_PURPLE}${BOLD}"  " ██████╗ ███╗   ███╗" 20
    _box_line "${C_VIOLET}${BOLD}"  " ██╔══██╗████╗ ████║" 20
    _box_line "${C_MAGENTA}${BOLD}" " ██████╔╝██╔████╔██║" 20
    _box_line "${C_PINK}${BOLD}"    " ██╔══██╗██║╚██╔╝██║" 20
    _box_line "${C_ORANGE}${BOLD}"  " ██║  ██║██║ ╚═╝ ██║" 20
    _box_line "${C_YELLOW}${BOLD}"  " ╚═╝  ╚═╝╚═╝     ╚═╝" 20
    _box_blank
    _box_line "${C_HOTPINK}${BOLD}" "S E R V E R   M O N I T O R"
    _box_blank
    _hr "╠" "╣"
    _box_blank
    _box_line "${C_YELLOW}${BOLD}" "Version ${VERSION}"
    _box_blank
    _box_line "${C_AMBER}" "https://github.com/Ali-Rahmanii/RM-Server-Monitor"
    _box_blank
    _box_line "${BOLD}" "by Ali Rahmani   ·   Telegram: @a_alirahmani" 44
    _box_blank
    _hr "╚" "╝"
    echo ""
    echo -e "${DIM}  run ${RESET}${BOLD}sudo rmmonitor${RESET}${DIM} anytime, from anywhere${RESET}"
    echo ""
}

print_menu() {
    echo -e "${BOLD}Main Menu:${RESET}"
    echo -e "  ${C_PINK}1)${RESET} Install Core System — venv + packages + systemd service"
    echo -e "  ${C_PINK}2)${RESET} Start / Stop / Restart Core Service"
    echo -e "  ${C_PINK}3)${RESET} Update System (git pull + packages + restart + update all agents)"
    echo -e "  ${C_PINK}4)${RESET} Edit .env Configuration"
    echo -e "  ${C_PINK}5)${RESET} Backup Database"
    echo -e "  ${C_PINK}6)${RESET} Restore Database"
    echo -e "  ${C_PINK}7)${RESET} Uninstall (remove Core service + database)"
    echo -e "  ${RED}0)${RESET} Exit"
    echo ""
}

# ══════════════════════════════════════════════════════════════════
#  shared helpers
# ══════════════════════════════════════════════════════════════════
ensure_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        log "python3 not found — attempting automatic install..."
        if command -v apt-get >/dev/null 2>&1; then
            apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip
        elif command -v dnf >/dev/null 2>&1; then
            dnf install -y -q python3 python3-pip
        elif command -v yum >/dev/null 2>&1; then
            yum install -y -q python3 python3-pip
        else
            die "python3 not found and cannot be auto-installed on this distro."
        fi
    fi
    if ! python3 -m venv --help >/dev/null 2>&1; then
        if command -v apt-get >/dev/null 2>&1; then
            log "Installing python3-venv..."
            apt-get update -qq && apt-get install -y -qq python3-venv
        fi
    fi
}

service_exists() {
    [[ -f "${CORE_SERVICE_FILE}" ]]
}

# ══════════════════════════════════════════════════════════════════
#  1) Install Core System
# ══════════════════════════════════════════════════════════════════
install_core() {
    check_root
    ensure_python

    if [[ ! -x "${VENV_DIR}/bin/pip" ]]; then
        log "Creating virtualenv at ${VENV_DIR}..."
        python3 -m venv "${VENV_DIR}"
    fi
    if [[ ! -x "${VENV_DIR}/bin/pip" ]]; then
        die "Failed to create the virtualenv. Is python3-venv installed?"
    fi

    log "Installing Python packages..."
    "${VENV_DIR}/bin/pip" install --upgrade pip -q
    "${VENV_DIR}/bin/pip" install -r "${SCRIPT_DIR}/requirements.txt" -q

    if [[ ! -f "${ENV_FILE}" ]]; then
        if [[ -f "${SCRIPT_DIR}/.env.example" ]]; then
            cp "${SCRIPT_DIR}/.env.example" "${ENV_FILE}"
            warn ".env was created from the example file. Edit it (menu option 4) — at minimum set WEB_PASSWORD, and TELEGRAM_BOT_TOKEN/TELEGRAM_ADMIN_IDS if you want the bot active."
        else
            die "Neither .env nor .env.example was found — create one manually."
        fi
    fi

    local web_port
    web_port="$(load_env_var WEB_PORT "${ENV_FILE}" 8000)"

    if command -v systemctl >/dev/null 2>&1; then
        log "Creating systemd service..."
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
TimeoutStopSec=20
User=root

[Install]
WantedBy=multi-user.target
SERVICE_EOF
        systemctl daemon-reload
        systemctl enable --now "${CORE_SERVICE_NAME}"
        sleep 2
        if systemctl is-active --quiet "${CORE_SERVICE_NAME}"; then
            log "Service ${CORE_SERVICE_NAME} is active."
        else
            err "Service failed to start. Logs: journalctl -u ${CORE_SERVICE_NAME} -n 50"
        fi
    else
        warn "systemctl not found — run the system manually with: ${VENV_DIR}/bin/python main.py"
    fi

    echo ""
    log "Install complete. Dashboard: http://<server-ip>:${web_port}"
}

# ══════════════════════════════════════════════════════════════════
#  2) Manage Core service
# ══════════════════════════════════════════════════════════════════
manage_service() {
    if ! command -v systemctl >/dev/null 2>&1; then
        err "systemctl is not available on this system."
        pause; return
    fi
    if ! service_exists; then
        err "Service ${CORE_SERVICE_NAME} isn't installed yet — run option 1 first."
        pause; return
    fi

    echo -e "${BOLD}Manage Core Service:${RESET}"
    echo "  1) Start"
    echo "  2) Stop"
    echo "  3) Restart"
    echo "  4) Status"
    echo "  0) Back"
    read -rp "> " sub
    case "${sub}" in
        1) check_root; systemctl start "${CORE_SERVICE_NAME}" && log "Started." ;;
        2) check_root; systemctl stop "${CORE_SERVICE_NAME}" && log "Stopped." ;;
        3) check_root; systemctl restart "${CORE_SERVICE_NAME}" && log "Restarted." ;;
        4) systemctl status "${CORE_SERVICE_NAME}" --no-pager || true ;;
        0) return ;;
        *) err "Invalid option." ;;
    esac
    pause
}

# ══════════════════════════════════════════════════════════════════
#  3) Full system update
# ══════════════════════════════════════════════════════════════════
update_system() {
    # نصب اصلی معمولاً با root انجام شده (setup.sh با sudo اجرا می‌شود)،
    # پس فایل‌های .git/venv/service هم مالک root دارند — بدون root این
    # مرحله با خطای permission denied بی‌سروصدا شکست می‌خورد.
    check_root
    log "Starting update..."
    local git_updated=0

    if [[ -d "${SCRIPT_DIR}/.git" ]]; then
        log "Pulling the latest version from git..."
        # از "git pull" ساده استفاده نمی‌کنیم چون روی سرورهای تازه که
        # تنظیمات pull.rebase/pull.ff ست نشده، یا روی کلون‌های shallow
        # (--depth 1 که setup.sh می‌سازد)، معمولاً با خطای "divergent
        # branches" شکست می‌خورد. fetch + reset --hard همیشه کار می‌کند
        # و دقیقاً working tree را با آخرین نسخه‌ی main یکی می‌کند —
        # فایل‌های .env/monitorbot.db/.venv/backups چون در .gitignore
        # هستند دست‌نخورده می‌مانند.
        local before after
        before="$(cd "${SCRIPT_DIR}" && git rev-parse HEAD 2>/dev/null)"
        if (cd "${SCRIPT_DIR}" && git fetch --all --quiet && git reset --hard origin/main --quiet); then
            after="$(cd "${SCRIPT_DIR}" && git rev-parse HEAD 2>/dev/null)"
            if [[ "${before}" != "${after}" ]]; then
                log "Repository updated: ${before:0:7} → ${after:0:7}"
                git_updated=1
            else
                log "Already up to date (${after:0:7})."
            fi
        else
            err "git update failed — see the error output above."
            warn "Continuing with the current version on disk."
        fi
    else
        warn "This folder isn't a git repo — skipping git pull."
    fi

    if [[ -x "${VENV_DIR}/bin/pip" ]]; then
        log "Updating Python packages..."
        "${VENV_DIR}/bin/pip" install --upgrade -r "${SCRIPT_DIR}/requirements.txt" -q
    else
        warn "virtualenv not found — run option 1 (Install) first."
    fi

    if command -v systemctl >/dev/null 2>&1 && service_exists; then
        check_root
        log "Restarting Core service..."
        systemctl restart "${CORE_SERVICE_NAME}"
        sleep 2
    fi

    if [[ -f "${ENV_FILE}" ]]; then
        local web_port web_user web_pass
        web_port="$(load_env_var WEB_PORT "${ENV_FILE}" 8000)"
        web_user="$(load_env_var WEB_USERNAME "${ENV_FILE}" admin)"
        web_pass="$(load_env_var WEB_PASSWORD "${ENV_FILE}" changeme)"

        log "Requesting a remote update of every SSH-deployed agent via the API..."
        local response
        response="$(curl -s -u "${web_user}:${web_pass}" -X POST "http://127.0.0.1:${web_port}/api/update-agents" 2>/dev/null)"
        if [[ -z "${response}" ]]; then
            warn "No response from the API — is the Core service running?"
        elif command -v python3 >/dev/null 2>&1; then
            echo "${response}" | python3 -m json.tool 2>/dev/null || echo "${response}"
        else
            echo "${response}"
        fi
    else
        warn ".env not found — skipped updating agents."
    fi

    echo ""
    log "Update finished."

    if [[ "${git_updated}" -eq 1 ]]; then
        pause
        log "Restarting the menu with the freshly pulled code..."
        exec bash "${SCRIPT_DIR}/rmserver.sh"
    fi
}

# ══════════════════════════════════════════════════════════════════
#  4) Edit .env
# ══════════════════════════════════════════════════════════════════
edit_env() {
    if [[ ! -f "${ENV_FILE}" ]]; then
        if [[ -f "${SCRIPT_DIR}/.env.example" ]]; then
            cp "${SCRIPT_DIR}/.env.example" "${ENV_FILE}"
            log ".env didn't exist — created from .env.example."
        else
            err ".env and .env.example are both missing — nothing to edit."
            pause; return
        fi
    fi

    local editor="${EDITOR:-nano}"
    if ! command -v "${editor}" >/dev/null 2>&1; then
        if command -v nano >/dev/null 2>&1; then editor="nano"
        elif command -v vim >/dev/null 2>&1; then editor="vim"
        elif command -v vi >/dev/null 2>&1; then editor="vi"
        else
            err "No text editor found (nano/vim/vi). Install one first, e.g.: apt-get install -y nano"
            pause; return
        fi
    fi

    "${editor}" "${ENV_FILE}"
    log ".env saved. Restart the Core service for changes to take effect (menu option 2)."
}

# ══════════════════════════════════════════════════════════════════
#  5) Backup database
# ══════════════════════════════════════════════════════════════════
backup_database() {
    if [[ ! -f "${DB_FILE}" ]]; then
        err "Database file not found at ${DB_FILE}."
        pause; return
    fi
    mkdir -p "${BACKUP_DIR}"

    # If the WAL file exists and we have the sqlite3 CLI, checkpoint it
    # into the main file first — otherwise a raw copy of the .db file
    # while Core is running can be an incomplete/corrupt snapshot.
    if [[ -f "${DB_FILE}-wal" ]] && command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 "${DB_FILE}" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null 2>&1 || true
    elif [[ -f "${DB_FILE}-wal" ]]; then
        warn "sqlite3 CLI not found and a WAL file is present — this backup might miss the most recent writes. For a guaranteed-consistent backup, prefer the web dashboard's Backup button or the Telegram bot."
    fi

    local ts dest
    ts="$(date +%Y%m%d-%H%M%S)"
    dest="${BACKUP_DIR}/monitorbot-${ts}.db"
    cp "${DB_FILE}" "${dest}"
    log "Backup saved: ${dest}"
    pause
}

# ══════════════════════════════════════════════════════════════════
#  6) Restore database
# ══════════════════════════════════════════════════════════════════
restore_database() {
    mkdir -p "${BACKUP_DIR}"
    local files=()
    while IFS= read -r -d '' f; do files+=("$f"); done < <(find "${BACKUP_DIR}" -maxdepth 1 -name "*.db" -print0 2>/dev/null | sort -z)

    if [[ ${#files[@]} -eq 0 ]]; then
        err "No backups found in ${BACKUP_DIR}."
        pause; return
    fi

    echo "Available backups:"
    local i=1
    for f in "${files[@]}"; do
        echo "  ${i}) $(basename "${f}")"
        i=$((i + 1))
    done
    read -rp "Pick a backup number to restore (0 to cancel): " choice
    if [[ -z "${choice}" || "${choice}" == "0" ]]; then
        warn "Cancelled."
        pause; return
    fi
    local idx=$((choice - 1))
    if [[ ${idx} -lt 0 || ${idx} -ge ${#files[@]} ]]; then
        err "Invalid choice."
        pause; return
    fi
    local picked="${files[$idx]}"

    read -rp "This will OVERWRITE the current database with $(basename "${picked}"). Type yes to confirm: " confirm
    if [[ "${confirm}" != "yes" ]]; then
        warn "Cancelled."
        pause; return
    fi

    local was_running=0
    if command -v systemctl >/dev/null 2>&1 && service_exists && systemctl is-active --quiet "${CORE_SERVICE_NAME}"; then
        check_root
        log "Stopping Core service for a safe restore..."
        systemctl stop "${CORE_SERVICE_NAME}"
        was_running=1
    fi

    [[ -f "${DB_FILE}" ]] && cp "${DB_FILE}" "${DB_FILE}.before-restore" 2>/dev/null || true
    cp "${picked}" "${DB_FILE}"
    rm -f "${DB_FILE}-wal" "${DB_FILE}-shm"
    log "Database restored from $(basename "${picked}")."

    if [[ ${was_running} -eq 1 ]]; then
        log "Restarting Core service..."
        systemctl start "${CORE_SERVICE_NAME}"
    fi
    pause
}

# ══════════════════════════════════════════════════════════════════
#  7) Full uninstall
# ══════════════════════════════════════════════════════════════════
uninstall_core() {
    check_root
    echo -e "${RED}${BOLD}This will remove the Core service.${RESET}"
    read -rp "Type yes to confirm: " confirm
    if [[ "${confirm}" != "yes" ]]; then
        warn "Cancelled."
        pause; return
    fi

    if command -v systemctl >/dev/null 2>&1; then
        systemctl stop "${CORE_SERVICE_NAME}" 2>/dev/null || true
        systemctl disable "${CORE_SERVICE_NAME}" 2>/dev/null || true
    fi
    if [[ -f "${CORE_SERVICE_FILE}" ]]; then
        rm -f "${CORE_SERVICE_FILE}"
        command -v systemctl >/dev/null 2>&1 && systemctl daemon-reload
        log "Core service removed."
    fi

    read -rp "Also delete the database (monitorbot.db)? All history will be lost [y/N]: " del_db
    if [[ "${del_db}" =~ ^[Yy]$ ]]; then
        rm -f "${DB_FILE}" "${DB_FILE}-wal" "${DB_FILE}-shm"
        log "Database deleted."
    fi

    read -rp "Also delete the virtualenv (.venv)? [y/N]: " del_venv
    if [[ "${del_venv}" =~ ^[Yy]$ ]]; then
        rm -rf "${VENV_DIR}"
        log "virtualenv deleted."
    fi

    echo ""
    echo -e "${RED}${BOLD}Also remove the entire installation itself?${RESET}"
    echo "This deletes ${SCRIPT_DIR} completely (the whole repo/script) and the"
    echo "global 'rmmonitor' command. You would need to re-run the curl installer"
    echo "or 'git clone' again to use RM Server Monitor after this."
    read -rp "Type DELETE (all caps) to confirm full removal, or press Enter to skip: " full_confirm

    if [[ "${full_confirm}" == "DELETE" ]]; then
        rm -f "/usr/local/bin/rmmonitor"
        log "Global 'rmmonitor' command removed."
        log "Deleting ${SCRIPT_DIR} ..."
        # این آخرین کاری است که این اسکریپت انجام می‌دهد — بعد از این
        # هیچ خط دیگری از فایل خوانده نمی‌شود (exit بلافاصله بعدش)،
        # پس امن است که پوشه‌ی خودِ اسکریپت را همین‌جا حذف کنیم.
        local self_dir="${SCRIPT_DIR}"
        cd /
        rm -rf "${self_dir}"
        echo ""
        echo -e "${C_AMBER}RM Server Monitor has been completely removed. Goodbye!${RESET}"
        exit 0
    fi

    echo ""
    log "Uninstall complete. Source files were left untouched (only the service/database/venv were removed)."
    log "Run this menu again anytime with 'rmmonitor', or choose full removal next time to delete everything."
}

# ══════════════════════════════════════════════════════════════════
#  main menu loop
# ══════════════════════════════════════════════════════════════════
main_loop() {
    while true; do
        print_banner
        print_menu
        read -rp "Choose an option: " choice
        case "${choice}" in
            1) install_core; pause ;;
            2) manage_service ;;
            3) update_system; pause ;;
            4) edit_env; pause ;;
            5) backup_database ;;
            6) restore_database ;;
            7) uninstall_core; pause ;;
            0) echo -e "${C_AMBER}Goodbye!${RESET}"; exit 0 ;;
            *) err "Invalid option."; pause ;;
        esac
    done
}

# نصب اصلی معمولاً با sudo انجام می‌شود (setup.sh این‌طور است)، پس
# تقریباً همه‌ی گزینه‌های این منو (git/venv/service/.env/دیتابیس) روی
# فایل‌های مالکِ root کار می‌کنند. به‌جای اینکه هر گزینه بی‌سروصدا با
# permission denied شکست بخورد، همینجا صریح و زود از کاربر می‌خواهیم.
if [[ "${EUID}" -ne 0 ]]; then
    echo -e "${RED}${BOLD}RM Server Monitor needs root to manage services, git, and files under ${SCRIPT_DIR}.${RESET}"
    echo -e "Re-run with: ${BOLD}sudo rmmonitor${RESET}  (or: sudo bash rmserver.sh)"
    exit 1
fi

main_loop
