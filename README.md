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

- **Live dashboard** — dark, glassmorphism UI (TailwindCSS) with separately toggleable **Chart.js** charts per server (CPU, RAM, Disk, Network — hide/show each with the 👁️ button), auto-refreshing every 2–3 seconds, no page reloads.
- **Top Consumers** — per-server live list of the heaviest CPU/RAM processes.
- **Real total traffic** — the agent auto-installs and reads `vnstat`, so you see actual lifetime Rx/Tx bandwidth consumed, not just the live transfer rate — shown on cards, the detail view, and in bot reports.
- **Telegram bot** — 100% English, entirely inline-keyboard driven (no text commands to memorize): browse servers, view live stats and top processes, add servers (manual or SSH auto-deploy), remote-uninstall, adjust settings, and back up/restore the database — all with buttons. Automatic down/recovered/threshold alerts (sent only on state change) plus optional periodic summary reports (average CPU/RAM over a configurable period).
- **SSH Auto-Deploy** — add a server by IP + SSH credentials from the dashboard or the bot; Core SSHes in, installs the agent, and registers it automatically. One click to remotely uninstall it too.
- **Adjustable check interval & DB backup/restore** — change the global scan interval from the dashboard's Settings panel, and download/upload the SQLite database as a backup, right from the browser (or the bot).
- **One-line install** — `bash <(curl -Ls .../setup.sh)` clones the repo, sets up a global `rmmonitor` command, and drops you straight into the menu.
- **`install.sh`** — a self-contained installer/uninstaller/updater for the agent (plus `vnstat` setup), with a `systemd` service (`monitorbot-agent`), safe port-in-use pre-check, and idempotent updates that preserve the existing token.
- **`rmserver.sh`** — an interactive, colored CLI menu (GTA Sunset theme 🌅) to install Core as a `systemd` service, manage it, edit `.env`, pull updates (cascading to every SSH-deployed agent), back up/restore the database, or cleanly uninstall.
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
sudo rmmonitor
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

Set `TELEGRAM_BOT_TOKEN` (from [@BotFather](https://t.me/BotFather)) and `TELEGRAM_ADMIN_IDS` (your numeric Telegram user ID) in `.env`, then restart Core (`rmserver.sh` → option 2 → Restart). Send `/start` — everything from there is inline buttons (glass keyboard), no commands to remember:

- 📋 **Servers** — live status, refresh, top processes, add a server (manual token or SSH auto-deploy), delete from DB, or remote-uninstall via SSH.
- ⚙️ **Settings** — change the check interval, and turn on periodic summary reports (average CPU/RAM per server over a period you choose — e.g. every 12h).
- 💾 **Backup & Restore** — tap to receive `monitorbot.db` as a document, or reply with a `.db` file to restore it.

### 🔄 Updating

```bash
sudo bash rmserver.sh
```
Choose **3) Update System** — this pulls the latest code, updates Python packages, restarts Core, and remotely re-runs the installer on every SSH-deployed agent to keep them current.

The menu also has **4) Edit .env**, **5) Backup Database**, and **6) Restore Database** (lists backups from a local `backups/` folder and restores your pick).

### 🗑 Uninstalling

`sudo bash rmserver.sh` → **7) Uninstall**. You'll be asked separately whether to also delete the database and the virtualenv, and — as a final, explicitly-confirmed step — whether to remove the entire installation and the global `rmmonitor` command too. Skip that last step and source files are left untouched.

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

### 🛠 Troubleshooting SSH Deploy / Update Failures

If adding, updating, or remote-uninstalling a server via SSH fails, the web dashboard and the Telegram bot both now show the **actual output** of the remote install script, plus a suggested fix when the error matches a known pattern. You don't need to SSH in and dig through `journalctl` for these — a few common ones:

