"""پیکربندی سیستم مرکزی — همه از فایل .env کنار main.py خوانده می‌شود."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── تلگرام ───
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_IDS = [
    int(x) for x in os.environ.get("TELEGRAM_ADMIN_IDS", "").replace(" ", "").split(",")
    if x.strip().isdigit()
]

# ─── دیتابیس ───
DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "monitorbot.db"))

# ─── زمان‌بندی (دقیقه) — با /setinterval یا از داشبورد هم قابل تغییر
# است، بدون نیاز به ری‌استارت؛ این فقط مقدار پیش‌فرضِ اولیه است ───
DEFAULT_INTERVAL_MINUTES = int(os.environ.get("MONITOR_INTERVAL_MINUTES", "30"))
MIN_INTERVAL_MINUTES = 1

# ─── داشبورد وب ───
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("WEB_PORT", "8000"))
WEB_USERNAME = os.environ.get("WEB_USERNAME", "admin")
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "changeme")

# ─── آستانه‌ی هشدار بحرانی (درصد) ───
CPU_ALERT_THRESHOLD = float(os.environ.get("CPU_ALERT_THRESHOLD", "90"))
RAM_ALERT_THRESHOLD = float(os.environ.get("RAM_ALERT_THRESHOLD", "90"))
DISK_ALERT_THRESHOLD = float(os.environ.get("DISK_ALERT_THRESHOLD", "90"))

# ─── تایم‌اوت هر فراخوانی به یک ایجنت (ثانیه) ───
AGENT_REQUEST_TIMEOUT = float(os.environ.get("AGENT_REQUEST_TIMEOUT", "15"))

# ─── چند نسخه از تاریخچه‌ی هر سرور نگه داشته شود (برای جلوگیری از
# بزرگ‌شدن بی‌رویه‌ی دیتابیس در اجرای طولانی‌مدت) ───
MAX_LOG_ROWS_PER_SERVER = int(os.environ.get("MAX_LOG_ROWS_PER_SERVER", "2000"))

# ─── استقرار خودکار ایجنت از راه SSH (Auto-Deploy) ───
SSH_CONNECT_TIMEOUT = float(os.environ.get("SSH_CONNECT_TIMEOUT", "20"))
SSH_INSTALL_TIMEOUT = float(os.environ.get("SSH_INSTALL_TIMEOUT", "300"))
AGENT_DEFAULT_PORT = int(os.environ.get("AGENT_DEFAULT_PORT", "5100"))
