#!/usr/bin/env bash
#
# RM Server Monitor — نصب یک‌خطی.
#
#   bash <(curl -Ls https://raw.githubusercontent.com/Ali-Rahmanii/RM-Server-Monitor/main/setup.sh)
#
# این اسکریپت: مخزن را در یک مسیر ثابت کلون می‌کند (یا اگر از قبل
# هست، به‌روزش می‌کند)، دستور سراسری «rmmonitor» را می‌سازد، و در
# پایان خودش منوی تعاملی را باز می‌کند.
#
set -uo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/RM-Server-Monitor}"
REPO_URL="${REPO_URL:-https://github.com/Ali-Rahmanii/RM-Server-Monitor.git}"
BIN_LINK="/usr/local/bin/rmmonitor"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
log()  { echo -e "${GREEN}[setup]${RESET} $*"; }
warn() { echo -e "${YELLOW}[setup] هشدار:${RESET} $*"; }
err()  { echo -e "${RED}[setup] خطا:${RESET} $*" >&2; }
die()  { err "$*"; exit 1; }

if [[ "${EUID}" -ne 0 ]]; then
    die "این اسکریپت باید با root/sudo اجرا شود. مثال:
  curl -Ls https://raw.githubusercontent.com/Ali-Rahmanii/RM-Server-Monitor/main/setup.sh | sudo bash"
fi

echo -e "${CYAN}${BOLD}"
echo "  RM Server Monitor — نصب سریع"
echo -e "${RESET}"

# ── git ──
if ! command -v git >/dev/null 2>&1; then
    log "git پیدا نشد — در حال نصب..."
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq && apt-get install -y -qq git
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y -q git
    elif command -v yum >/dev/null 2>&1; then
        yum install -y -q git
    else
        die "git پیدا نشد و نصب خودکار روی این توزیع ممکن نیست. اول git را دستی نصب کن."
    fi
fi

# ── کلون یا به‌روزرسانی مخزن ──
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    log "نصب قبلی در ${INSTALL_DIR} پیدا شد — به‌روزرسانی..."
    git -C "${INSTALL_DIR}" pull --ff-only || warn "git pull ناموفق بود — با نسخه‌ی فعلی روی دیسک ادامه می‌دهیم."
elif [[ -e "${INSTALL_DIR}" ]]; then
    die "مسیر ${INSTALL_DIR} از قبل وجود دارد ولی یک مخزن گیت نیست.
حذفش کن یا با متغیر INSTALL_DIR=/مسیر/دیگر این اسکریپت را دوباره اجرا کن، مثلاً:
  INSTALL_DIR=/opt/my-monitor bash <(curl -Ls .../setup.sh)"
else
    log "کلون کردن مخزن در ${INSTALL_DIR}..."
    git clone --depth 1 "${REPO_URL}" "${INSTALL_DIR}" || die "کلون مخزن ناموفق بود — اتصال اینترنت یا آدرس مخزن را چک کن."
fi

# ── اجرایی‌کردن اسکریپت‌ها ──
chmod +x "${INSTALL_DIR}/rmserver.sh" 2>/dev/null || true
chmod +x "${INSTALL_DIR}/install.sh" 2>/dev/null || true

# ── دستور سراسری rmmonitor ──
log "ساخت دستور سراسری «rmmonitor»..."
mkdir -p "$(dirname "${BIN_LINK}")"
ln -sf "${INSTALL_DIR}/rmserver.sh" "${BIN_LINK}"

if ! command -v rmmonitor >/dev/null 2>&1; then
    warn "/usr/local/bin ظاهراً در PATH نیست — از این به بعد یا با مسیر کامل اجرا کن (${BIN_LINK}) یا /usr/local/bin را به PATH اضافه کن."
fi

echo ""
log "نصب تمام شد! از این به بعد هرجا بودی کافیه بنویسی: ${BOLD}rmmonitor${RESET}"
echo ""
sleep 1

exec "${BIN_LINK}"