- **`ensurepip is not available` / venv creation fails** — the target server's `python3-venv` package is incomplete (common on newer Ubuntu images, where the version-specific package like `python3.12-venv` isn't pulled in automatically). `install.sh` now detects this with a real functional test (not just `--help`) and tries to install the exact matching package automatically; if it still fails, run the command it prints (e.g. `apt install -y python3.12-venv`) on the target server yourself and retry.
- **"Port 5100 already in use"** — if it's our own agent already running there (re-adding a server, retrying a failed deploy), `install.sh` now detects that automatically and updates in place instead of requiring a manual `--uninstall` first. If it's genuinely something else on that port, SSH in and check with `sudo ss -ltnp | grep 5100`.
- **Core service seems "stuck" on restart** — check `sudo journalctl -u monitorbot-core -n 100 --no-pager` for the actual error; a shutdown deadlock that could cause this (introduced by the periodic summary report feature) has been fixed, and the service unit now also caps shutdown at 20s instead of systemd's 90s default as a safety net.
- **`rmmonitor` → "Permission denied" after an update, or "command not found" under `sudo`** — the former was a real bug (fixed: the repo's shell scripts are now correctly tracked as executable in git, so a fresh clone or update always extracts them that way); the latter usually means `/usr/local/bin` isn't in `sudo`'s `secure_path` on that particular server — `bash /opt/RM-Server-Monitor/rmserver.sh` always works regardless of PATH.

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

- **داشبورد زنده** — رابط تاریک و شیشه‌ای با TailwindCSS، چهار چارت جدا و قابل‌مخفی‌کردن (با دکمه‌ی 👁️) برای هر سرور با **Chart.js**: CPU، RAM، دیسک، شبکه — به‌روزرسانی خودکار هر ۲ تا ۳ ثانیه بدون رفرش صفحه.
- **پرمصرف‌ترین‌ها** — لیست زنده‌ی پردازش‌های پرمصرف CPU/RAM هر سرور.
- **ترافیک کل واقعی** — ایجنت خودش `vnstat` را نصب و می‌خواند، پس کل ترافیک واقعی مصرف‌شده (نه فقط سرعت لحظه‌ای) روی کارت‌ها، جزئیات سرور و گزارش‌های ربات نشان داده می‌شود.
- **ربات تلگرام** — کاملاً انگلیسی و فقط با دکمه‌های شیشه‌ای (Inline Keyboard) کار می‌کند، بدون نیاز به حفظ دستور: مرور سرورها، وضعیت و پردازش‌های زنده، افزودن سرور (دستی یا SSH خودکار)، حذف از راه دور، تنظیمات، و بکاپ/بازیابی دیتابیس. هشدار خودکار قطعی/بازگشت/عبور از آستانه (فقط روی تغییر وضعیت) به‌علاوه‌ی گزارش دوره‌ای اختیاری (میانگین CPU/RAM در بازه‌ی دلخواه).
- **استقرار خودکار SSH** — افزودن سرور فقط با آی‌پی و اطلاعات SSH از داخل داشبورد یا ربات؛ سیستم مرکزی خودش وصل می‌شود، ایجنت را نصب و ثبت می‌کند. حذف از راه دور هم با یک کلیک.
- **فاصله‌ی چک قابل‌تنظیم + بکاپ/بازیابی دیتابیس** — از پنل تنظیمات داشبورد فاصله‌ی چک را عوض کن، و دیتابیس SQLite را مستقیم از مرورگر (یا ربات) دانلود/آپلود کن.
- **نصب یک‌خطی** — با `bash <(curl -Ls .../setup.sh)` مخزن کلون می‌شود، دستور سراسری `rmmonitor` ساخته می‌شود، و مستقیم وارد منو می‌شوی.
- **`install.sh`** — نصب/حذف/به‌روزرسانی خودکفای ایجنت (به‌همراه راه‌اندازی `vnstat`)، با سرویس systemd (`monitorbot-agent`)، بررسی امن اشغال‌نبودن پورت، و به‌روزرسانی idempotent که توکن موجود را حفظ می‌کند.
- **`rmserver.sh`** — منوی رنگی و تعاملی (تم غروب لس‌آنجلس 🌅) برای نصب Core به‌عنوان سرویس systemd، مدیریت آن، ویرایش `.env`، دریافت آپدیت (و انتقال آپدیت به همه‌ی ایجنت‌های نصب‌شده با SSH)، بکاپ/بازیابی دیتابیس، یا حذف تمیز.
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
sudo rmmonitor
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

`TELEGRAM_BOT_TOKEN` (از [@BotFather](https://t.me/BotFather)) و `TELEGRAM_ADMIN_IDS` (آی‌دی عددی تلگرام خودت) را در `.env` تنظیم کن، بعد Core را ری‌استارت کن (`rmserver.sh` ← گزینه ۲ ← Restart). با `/start` شروع کن — از آنجا همه‌چیز با دکمه است، دستوری برای حفظ‌کردن نیست:

- 📋 **Servers** — وضعیت زنده، رفرش، پردازش‌های پرمصرف، افزودن سرور (توکن دستی یا استقرار خودکار SSH)، حذف از دیتابیس، یا حذف از راه دور با SSH.
- ⚙️ **Settings** — تغییر فاصله‌ی چک، و فعال‌کردن گزارش دوره‌ای (میانگین CPU/RAM هر سرور در بازه‌ی دلخواه — مثلاً هر ۱۲ ساعت).
- 💾 **Backup & Restore** — با یک دکمه فایل `monitorbot.db` را دریافت کن، یا با ارسال یک فایل `.db` آن را بازیابی کن.

### 🔄 به‌روزرسانی

```bash
sudo bash rmserver.sh
```
گزینه‌ی **۳) به‌روزرسانی سیستم** را انتخاب کن — آخرین کد را از گیت می‌گیرد، پکیج‌های پایتون را به‌روز می‌کند، Core را ری‌استارت می‌کند، و نصب‌کننده را از راه دور روی همه‌ی ایجنت‌های نصب‌شده با SSH دوباره اجرا می‌کند تا آن‌ها هم به‌روز بمانند.

منو گزینه‌های **۴) ویرایش .env**، **۵) بکاپ دیتابیس** و **۶) بازیابی دیتابیس** (لیست بکاپ‌های پوشه‌ی `backups/` و انتخاب برای بازگردانی) را هم دارد.

