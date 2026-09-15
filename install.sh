#!/usr/bin/env bash
#
# Monitorbot Agent — نصب/حذف خودکار روی سرور هدف.
# این اسکریپت کاملاً خودکفا است (هیچ فایل دیگری لازم ندارد) تا با
# curl مستقیم قابل اجرا باشد:
#
#   curl -fsSL https://raw.githubusercontent.com/<user>/<repo>/main/install.sh | sudo bash
#   curl -fsSL .../install.sh | sudo bash -s -- --uninstall
#
# یا به‌صورت محلی:
#   sudo bash install.sh
#   sudo bash install.sh --uninstall
#
set -euo pipefail

AGENT_PORT="${AGENT_PORT:-5100}"
INSTALL_DIR="${INSTALL_DIR:-/opt/monitorbot-agent}"
SERVICE_NAME="monitorbot-agent"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

log()  { echo -e "[monitorbot-agent] $*"; }
err()  { echo -e "[monitorbot-agent] خطا: $*" >&2; }
die()  { err "$*"; exit 1; }

# ══════════════════════════════════════════════════════════════════
#  حذف
# ══════════════════════════════════════════════════════════════════
do_uninstall() {
    log "شروع حذف ایجنت..."

    if command -v systemctl >/dev/null 2>&1; then
        systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
        systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
    fi

    if [[ -f "${SERVICE_FILE}" ]]; then
        rm -f "${SERVICE_FILE}"
        log "فایل سرویس systemd حذف شد."
    fi

    if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload 2>/dev/null || true
        systemctl reset-failed "${SERVICE_NAME}" 2>/dev/null || true
    fi

    if [[ -d "${INSTALL_DIR}" ]]; then
        rm -rf "${INSTALL_DIR}"
        log "پوشه‌ی نصب (${INSTALL_DIR}) حذف شد."
    fi

    sleep 1
    if (echo > "/dev/tcp/127.0.0.1/${AGENT_PORT}") 2>/dev/null; then
        err "پورت ${AGENT_PORT} همچنان در حال استفاده است (شاید پروسه‌ی دیگری آن را گرفته)."
    else
        log "پورت ${AGENT_PORT} آزاد شد."
    fi

    log "حذف کامل شد. STATUS=UNINSTALLED"
}

# ══════════════════════════════════════════════════════════════════
#  نصب
# ══════════════════════════════════════════════════════════════════
check_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        die "این اسکریپت برای ساخت systemd service و نصب پکیج باید با root/sudo اجرا شود."
    fi
}

check_port_free() {
    log "بررسی آزاد بودن پورت ${AGENT_PORT}..."
    if (echo > "/dev/tcp/127.0.0.1/${AGENT_PORT}") 2>/dev/null; then
        die "پورت ${AGENT_PORT} از قبل در حال استفاده است. نصب متوقف شد. (اگر می‌خواهی دوباره نصب کنی، اول با --uninstall حذف کن)"
    fi
    log "پورت ${AGENT_PORT} آزاد است."
}

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
            die "python3 پیدا نشد و امکان نصب خودکار روی این توزیع وجود ندارد. اول python3 را دستی نصب کن."
        fi
    fi

    # نکته‌ی مهم: "python3 -m venv --help" حتی بدون ensurepip هم موفق
    # برمی‌گردد (فقط متن راهنما را چاپ می‌کند) — پس این چک قدیمی هیچ‌وقت
    # مشکل واقعی را تشخیص نمی‌داد. روی خیلی از اوبونتوهای جدید، پکیج
    # عمومی python3-venv بدون بسته‌ی نسخه‌محورِ pythonX.Y-venv کامل
    # نیست و ساخت واقعی virtualenv با خطای «ensurepip is not available»
    # شکست می‌خورد. تنها راه مطمئن، یک تست واقعیِ ساخت venv است.
    local test_dir venv_ok=0
    test_dir="$(mktemp -d)"
    if python3 -m venv "${test_dir}/venv" >/dev/null 2>&1 && [[ -x "${test_dir}/venv/bin/pip" ]]; then
        venv_ok=1
    fi
    rm -rf "${test_dir}"

    if [[ "${venv_ok}" -eq 0 ]]; then
        log "ماژول venv کامل نیست (احتمالاً ensurepip موجود نیست) — تلاش برای نصب..."
        if command -v apt-get >/dev/null 2>&1; then
            apt-get update -qq
            apt-get install -y -qq python3-venv python3-pip 2>/dev/null || true
            # پکیج نسخه‌محور دقیق (مثلاً python3.12-venv) معمولاً همان
            # چیزی است که واقعاً ensurepip را می‌آورد
            local pyver
            pyver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
            if [[ -n "${pyver}" ]]; then
                apt-get install -y -qq "python${pyver}-venv" 2>/dev/null || true
            fi
        elif command -v dnf >/dev/null 2>&1; then
            dnf install -y -q python3-pip >/dev/null 2>&1 || true
        elif command -v yum >/dev/null 2>&1; then
            yum install -y -q python3-pip >/dev/null 2>&1 || true
        fi

        # دوباره تست می‌کنیم — اگر بازم نشد، همینجا با پیام روشن متوقف
        # می‌شویم به‌جای اینکه بذاریم setup_venv_and_service با خطای
        # مبهم‌تر شکست بخورد
        test_dir="$(mktemp -d)"
        if python3 -m venv "${test_dir}/venv" >/dev/null 2>&1 && [[ -x "${test_dir}/venv/bin/pip" ]]; then
            venv_ok=1
        fi
        rm -rf "${test_dir}"

        if [[ "${venv_ok}" -eq 0 ]]; then
            local pyver_hint="${pyver:-3.X}"
            die "ساخت virtualenv پایتون ناموفق بود (ensurepip در دسترس نیست). این دستور را دستی روی سرور اجرا کن و دوباره تلاش کن: apt install -y python${pyver_hint}-venv"
        fi
    fi
}

