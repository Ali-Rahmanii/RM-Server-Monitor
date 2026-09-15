"""
ربات تلگرام مانیتورینگ — مستقل از وب و زمان‌بند اجرا می‌شود اما با
هر دو در ارتباط است: زمان‌بند از طریق set_alert_callback هشدار
می‌فرستد، و دستورات ربات مستقیماً از database.py می‌خوانند/می‌نویسند.
"""
from __future__ import annotations

import html
import logging
import secrets as secrets_mod
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
)

from . import config, database as db, scheduler
from .collector import collect_one

logger = logging.getLogger("monitorbot.bot")


def _is_admin(update: Update) -> bool:
    if not config.TELEGRAM_ADMIN_IDS:
        return True  # اگر ادمینی تنظیم نشده، محدودیتی اعمال نمی‌شود (فقط برای تست محلی)
    uid = update.effective_user.id if update.effective_user else None
    return uid in config.TELEGRAM_ADMIN_IDS


async def _guard(update: Update) -> bool:
    if not _is_admin(update):
        await update.message.reply_text("⛔ دسترسی نداری.")
        return False
    return True


def _fmt_status_icon(status: str) -> str:
    return {"up": "🟢", "down": "🔴"}.get(status, "⚪")


def _fmt_bps(value: Optional[float]) -> str:
    if value is None:
        return "-"
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if value < 1024:
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TB/s"


