<div align="center">

# 🖥 RM Server Monitor

**A modern, self-hosted server monitoring stack — live dashboard, Telegram bot, and one-command SSH auto-deploy.**

[![Version](https://img.shields.io/badge/version-v1.0.0-6366f1?style=flat-square)](https://github.com/Ali-Rahmanii/RM-Server-Monitor/releases)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-34d399?style=flat-square)](LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-Core-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

Developed by **Ali Rahmani** · Telegram [@a_alirahmani](https://t.me/a_alirahmani) · [GitHub](https://github.com/Ali-Rahmanii/RM-Server-Monitor)

</div>

---

![Dashboard](https://via.placeholder.com/1200x650/0a0e17/818cf8?text=RM+Server+Monitor+Dashboard)
![Server Detail](https://via.placeholder.com/1200x650/0a0e17/34d399?text=Live+Charts+%2B+Top+Consumers)

---

## 🇬🇧 English

### What is this?

RM Server Monitor is a two-part system for keeping an eye on a fleet of Linux servers:

- **Agent** — a tiny FastAPI service (port `5100`) you run on every target server. It reports CPU, RAM, disk, network throughput, and the top CPU/RAM-consuming processes, protected by a Bearer token.
- **Core** — a central system with a SQLite-backed scheduler, a Telegram bot, and a glassmorphism web dashboard, all polling your agents and keeping history.

### ✨ Features

- **Live dashboard** — dark, glassmorphism UI (TailwindCSS) with real-time **Chart.js** gauges and time-series charts (CPU/RAM/Disk/Network), auto-refreshing every 2–3 seconds, no page reloads.
- **Top Consumers** — per-server live list of the heaviest CPU/RAM processes.
- **Telegram bot** — `/servers`, `/status`, `/statusall`, `/top`, `/addserver`, `/delserver`, `/setinterval`, with automatic down/recovered/threshold alerts (sent only on state change, not spammed every cycle).
- **SSH Auto-Deploy** — add a server by IP + SSH credentials from the dashboard; Core SSHes in, installs the agent, and registers it automatically. One click to remotely uninstall it too.
- **One-line install** — `bash <(curl -Ls .../setup.sh)` clones the repo, sets up a global `rmmonitor` command, and drops you straight into the menu.
- **`install.sh`** — a self-contained installer/uninstaller/updater for the agent, with a `systemd` service (`monitorbot-agent`), safe port-in-use pre-check, and idempotent updates that preserve the existing token.
- **`rmserver.sh`** — an interactive, colored CLI menu to install Core as a `systemd` service, manage it, pull updates (and cascade the update to every SSH-deployed agent), or cleanly uninstall.
- **Systemd support** end-to-end — both Agent and Core can run as always-on, auto-restarting services.

### 🚀 Quick Start

One command, that's it:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/Ali-Rahmanii/RM-Server-Monitor/main/setup.sh)
```

This clones the repo to `/opt/RM-Server-Monitor`, creates a global `rmmonitor` command, and immediately opens the interactive menu. From there pick **1) Install Core System** — it will:
1. Create a Python virtualenv and install dependencies.
2. Copy `.env.example` → `.env` (edit this afterwards — at minimum change `WEB_PASSWORD`, and set `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ADMIN_IDS` if you want the bot active).
3. Create and start a `monitorbot-core` systemd service.

From now on, open the menu **anytime, from anywhere**, by just typing:

```bash
rmmonitor
```

<details>
<summary>Prefer manual clone?</summary>

```bash
git clone https://github.com/Ali-Rahmanii/RM-Server-Monitor.git
cd RM-Server-Monitor
sudo bash rmserver.sh
```
</details>

### 🌐 Using the Dashboard

Once Core is running, open:

```
http://<your-server-ip>:8000
```

Log in with the `WEB_USERNAME` / `WEB_PASSWORD` from your `.env` (HTTP Basic Auth). From there you can:
- Click **🚀 Auto-Deploy (SSH)** to add a new server just by giving its IP + SSH login — no manual agent install needed.
- Click any server card to see live charts and top processes.
- Use **🧨 Remote Uninstall** to cleanly remove the agent from a server via SSH.

### 🤖 Telegram Bot

Set `TELEGRAM_BOT_TOKEN` (from [@BotFather](https://t.me/BotFather)) and `TELEGRAM_ADMIN_IDS` (your numeric Telegram user ID) in `.env`, then restart Core (`rmserver.sh` → option 2 → Restart). See [monitorbot/README.md](README.md) commands table below.

### 🔄 Updating

```bash
sudo bash rmserver.sh
```
Choose **3) Update System** — this pulls the latest code, updates Python packages, restarts Core, and remotely re-runs the installer on every SSH-deployed agent to keep them current.

### 🗑 Uninstalling

`sudo bash rmserver.sh` → **4) Uninstall**. You'll be asked separately whether to also delete the database and the virtualenv; source files are left untouched.

### 📂 Project Structure

```
RM-Server-Monitor/
├── agent/            # Lightweight monitoring API (deploy to each target server)
├── core/              # Dashboard, scheduler, Telegram bot, SSH deployer
├── setup.sh            # One-line curl installer (clones repo, creates `rmmonitor`)
├── install.sh         # Self-contained agent installer/updater/uninstaller
├── rmserver.sh         # Interactive Core management CLI (aliased as `rmmonitor`)
├── main.py            # Core entry point
└── requirements.txt
```

### 🔒 Security Notes

- The agent rejects **all** requests if `AGENT_TOKEN` isn't set — secure by default.
- Token comparisons use `secrets.compare_digest` (timing-attack safe).
- Change `WEB_PASSWORD` immediately — it also guards the SSH deploy/uninstall endpoints.
- SSH credentials for auto-deployed servers are stored in `monitorbot.db` for later remote-uninstall use; prefer SSH keys over passwords, and restrict access to the database file.

---

## 🇮🇷 فارسی

### این پروژه چیست؟

RM Server Monitor یک سیستم مانیتورینگ دو بخشی برای مدیریت چند سرور لینوکسی است:

- **Agent (ایجنت)** — یک API سبک (FastAPI) روی پورت `5100` که روی هر سرور هدف نصب می‌شود و CPU، RAM، دیسک، ترافیک شبکه و پرمصرف‌ترین پردازش‌ها را با احراز هویت Bearer Token گزارش می‌دهد.
- **Core (سیستم مرکزی)** — دیتابیس SQLite + زمان‌بند + ربات تلگرام + داشبورد وب با ظاهر شیشه‌ای (glassmorphism) که همه‌ی ایجنت‌ها را چک می‌کند و تاریخچه نگه می‌دارد.

### ✨ امکانات

- **داشبورد زنده** — رابط تاریک و شیشه‌ای با TailwindCSS، گیج‌ها و نمودارهای زمانی زنده با **Chart.js** برای CPU/RAM/دیسک/شبکه، به‌روزرسانی خودکار هر ۲ تا ۳ ثانیه بدون رفرش صفحه.
- **پرمصرف‌ترین‌ها** — لیست زنده‌ی پردازش‌های پرمصرف CPU/RAM هر سرور.
- **ربات تلگرام** — دستورات `/servers`، `/status`، `/statusall`، `/top`، `/addserver`، `/delserver`، `/setinterval` با هشدار خودکار قطعی/بازگشت/عبور از آستانه (فقط روی تغییر وضعیت، بدون اسپم).
- **استقرار خودکار SSH** — افزودن سرور فقط با آی‌پی و اطلاعات SSH از داخل داشبورد؛ سیستم مرکزی خودش وصل می‌شود، ایجنت را نصب و ثبت می‌کند. حذف از راه دور هم با یک کلیک.
- **نصب یک‌خطی** — با `bash <(curl -Ls .../setup.sh)` مخزن کلون می‌شود، دستور سراسری `rmmonitor` ساخته می‌شود، و مستقیم وارد منو می‌شوی.
- **`install.sh`** — نصب/حذف/به‌روزرسانی خودکفای ایجنت، با سرویس systemd (`monitorbot-agent`)، بررسی امن اشغال‌نبودن پورت، و به‌روزرسانی idempotent که توکن موجود را حفظ می‌کند.
- **`rmserver.sh`** — منوی رنگی و تعاملی برای نصب Core به‌عنوان سرویس systemd، مدیریت آن، دریافت آپدیت (و انتقال آپدیت به همه‌ی ایجنت‌های نصب‌شده با SSH)، یا حذف تمیز.
- **پشتیبانی کامل از systemd** — هم Agent و هم Core می‌توانند به‌صورت سرویس همیشه-روشن با auto-restart اجرا شوند.

### 🚀 شروع سریع

فقط یک دستور:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/Ali-Rahmanii/RM-Server-Monitor/main/setup.sh)
```

این دستور مخزن را در `/opt/RM-Server-Monitor` کلون می‌کند، دستور سراسری `rmmonitor` را می‌سازد، و بلافاصله منوی تعاملی را باز می‌کند. از آنجا گزینه‌ی **۱) نصب سیستم مرکزی** را انتخاب کن — این کار:
۱. یک virtualenv پایتون می‌سازد و وابستگی‌ها را نصب می‌کند.
۲. فایل `.env.example` را در `.env` کپی می‌کند (بعداً حتماً ویرایشش کن — حداقل `WEB_PASSWORD` را عوض کن، و اگر می‌خواهی ربات فعال باشد `TELEGRAM_BOT_TOKEN`/`TELEGRAM_ADMIN_IDS` را هم تنظیم کن).
۳. سرویس systemd به اسم `monitorbot-core` می‌سازد و اجرا می‌کند.

از این به بعد، **هر وقت و هرجا** خواستی منو را دوباره باز کنی، کافیه بنویسی:

```bash
rmmonitor
```

<details>
<summary>ترجیح می‌دهی دستی کلون کنی؟</summary>

```bash
git clone https://github.com/Ali-Rahmanii/RM-Server-Monitor.git
cd RM-Server-Monitor
sudo bash rmserver.sh
```
</details>

### 🌐 استفاده از داشبورد

بعد از بالا آمدن Core، این آدرس را باز کن:

```
http://<آی‌پی-سرور>:8000
```

با `WEB_USERNAME`/`WEB_PASSWORD` فایل `.env` وارد شو (HTTP Basic Auth). از آنجا می‌توانی:
- روی **🚀 استقرار خودکار (SSH)** بزنی و فقط با آی‌پی و اطلاعات SSH سرور جدید اضافه کنی — بدون نصب دستی.
- روی هر کارت سرور بزنی تا نمودارهای زنده و پردازش‌های پرمصرف را ببینی.
- از **🧨 حذف از راه دور** برای پاک‌کردن کامل ایجنت از یک سرور (از طریق SSH) استفاده کنی.

### 🤖 ربات تلگرام

`TELEGRAM_BOT_TOKEN` (از [@BotFather](https://t.me/BotFather)) و `TELEGRAM_ADMIN_IDS` (آی‌دی عددی تلگرام خودت) را در `.env` تنظیم کن، بعد Core را ری‌استارت کن (`rmserver.sh` ← گزینه ۲ ← Restart).

### 🔄 به‌روزرسانی

```bash
sudo bash rmserver.sh
```
گزینه‌ی **۳) به‌روزرسانی سیستم** را انتخاب کن — آخرین کد را از گیت می‌گیرد، پکیج‌های پایتون را به‌روز می‌کند، Core را ری‌استارت می‌کند، و نصب‌کننده را از راه دور روی همه‌ی ایجنت‌های نصب‌شده با SSH دوباره اجرا می‌کند تا آن‌ها هم به‌روز بمانند.

### 🗑 حذف

`sudo bash rmserver.sh` ← **۴) حذف کامل**. جداگانه از تو می‌پرسد که آیا دیتابیس و virtualenv هم حذف شوند؛ فایل‌های سورس دست‌نخورده باقی می‌مانند.

### 🔒 نکات امنیتی

- ایجنت اگر `AGENT_TOKEN` تنظیم نشده باشد همه‌ی درخواست‌ها را رد می‌کند — پیش‌فرض امن.
- مقایسه‌ی توکن با `secrets.compare_digest` انجام می‌شود (ضد حمله‌ی timing).
- حتماً `WEB_PASSWORD` را عوض کن — همین رمز روی endpoint های استقرار/حذف SSH هم محافظت اعمال می‌کند.
- اطلاعات SSH سرورهایی که با Auto-Deploy ساخته شدند برای استفاده‌ی بعدی (حذف از راه دور) در `monitorbot.db` ذخیره می‌شوند؛ ترجیحاً از کلید SSH به‌جای رمز عبور استفاده کن و دسترسی به فایل دیتابیس را محدود نگه دار.

---

<div align="center">

**⭐ اگر این پروژه به کارت اومد، یه ستاره بده! / If this project helped you, please star it! ⭐**

[Ali Rahmani](https://github.com/Ali-Rahmanii) · [Telegram](https://t.me/a_alirahmani) · [Report an Issue](https://github.com/Ali-Rahmanii/RM-Server-Monitor/issues)

</div>