# نصب و راه‌اندازی vnstat برای گرفتن کل ترافیک واقعی مصرفی (نه فقط
# سرعت لحظه‌ای) — اختیاری: اگر نصب نشود، ایجنت بدون این بخش کار می‌کند.
ensure_vnstat() {
    if ! command -v vnstat >/dev/null 2>&1; then
        log "نصب vnstat برای آمار کل ترافیک واقعی..."
        if command -v apt-get >/dev/null 2>&1; then
            DEBIAN_FRONTEND=noninteractive apt-get update -qq
            DEBIAN_FRONTEND=noninteractive apt-get install -y -qq vnstat
        elif command -v dnf >/dev/null 2>&1; then
            dnf install -y -q vnstat
        elif command -v yum >/dev/null 2>&1; then
            yum install -y -q vnstat
        else
            warn "vnstat روی این توزیع خودکار نصب نمی‌شود — آمار کل ترافیک در دسترس نخواهد بود."
            return
        fi
    fi

    if ! command -v vnstat >/dev/null 2>&1; then
        warn "نصب vnstat ناموفق بود — آمار کل ترافیک در دسترس نخواهد بود."
        return
    fi

    local iface
    iface="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="dev") print $(i+1)}' | head -n1)"
    if [[ -z "${iface}" ]]; then
        iface="$(ls /sys/class/net 2>/dev/null | grep -v '^lo$' | head -n1)"
    fi
    if [[ -n "${iface}" ]]; then
        vnstat --add -i "${iface}" >/dev/null 2>&1 || true
        if command -v systemctl >/dev/null 2>&1; then
            systemctl enable --now vnstat >/dev/null 2>&1 || true
        fi
        log "vnstat روی رابط شبکه‌ی ${iface} فعال شد."
    else
        warn "رابط شبکه‌ی اصلی پیدا نشد — در صورت نیاز vnstat را دستی راه‌اندازی کن."
    fi
}

