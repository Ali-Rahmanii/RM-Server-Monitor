#!/usr/bin/env bash
#
# RM Server Monitor — one-line installer.
#
#   bash <(curl -Ls https://raw.githubusercontent.com/Ali-Rahmanii/RM-Server-Monitor/main/setup.sh)
#
# This script: clones the repo to a fixed location (or updates it if
# already present), creates the global "rmmonitor" command, and
# finally opens the interactive menu itself.
#
set -uo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/RM-Server-Monitor}"
REPO_URL="${REPO_URL:-https://github.com/Ali-Rahmanii/RM-Server-Monitor.git}"
BIN_LINK="/usr/local/bin/rmmonitor"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
log()  { echo -e "${GREEN}[setup]${RESET} $*"; }
warn() { echo -e "${YELLOW}[setup] warning:${RESET} $*"; }
err()  { echo -e "${RED}[setup] error:${RESET} $*" >&2; }
die()  { err "$*"; exit 1; }

if [[ "${EUID}" -ne 0 ]]; then
    die "This script must be run as root/sudo. Example:
  curl -Ls https://raw.githubusercontent.com/Ali-Rahmanii/RM-Server-Monitor/main/setup.sh | sudo bash"
fi

echo -e "${CYAN}${BOLD}"
echo "  RM Server Monitor — Quick Setup"
echo -e "${RESET}"

# ── git ──
if ! command -v git >/dev/null 2>&1; then
    log "git not found — installing..."
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq && apt-get install -y -qq git
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y -q git
    elif command -v yum >/dev/null 2>&1; then
        yum install -y -q git
    else
        die "git not found and cannot be auto-installed on this distro. Install git manually first."
    fi
fi

# ── clone or update the repo ──
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    log "Existing install found at ${INSTALL_DIR} — updating..."
    # Plain "git pull --ff-only" routinely fails on a shallow clone
    # (this repo is cloned with --depth 1 below) or on a fresh server
    # with no pull.rebase/pull.ff configured — fetch + reset --hard is
    # bulletproof against both and always lands exactly on origin/main.
    before="$(git -C "${INSTALL_DIR}" rev-parse HEAD 2>/dev/null || echo unknown)"
    if git -C "${INSTALL_DIR}" fetch --all --quiet && git -C "${INSTALL_DIR}" reset --hard origin/main --quiet; then
        after="$(git -C "${INSTALL_DIR}" rev-parse HEAD 2>/dev/null || echo unknown)"
        if [[ "${before}" != "${after}" ]]; then
            log "Updated: ${before:0:7} -> ${after:0:7}"
        else
            log "Already up to date (${after:0:7})."
        fi
    else
        err "git update failed (see error output above) — the version on disk was NOT changed."
        die "Fix the git error, or delete ${INSTALL_DIR} and re-run this installer to get a clean clone."
    fi
elif [[ -e "${INSTALL_DIR}" ]]; then
    die "Path ${INSTALL_DIR} already exists but is not a git repo.
Remove it, or re-run this script with a different path, e.g.:
  INSTALL_DIR=/opt/my-monitor bash <(curl -Ls .../setup.sh)"
else
    log "Cloning the repo into ${INSTALL_DIR}..."
    git clone --depth 1 "${REPO_URL}" "${INSTALL_DIR}" || die "Repo clone failed — check your internet connection or the repo URL."
fi

# ── make scripts executable ──
chmod +x "${INSTALL_DIR}/rmserver.sh" 2>/dev/null || true
chmod +x "${INSTALL_DIR}/install.sh" 2>/dev/null || true

# ── global "rmmonitor" command ──
log "Creating the global \"rmmonitor\" command..."
mkdir -p "$(dirname "${BIN_LINK}")"
ln -sf "${INSTALL_DIR}/rmserver.sh" "${BIN_LINK}"

if ! command -v rmmonitor >/dev/null 2>&1; then
    warn "/usr/local/bin doesn't seem to be in PATH — either run with the full path (${BIN_LINK}) or add /usr/local/bin to your PATH."
fi

# ── restart the Core service if it's already installed & running ──
# Updating the files on disk does nothing for a systemd service that's
# already running the old process in memory — it has to be restarted
# to actually pick up the new code.
if command -v systemctl >/dev/null 2>&1 && [[ -f /etc/systemd/system/monitorbot-core.service ]]; then
    log "Restarting the running monitorbot-core service to load the new code..."
    systemctl restart monitorbot-core || warn "Could not restart monitorbot-core — check: journalctl -u monitorbot-core -n 50"
fi

echo ""
log "Setup complete! From now on, anywhere, just type: ${BOLD}sudo rmmonitor${RESET}"
echo ""
sleep 1

exec "${BIN_LINK}"