### 🗑 حذف

`sudo bash rmserver.sh` ← **۷) حذف کامل**. جداگانه از تو می‌پرسد که آیا دیتابیس و virtualenv هم حذف شوند، و به‌عنوان آخرین مرحله (با تایید صریح جداگانه) اینکه آیا کل نصب و دستور سراسری `rmmonitor` هم پاک شود یا نه. اگه اون مرحله‌ی آخر رو رد کنی، فایل‌های سورس دست‌نخورده باقی می‌مانند.

### 🛠 رفع اشکال خطاهای نصب/آپدیت SSH

اگه اضافه‌کردن، آپدیت یا حذفِ از راه دورِ یه سرور با SSH شکست خورد، الان هم پنل وب و هم ربات تلگرام **خروجی واقعیِ** اسکریپت نصب روی سرور هدف رو نشون می‌دن، به‌علاوه یه راه‌حل پیشنهادی اگه خطا با یکی از الگوهای شناخته‌شده مطابقت داشته باشه — دیگه لازم نیست خودت بری `journalctl` رو بگردی. چندتا از رایج‌ترین‌ها:

- **`ensurepip is not available` / ساخت venv شکست می‌خوره** — پکیج `python3-venv` روی سرور هدف ناقصه (خیلی رایج روی اوبونتوهای جدید، جایی که پکیج نسخه‌محور مثل `python3.12-venv` خودکار نصب نمی‌شه). `install.sh` الان این مورد رو با یه تست واقعی (نه فقط `--help`) تشخیص می‌ده و خودش سعی می‌کنه پکیج دقیق رو نصب کنه؛ اگه بازم نشد، همون دستوری که چاپ می‌کنه (مثلاً `apt install -y python3.12-venv`) رو دستی روی سرور هدف بزن و دوباره تلاش کن.
- **«پورت 5100 از قبل در حال استفاده است»** — اگه خودِ همین ایجنت قبلاً روی همون سرور نصب بوده (دوباره اضافه‌کردن یه سرور، یا تلاش مجدد بعد از یه دیپلوی ناموفق)، `install.sh` الان خودش این رو تشخیص می‌ده و به‌جای نیاز به `--uninstall` دستی، خودکار آپدیتش می‌کنه. اگه واقعاً یه چیز دیگه روی اون پورته، SSH بزن و چک کن: `sudo ss -ltnp | grep 5100`
- **سرویس Core موقع Restart «گیر» می‌کنه** — لاگ واقعی رو با `sudo journalctl -u monitorbot-core -n 100 --no-pager` ببین؛ یه باگ deadlock توی خاموش‌شدن (که ویژگی گزارش دوره‌ای باعثش شده بود) درست شده، و فایل سرویس هم الان حداکثر ۲۰ ثانیه صبر می‌کنه نه ۹۰ ثانیه‌ی پیش‌فرض systemd.
- **`rmmonitor` بعد از آپدیت «Permission denied» می‌ده، یا زیر `sudo` می‌گه «command not found»** — مورد اول یه باگ واقعی بود (درست شد: اسکریپت‌های شل الان توی خودِ گیت هم به‌درستی اجرایی علامت‌گذاری شدن، پس هر کلون یا آپدیتی همیشه همینطور می‌مونه)؛ مورد دوم معمولاً یعنی `/usr/local/bin` توی `secure_path` تنظیمات `sudo` همون سرور خاص نیست — `bash /opt/RM-Server-Monitor/rmserver.sh` همیشه بدون وابستگی به PATH کار می‌کنه.

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