write_agent_files() {
    mkdir -p "${INSTALL_DIR}"
    log "نوشتن فایل‌های ایجنت در ${INSTALL_DIR}..."

    cat > "${INSTALL_DIR}/requirements.txt" <<'REQ_EOF'
fastapi>=0.110
uvicorn[standard]>=0.27
psutil>=5.9
python-dotenv>=1.0
REQ_EOF

    cat > "${INSTALL_DIR}/agent.py" <<'AGENT_EOF'
"""
Monitorbot Agent — یک API سبک که روی هر سرور هدف اجرا می‌شود و
وضعیت سخت‌افزار/شبکه/پردازش‌های آن سرور را برمی‌گرداند.

اجرا روی هر سرور هدف:
    pip install -r requirements.txt
    python agent.py

پیش از اجرا، AGENT_TOKEN را در agent/.env تنظیم کن — سیستم مرکزی
باید دقیقاً همین توکن را به‌صورت Bearer برای دسترسی به /status بفرستد.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# کنسول ویندوز معمولاً با codepage cp1252 اجرا می‌شود که نمی‌تواند
# متن فارسی/ایموجی را چاپ کند — خروجی را صریحاً روی UTF-8 می‌گذاریم.

import psutil
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

import secrets

AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "").strip()
AGENT_PORT = int(os.environ.get("AGENT_PORT", "5100"))
TOP_N = int(os.environ.get("AGENT_TOP_N", "5"))

app = FastAPI(title="Monitorbot Agent", version="1.0.0")

_boot_time = time.time()


def _check_token(authorization: Optional[str]) -> None:
    """
    ⚠️ پیش‌فرض امن: اگر AGENT_TOKEN اصلاً تنظیم نشده باشد، ایجنت به‌جای
    باز ماندن بدون احرازهویت، همه‌ی درخواست‌ها را رد می‌کند.
    """
    if not AGENT_TOKEN:
        raise HTTPException(status_code=503, detail="AGENT_TOKEN روی این ایجنت تنظیم نشده است")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token یافت نشد")
    provided = authorization[len("Bearer "):].strip()
    # مقایسه‌ی زمان‌ثابت — جلوگیری از حمله‌ی timing روی توکن
    if not secrets.compare_digest(provided, AGENT_TOKEN):
        raise HTTPException(status_code=401, detail="توکن نامعتبر است")


@app.get("/health")
def health():
    """بدون نیاز به توکن — فقط برای تشخیص بالا/پایین بودن خودِ ایجنت."""
    return {"status": "ok", "uptime_seconds": round(time.time() - _boot_time, 1)}


def _collect_processes(limit: int) -> Dict[str, List[Dict[str, Any]]]:
    """
    ⚠️ نکته‌ی مهم درباره‌ی دقت: psutil برای cpu_percent هر پروسه به دو
    نمونه‌گیری با فاصله نیاز دارد — فراخوانی اول همیشه ۰ برمی‌گرداند.
    اینجا اول یک نمونه‌ی «گرم‌کننده» می‌گیریم، کمی صبر می‌کنیم، و بعد
    نمونه‌ی واقعی را می‌خوانیم — وگرنه لیست «پرمصرف‌ترین‌ها» همیشه خالی
    یا نادرست می‌شد.
    """
    snapshot = list(psutil.process_iter(["pid", "name", "username"]))
    for p in snapshot:
        try:
            p.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    time.sleep(0.3)

    procs = []
    for p in snapshot:
        try:
            cpu = p.cpu_percent(interval=None)
            ram_pct = p.memory_percent()
            info = p.info
            procs.append({
                "pid": info.get("pid"),
                "name": info.get("name") or "?",
                "user": info.get("username") or "?",
                "cpu_percent": round(cpu, 1),
                "ram_percent": round(ram_pct, 1),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    top_cpu = sorted(procs, key=lambda x: x["cpu_percent"], reverse=True)[:limit]
    top_ram = sorted(procs, key=lambda x: x["ram_percent"], reverse=True)[:limit]
    return {"top_cpu": top_cpu, "top_ram": top_ram}


def _get_vnstat_traffic() -> Optional[Dict[str, Any]]:
    """
    کل ترافیک واقعیِ مصرف‌شده (نه سرعت لحظه‌ای) از vnstat، اگر روی
    سرور نصب باشد (با install.sh نصب می‌شود). خروجی JSON نسخه‌ی 1.x
    vnstat بر حسب KiB است و نسخه‌ی 2.x بر حسب بایت خام — این تفاوت
    اینجا نرمال‌سازی می‌شود. اگر vnstat نصب نباشد یا خروجی غیرمنتظره
    بدهد، None برمی‌گردد (این ویژگی هیچ‌وقت نباید /status را خراب کند).
    """
    try:
        result = subprocess.run(
            ["vnstat", "--json"], capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        data = json.loads(result.stdout)
        interfaces = data.get("interfaces") or []
        if not interfaces:
            return None
        iface = interfaces[0]
        total = (iface.get("traffic") or {}).get("total") or {}
        rx, tx = total.get("rx"), total.get("tx")
        if rx is None or tx is None:
            return None
        version = str(data.get("vnstatversion", "2"))
        if version.startswith("1."):
            rx, tx = rx * 1024, tx * 1024
        return {
            "iface": iface.get("name") or iface.get("id") or "?",
            "rx_bytes": float(rx),
            "tx_bytes": float(tx),
        }
    except Exception:
        return None


@app.get("/status")
def status(authorization: Optional[str] = Header(default=None)):
    _check_token(authorization)

    # CPU: یک نمونه‌ی کوتاه برای عدد لحظه‌ایِ معنادار (نه ۰ فوری)
    cpu_percent = psutil.cpu_percent(interval=0.3)
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
    load_avg = None
    try:
        load_avg = list(os.getloadavg())  # فقط لینوکس/مک
    except (AttributeError, OSError):
        pass

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        disks.append({
            "mountpoint": part.mountpoint,
            "device": part.device,
            "fstype": part.fstype,
            "total_gb": round(usage.total / (1024 ** 3), 2),
            "used_gb": round(usage.used / (1024 ** 3), 2),
            "percent": usage.percent,
        })

    # ⏱ پهنای باند لحظه‌ای: دو نمونه از شمارنده‌های تجمعی با فاصله‌ی
    # کوتاه، تا نرخ واقعی بایت‌بر‌ثانیه به‌دست بیاید — نه فقط عدد کل
    # از زمان بوت که برای مانیتورینگ لحظه‌ای بی‌فایده است.
    io1 = psutil.net_io_counters()
    time.sleep(0.5)
    io2 = psutil.net_io_counters()
    sent_rate = max(0, io2.bytes_sent - io1.bytes_sent) * 2  # bytes/sec (نمونه ۰.۵ ثانیه‌ای)
    recv_rate = max(0, io2.bytes_recv - io1.bytes_recv) * 2

    disk_percent_max = max((d["percent"] for d in disks), default=0)

    return JSONResponse({
        "hostname": socket.gethostname(),
        "timestamp": time.time(),
        "cpu": {
            "percent": cpu_percent,
            "per_core": cpu_per_core,
            "core_count": psutil.cpu_count(),
            "load_avg_1_5_15": load_avg,
        },
        "memory": {
            "total_gb": round(mem.total / (1024 ** 3), 2),
            "used_gb": round(mem.used / (1024 ** 3), 2),
            "percent": mem.percent,
            "swap_percent": swap.percent,
        },
        "disks": disks,
        "disk_percent_max": disk_percent_max,
        "network": {
            "bytes_sent_total": io2.bytes_sent,
            "bytes_recv_total": io2.bytes_recv,
            "sent_bytes_per_sec": round(sent_rate, 1),
            "recv_bytes_per_sec": round(recv_rate, 1),
        },
        "processes": _collect_processes(TOP_N),
        "traffic_total": _get_vnstat_traffic(),
    })


if __name__ == "__main__":
    import uvicorn

    if not AGENT_TOKEN:
        print("⚠️  AGENT_TOKEN تنظیم نشده — /status هیچ درخواستی را قبول نمی‌کند.")
        print("    مقدارش را در agent/.env بگذار، مثلاً: AGENT_TOKEN=یک-رشته-تصادفی-طولانی")

    print(f"🚀 Monitorbot Agent روی پورت {AGENT_PORT} اجرا می‌شود (میزبان: {socket.gethostname()})")
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)

AGENT_EOF
}

generate_token() {
    python3 -c "import secrets; print(secrets.token_urlsafe(32))"
}

write_systemd_service() {
    cat > "${SERVICE_FILE}" <<SERVICE_EOF
[Unit]
Description=Monitorbot Agent (monitoring API on port ${AGENT_PORT})
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/agent.py
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
SERVICE_EOF
}

# mode: "install" (نصب تازه، توکن جدید) یا "update" (فقط کد/پکیج‌ها را
# تازه می‌کند، اگر .env از قبل هست توکن دست‌نخورده می‌ماند تا ثبت سرور
# در سیستم مرکزی خراب نشود)
setup_venv_and_service() {
    local mode="$1"

    if [[ ! -x "${INSTALL_DIR}/venv/bin/pip" ]]; then
        log "ساخت virtualenv..."
        python3 -m venv "${INSTALL_DIR}/venv"
    fi
    if [[ ! -x "${INSTALL_DIR}/venv/bin/pip" ]]; then
        die "ساخت virtualenv ناموفق بود (pip در venv وجود ندارد). آیا python3-venv نصب است؟"
    fi

    log "نصب/به‌روزرسانی پکیج‌های پایتون..."
    "${INSTALL_DIR}/venv/bin/pip" install --upgrade pip -q
    "${INSTALL_DIR}/venv/bin/pip" install --upgrade -r "${INSTALL_DIR}/requirements.txt" -q

    local token=""
    if [[ "${mode}" == "update" && -f "${INSTALL_DIR}/.env" ]]; then
        log "فایل .env موجود است — توکن قبلی حفظ می‌شود."
        token="$(sed -n 's/^AGENT_TOKEN=//p' "${INSTALL_DIR}/.env" | head -n1)"
    fi
    if [[ -z "${token}" ]]; then
        token="$(generate_token)"
        cat > "${INSTALL_DIR}/.env" <<ENV_EOF
AGENT_TOKEN=${token}
AGENT_PORT=${AGENT_PORT}
AGENT_TOP_N=5
ENV_EOF
        chmod 600 "${INSTALL_DIR}/.env"
    fi

    if command -v systemctl >/dev/null 2>&1; then
        log "ساخت/به‌روزرسانی systemd service..."
        write_systemd_service
        systemctl daemon-reload
        systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1 || true
        systemctl restart "${SERVICE_NAME}"

        sleep 2
        if systemctl is-active --quiet "${SERVICE_NAME}"; then
            log "سرویس ${SERVICE_NAME} فعال است."
        else
            err "سرویس بالا نیامد. لاگ را با این دستور ببین: journalctl -u ${SERVICE_NAME} -n 50"
            exit 1
        fi
    else
        err "systemctl پیدا نشد — سرویس به‌صورت دستی در پس‌زمینه اجرا می‌شود (بدون auto-restart)."
        pkill -f "${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/agent.py" 2>/dev/null || true
        nohup "${INSTALL_DIR}/venv/bin/python" "${INSTALL_DIR}/agent.py" > "${INSTALL_DIR}/agent.log" 2>&1 &
        disown
        sleep 2
    fi

    # چک سلامت نهایی
    if (echo > "/dev/tcp/127.0.0.1/${AGENT_PORT}") 2>/dev/null; then
        log "ایجنت روی پورت ${AGENT_PORT} در حال گوش‌دادن است."
    else
        err "ایجنت روی پورت ${AGENT_PORT} پاسخ نمی‌دهد."
        exit 1
    fi

    echo ""
    echo "AGENT_TOKEN=${token}"
    echo "AGENT_PORT=${AGENT_PORT}"
    if [[ "${mode}" == "update" ]]; then
        echo "STATUS=UPDATED"
    else
        echo "STATUS=OK"
    fi
}

do_install() {
    check_root
    # اگر سرویس monitorbot-agent از قبل روی این سرور نصب است، «نصب»
    # دوباره نباید با خطای «پورت اشغال است» شکست بخورد — چون همان پورت
    # را خودِ همین سرویس گرفته. به‌جایش خودکار به مسیر آپدیت می‌رویم
    # (کد/پکیج‌ها را تازه می‌کند، توکن موجود را حفظ می‌کند) تا نیازی
    # به --uninstall دستی قبل از هر نصب دوباره نباشد.
    if [[ -f "${SERVICE_FILE}" ]]; then
        log "ایجنت Monitorbot از قبل روی این سرور نصب است — به‌جای نصب از صفر، آپدیتش می‌کنیم."
        do_update
        return
    fi
    check_port_free
    ensure_python
    # vnstat کاملاً اختیاری است — هر مشکلی در نصبش (apt قفل، ریپازیتوری
    # خراب، توزیع ناشناخته و ...) نباید کل نصب ایجنت را متوقف کند
    ensure_vnstat || warn "راه‌اندازی vnstat ناموفق بود — بدون آن ادامه می‌دهیم (این ویژگی اختیاری است)."
    write_agent_files
    setup_venv_and_service "install"
}

do_update() {
    check_root
    log "شروع به‌روزرسانی ایجنت..."
    mkdir -p "${INSTALL_DIR}"
    ensure_python
    ensure_vnstat || warn "راه‌اندازی vnstat ناموفق بود — بدون آن ادامه می‌دهیم (این ویژگی اختیاری است)."
    write_agent_files
    setup_venv_and_service "update"
}

# ══════════════════════════════════════════════════════════════════
#  ورودی
# ══════════════════════════════════════════════════════════════════
case "${1:-}" in
    --uninstall)
        check_root
        do_uninstall
        ;;
    --update)
        do_update
        ;;
    *)
        do_install
        ;;
esac
