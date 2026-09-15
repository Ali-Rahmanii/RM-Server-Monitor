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

import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# کنسول ویندوز معمولاً با codepage cp1252 اجرا می‌شود که نمی‌تواند
# متن فارسی/ایموجی را چاپ کند — خروجی را صریحاً روی UTF-8 می‌گذاریم.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

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
    })


if __name__ == "__main__":
    import uvicorn

    if not AGENT_TOKEN:
        print("⚠️  AGENT_TOKEN تنظیم نشده — /status هیچ درخواستی را قبول نمی‌کند.")
        print("    مقدارش را در agent/.env بگذار، مثلاً: AGENT_TOKEN=یک-رشته-تصادفی-طولانی")

    print(f"🚀 Monitorbot Agent روی پورت {AGENT_PORT} اجرا می‌شود (میزبان: {socket.gethostname()})")
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)