# ══════════════════════════════════════════════════════════════════
#  دستورات
# ══════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    text = (
        "🖥 <b>ربات مانیتورینگ سرورها</b>\n\n"
        "/servers — لیست سرورهای ثبت‌شده\n"
        "/status &lt;نام&gt; — وضعیت لحظه‌ای یک سرور\n"
        "/statusall — وضعیت خلاصه‌ی همه‌ی سرورها\n"
        "/top &lt;نام&gt; — پرمصرف‌ترین پردازش‌ها\n"
        "/addserver &lt;نام&gt; &lt;آی‌پی&gt; &lt;توکن&gt; [پورت] — افزودن سرور\n"
        "/delserver &lt;نام&gt; — حذف سرور\n"
        "/setinterval &lt;دقیقه&gt; — تغییر فاصله‌ی چک خودکار\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_servers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    servers = db.list_servers()
    if not servers:
        await update.message.reply_text("هیچ سروری ثبت نشده. با /addserver اضافه کن.")
        return
    lines = ["📋 <b>سرورها</b>"]
    for s in servers:
        icon = _fmt_status_icon(s["last_status"])
        en = "" if s["enabled"] else " (غیرفعال)"
        lines.append(f"{icon} <b>{html.escape(s['name'])}</b> — <code>{html.escape(s['ip'])}</code>{en}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_statusall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    servers = db.list_servers(enabled_only=True)
    if not servers:
        await update.message.reply_text("هیچ سروری ثبت نشده.")
        return
    msg = await update.message.reply_text("⏳ در حال چک کردن همه‌ی سرورها...")
    lines = ["📊 <b>وضعیت لحظه‌ای</b>"]
    for s in servers:
        result = await collect_one(s)
        icon = "🟢" if result["ok"] else "🔴"
        if result["ok"]:
            cpu = result.get("cpu_percent")
            ram = result.get("ram_percent")
            ping = result.get("ping_ms")
            extra = f"CPU {cpu:.0f}% RAM {ram:.0f}%" if cpu is not None and ram is not None else ""
            ping_txt = f" ({ping:.0f}ms)" if ping is not None else ""
            lines.append(f"{icon} <b>{html.escape(s['name'])}</b>{ping_txt} — {extra}")
        else:
            lines.append(f"{icon} <b>{html.escape(s['name'])}</b> — {html.escape(result.get('error') or 'قطع')}")
        db.set_server_status(s["id"], "up" if result["ok"] else "down", result["timestamp"])
        db.insert_log(
            s["id"], result["timestamp"], "up" if result["ok"] else "down",
            ping_ms=result.get("ping_ms"), cpu_percent=result.get("cpu_percent"),
            ram_percent=result.get("ram_percent"), disk_percent=result.get("disk_percent"),
            net_sent_bps=result.get("net_sent_bps"), net_recv_bps=result.get("net_recv_bps"),
            error=result.get("error"),
        )
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("استفاده: /status نام_سرور")
        return
    name = " ".join(context.args)
    server = db.get_server_by_name(name)
    if not server:
        await update.message.reply_text(f"سروری با نام «{html.escape(name)}» پیدا نشد.")
        return
    result = await collect_one(server)
    db.set_server_status(server["id"], "up" if result["ok"] else "down", result["timestamp"])
    db.insert_log(
        server["id"], result["timestamp"], "up" if result["ok"] else "down",
        ping_ms=result.get("ping_ms"), cpu_percent=result.get("cpu_percent"),
        ram_percent=result.get("ram_percent"), disk_percent=result.get("disk_percent"),
        net_sent_bps=result.get("net_sent_bps"), net_recv_bps=result.get("net_recv_bps"),
        error=result.get("error"),
    )
    if not result["ok"]:
        await update.message.reply_text(
            f"🔴 <b>{html.escape(server['name'])}</b>\nخطا: {html.escape(result.get('error') or '-')}",
            parse_mode=ParseMode.HTML,
        )
        return
    raw = result["raw"]
    cpu = raw.get("cpu", {})
    mem = raw.get("memory", {})
    net = raw.get("network", {})
    ping = result.get("ping_ms")
    lines = [
        f"🟢 <b>{html.escape(server['name'])}</b> — <code>{html.escape(server['ip'])}</code>",
        f"پینگ: {ping:.0f}ms" if ping is not None else "پینگ: -",
        f"CPU: {cpu.get('percent', '-')}%  ({cpu.get('core_count', '?')} هسته)",
        f"RAM: {mem.get('percent', '-')}%  ({mem.get('used_gb', '?')}/{mem.get('total_gb', '?')} GB)",
        f"شبکه: ⬆{_fmt_bps(net.get('sent_bytes_per_sec'))}  ⬇{_fmt_bps(net.get('recv_bytes_per_sec'))}",
    ]
    disks = raw.get("disks", [])
    for d in disks:
        lines.append(f"دیسک {d.get('mountpoint', '?')}: {d.get('percent', '-')}%")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("استفاده: /top نام_سرور")
        return
    name = " ".join(context.args)
    server = db.get_server_by_name(name)
    if not server:
        await update.message.reply_text(f"سروری با نام «{html.escape(name)}» پیدا نشد.")
        return
    result = await collect_one(server)
    if not result["ok"]:
        await update.message.reply_text(f"🔴 در دسترس نیست: {html.escape(result.get('error') or '-')}")
        return
    raw = result["raw"]
    procs = raw.get("processes", {})
    lines = [f"⚙️ <b>{html.escape(server['name'])}</b> — پرمصرف‌ترین‌ها"]
    lines.append("\n<b>CPU:</b>")
    for p in procs.get("top_cpu", []):
        lines.append(f"  {html.escape(str(p.get('name')))} — {p.get('cpu_percent', 0):.1f}% (pid {p.get('pid')})")
    lines.append("\n<b>RAM:</b>")
    for p in procs.get("top_ram", []):
        lines.append(f"  {html.escape(str(p.get('name')))} — {p.get('ram_percent', 0):.1f}% (pid {p.get('pid')})")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_addserver(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "استفاده: /addserver نام آی‌پی توکن [پورت=5100]"
        )
        return
    name, ip, token = args[0], args[1], args[2]
    port = 5100
    if len(args) >= 4:
        try:
            port = int(args[3])
        except ValueError:
            await update.message.reply_text("پورت باید عدد باشد.")
            return
    try:
        db.add_server(name, ip, token, port=port)
    except Exception as e:
        await update.message.reply_text(f"خطا: {html.escape(str(e))}")
        return
    await update.message.reply_text(f"✅ سرور «{html.escape(name)}» اضافه شد.")


async def cmd_delserver(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("استفاده: /delserver نام")
        return
    name = " ".join(context.args)
    if db.delete_server_by_name(name):
        await update.message.reply_text(f"🗑 سرور «{html.escape(name)}» حذف شد.")
    else:
        await update.message.reply_text("سروری با این نام پیدا نشد.")


async def cmd_setinterval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    if not context.args or not context.args[0].isdigit():
        current = scheduler.get_interval_minutes()
        await update.message.reply_text(f"فاصله‌ی فعلی: {current} دقیقه.\nاستفاده: /setinterval دقیقه")
        return
    minutes = scheduler.set_interval_minutes(int(context.args[0]))
    await update.message.reply_text(f"✅ فاصله‌ی چک خودکار روی {minutes} دقیقه تنظیم شد.")


# ══════════════════════════════════════════════════════════════════
#  هشدار خودکار (از scheduler.py صدا زده می‌شود)
# ══════════════════════════════════════════════════════════════════

def build_bot_application() -> Optional[Application]:
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN تنظیم نشده — ربات تلگرام غیرفعال می‌ماند.")
        return None

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("servers", cmd_servers))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("statusall", cmd_statusall))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("addserver", cmd_addserver))
    app.add_handler(CommandHandler("delserver", cmd_delserver))
    app.add_handler(CommandHandler("setinterval", cmd_setinterval))

    async def _alert_callback(server_row, kind, message):
        if not config.TELEGRAM_ADMIN_IDS:
            return
        icon = {"down": "🔴", "recovered": "🟢", "threshold": "⚠️"}.get(kind, "ℹ️")
        text = f"{icon} {html.escape(message)}"
        for admin_id in config.TELEGRAM_ADMIN_IDS:
            try:
                await app.bot.send_message(chat_id=admin_id, text=text, parse_mode=ParseMode.HTML)
            except Exception:
                logger.exception("ارسال هشدار به ادمین %s ناموفق بود", admin_id)

    scheduler.set_alert_callback(_alert_callback)
    return app
