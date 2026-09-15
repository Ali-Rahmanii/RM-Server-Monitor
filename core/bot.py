"""
Telegram bot — fully English, inline-keyboard driven (no text commands
besides /start and /cancel). Mirrors the web dashboard: server list,
live status, top processes, add/delete/remote-uninstall, settings
(check interval + periodic summary reports), and DB backup/restore.

Runs independently of the web dashboard and scheduler, but talks to
the same database and to scheduler.py (for alerts + periodic summary
callbacks) and deployer.py (for SSH add/update/uninstall).
"""
from __future__ import annotations

import asyncio
import html
import logging
import tempfile
from pathlib import Path
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
)

from . import config, database as db, deployer, scheduler
from .collector import collect_one

logger = logging.getLogger("monitorbot.bot")

# ── conversation states ──
(ADD_M_NAME, ADD_M_IP, ADD_M_PORT, ADD_M_TOKEN, ADD_M_GROUP,
 ADD_S_NAME, ADD_S_IP, ADD_S_PORT, ADD_S_USER, ADD_S_AUTH, ADD_S_GROUP,
 CUSTOM_INTERVAL, CUSTOM_SUMMARY, RESTORE_FILE) = range(14)


# ══════════════════════════════════════════════════════════════════
#  helpers
# ══════════════════════════════════════════════════════════════════

def _is_admin(update: Update) -> bool:
    if not config.TELEGRAM_ADMIN_IDS:
        return True  # local testing only — no admin list configured
    uid = update.effective_user.id if update.effective_user else None
    return uid in config.TELEGRAM_ADMIN_IDS


async def _guard(update: Update) -> bool:
    if _is_admin(update):
        return True
    if update.callback_query:
        await update.callback_query.answer("Access denied.", show_alert=True)
    elif update.message:
        await update.message.reply_text("Access denied.")
    return False


def _fmt_bytes(v: Optional[float]) -> str:
    if v is None:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    return f"{v:.1f}{units[i]}"


def _fmt_bps(v: Optional[float]) -> str:
    return _fmt_bytes(v) + "/s" if v is not None else "-"


def _status_icon(status: str) -> str:
    return {"up": "\U0001F7E2", "down": "\U0001F534"}.get(status, "⚪")


# تلگرام هر پیام را حداکثر ۴۰۹۶ کاراکتر قبول می‌کند — جای کافی برای
# متن خطا هم می‌گذاریم
_LOG_TAIL_LIMIT = 3000


def _fmt_error_with_log(prefix: str, error: Optional[str], log: Optional[str]) -> str:
    """پیام خطا + دنباله‌ی خروجی واقعی اسکریپت SSH (اگر باشد) را برای
    ارسال در چت آماده می‌کند — دقیقاً همان چیزی که کاربر برای دیباگ
    نصب/آپدیت/حذف از راه دور لازم دارد، بدون نیاز به journalctl."""
    text = f"{prefix}: {html.escape(error or '-')}"
    log = (log or "").strip()
    if log:
        tail = log[-_LOG_TAIL_LIMIT:]
        text += f"\n\n<b>Log output:</b>\n<pre>{html.escape(tail)}</pre>"
    return text


async def _edit_or_send(update: Update, text: str, kb: Optional[InlineKeyboardMarkup] = None) -> None:
    query = update.callback_query
    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ══════════════════════════════════════════════════════════════════
#  keyboards
# ══════════════════════════════════════════════════════════════════

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001F4CB Servers", callback_data="menu:servers")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings")],
        [InlineKeyboardButton("\U0001F4BE Backup & Restore", callback_data="menu:backup")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="menu:help")],
    ])


def kb_servers() -> InlineKeyboardMarkup:
    servers = db.list_servers()
    rows = [[InlineKeyboardButton(f"{_status_icon(s['last_status'])} {s['name']}", callback_data=f"srv:view:{s['id']}")]
            for s in servers]
    rows.append([InlineKeyboardButton("➕ Add Server", callback_data="menu:add")])
    rows.append([InlineKeyboardButton("\U0001F519 Back", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def kb_server_detail(server) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("\U0001F504 Refresh", callback_data=f"srv:view:{server['id']}"),
         InlineKeyboardButton("\U0001F525 Top Processes", callback_data=f"srv:top:{server['id']}")],
        [InlineKeyboardButton("\U0001F5D1 Delete from DB", callback_data=f"srv:delconfirm:{server['id']}")],
    ]
    if server["ssh_host"] and server["ssh_username"] and (server["ssh_password"] or server["ssh_key"]):
        rows.append([InlineKeyboardButton("\U0001F9E8 Remote Uninstall (SSH)", callback_data=f"srv:uninstconfirm:{server['id']}")])
    rows.append([InlineKeyboardButton("\U0001F519 Back to Servers", callback_data="menu:servers")])
    return InlineKeyboardMarkup(rows)


def kb_confirm(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data=yes_cb),
        InlineKeyboardButton("❌ Cancel", callback_data=no_cb),
    ]])


def kb_add_server() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Manual (IP + Token)", callback_data="add:manual")],
        [InlineKeyboardButton("\U0001F680 SSH Auto-Deploy", callback_data="add:ssh")],
        [InlineKeyboardButton("\U0001F519 Cancel", callback_data="menu:servers")],
    ])


def kb_cancel_flow() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="flow:cancel")]])


def kb_settings() -> InlineKeyboardMarkup:
    interval = scheduler.get_interval_minutes()
    summary_on = scheduler.get_summary_enabled()
    summary_h = scheduler.get_summary_interval_hours()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"\U0001F550 Check Interval: {interval} min", callback_data="settings:interval")],
        [InlineKeyboardButton(f"\U0001F4CA Summary Reports: {'ON, every ' + str(summary_h).rstrip('0').rstrip('.') + 'h' if summary_on else 'OFF'}",
                               callback_data="settings:summary")],
        [InlineKeyboardButton("\U0001F519 Back", callback_data="menu:main")],
    ])


def kb_interval() -> InlineKeyboardMarkup:
    presets = [5, 10, 15, 30, 60]
    row = [InlineKeyboardButton(f"{m}m", callback_data=f"settings:interval:set:{m}") for m in presets]
    return InlineKeyboardMarkup([
        row,
        [InlineKeyboardButton("✏️ Custom", callback_data="settings:interval:custom")],
        [InlineKeyboardButton("\U0001F519 Back", callback_data="menu:settings")],
    ])


def kb_summary() -> InlineKeyboardMarkup:
    on = scheduler.get_summary_enabled()
    toggle_label = "\U0001F6D1 Turn OFF" if on else "▶️ Turn ON"
    presets = [6, 12, 24, 48]
    row = [InlineKeyboardButton(f"{h}h", callback_data=f"settings:summary:set:{h}") for h in presets]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data="settings:summary:toggle")],
        row,
        [InlineKeyboardButton("✏️ Custom", callback_data="settings:summary:custom")],
        [InlineKeyboardButton("\U0001F519 Back", callback_data="menu:settings")],
    ])


def kb_backup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001F4BE Backup Now", callback_data="backup:now")],
        [InlineKeyboardButton("♻️ Restore from file", callback_data="backup:restore")],
        [InlineKeyboardButton("\U0001F519 Back", callback_data="menu:main")],
    ])


# ══════════════════════════════════════════════════════════════════
#  text builders
# ══════════════════════════════════════════════════════════════════

def _server_detail_text(server, latest) -> str:
    name = html.escape(server["name"])
    lines = [f"{_status_icon(server['last_status'])} <b>{name}</b>", f"<code>{html.escape(server['ip'])}:{server['port']}</code>"]
    if server["group_name"]:
        lines.append(f"Group: {html.escape(server['group_name'])}")
    if not latest:
        lines.append("\nNo data yet.")
        return "\n".join(lines)
    if latest["status"] != "up":
        lines.append(f"\n\U0001F534 DOWN — {html.escape(latest['error'] or '-')}" )
        return "\n".join(lines)
    lines.append("")
    if latest["ping_ms"] is not None:
        lines.append(f"Ping: {latest['ping_ms']:.0f}ms")
    if latest["cpu_percent"] is not None:
        lines.append(f"CPU: {latest['cpu_percent']:.0f}%")
    if latest["ram_percent"] is not None:
        lines.append(f"RAM: {latest['ram_percent']:.0f}%")
    if latest["disk_percent"] is not None:
        lines.append(f"Disk: {latest['disk_percent']:.0f}%")
    lines.append(f"Network: ⬆{_fmt_bps(latest['net_sent_bps'])} ⬇{_fmt_bps(latest['net_recv_bps'])}")
    if latest["traffic_rx_bytes"] is not None:
        iface = latest["traffic_iface"] or "?"
        lines.append(f"Total traffic ({iface}): ⬆{_fmt_bytes(latest['traffic_tx_bytes'])} ⬇{_fmt_bytes(latest['traffic_rx_bytes'])}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
#  entry commands
# ══════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    await _edit_or_send(update, "\U0001F5A5 <b>RM Server Monitor</b>\n\nChoose an option:", kb_main())


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Cancelled.", reply_markup=None)
    await _edit_or_send(update, "\U0001F5A5 <b>RM Server Monitor</b>\n\nChoose an option:", kb_main())
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════
#  main callback router (non-conversation buttons)
# ══════════════════════════════════════════════════════════════════

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not await _guard(update):
        return
    await query.answer()
    data = query.data

    if data == "menu:main":
        await _edit_or_send(update, "\U0001F5A5 <b>RM Server Monitor</b>\n\nChoose an option:", kb_main())

    elif data == "menu:servers":
        await _edit_or_send(update, "\U0001F4CB <b>Servers</b>", kb_servers())

    elif data == "menu:add":
        await _edit_or_send(update, "How do you want to add the server?", kb_add_server())

    elif data == "menu:help":
        text = (
            "ℹ️ <b>Help</b>\n\n"
            "\U0001F4CB Servers — view live status, top processes, add/remove agents\n"
            "⚙️ Settings — check interval + periodic summary reports\n"
            "\U0001F4BE Backup & Restore — download or upload the database\n\n"
            "Use /start anytime to reopen this menu."
        )
        await _edit_or_send(update, text, InlineKeyboardMarkup([[InlineKeyboardButton("\U0001F519 Back", callback_data="menu:main")]]))

    elif data == "menu:settings":
        await _edit_or_send(update, "⚙️ <b>Settings</b>", kb_settings())

    elif data == "menu:backup":
        await _edit_or_send(update, "\U0001F4BE <b>Backup & Restore</b>", kb_backup())

    elif data.startswith("srv:view:"):
        server_id = int(data.split(":")[2])
        server = db.get_server(server_id)
        if not server:
            await query.answer("Server not found.", show_alert=True)
            return
        latest = db.get_latest_log(server_id)
        await _edit_or_send(update, _server_detail_text(server, latest), kb_server_detail(server))

    elif data.startswith("srv:top:"):
        server_id = int(data.split(":")[2])
        server = db.get_server(server_id)
        if not server:
            await query.answer("Server not found.", show_alert=True)
            return
        await query.edit_message_text("⏳ Fetching live data...")
        result = await collect_one(server)
        if not result["ok"]:
            await _edit_or_send(update, f"\U0001F534 Unreachable: {html.escape(result.get('error') or '-')}", kb_server_detail(server))
            return
        procs = (result["raw"] or {}).get("processes", {})
        lines = [f"\U0001F525 <b>{html.escape(server['name'])}</b> — Top Processes", "\n<b>CPU:</b>"]
        for p in procs.get("top_cpu", []):
            lines.append(f"  {html.escape(str(p.get('name')))} — {p.get('cpu_percent', 0):.1f}% (pid {p.get('pid')})")
        lines.append("\n<b>RAM:</b>")
        for p in procs.get("top_ram", []):
            lines.append(f"  {html.escape(str(p.get('name')))} — {p.get('ram_percent', 0):.1f}% (pid {p.get('pid')})")
        await _edit_or_send(update, "\n".join(lines), kb_server_detail(server))

    elif data.startswith("srv:delconfirm:"):
        server_id = int(data.split(":")[2])
        await _edit_or_send(update, "Delete this server from the database?\n(The agent itself is left untouched on the target machine.)",
                             kb_confirm(f"srv:del:{server_id}", f"srv:view:{server_id}"))

    elif data.startswith("srv:del:"):
        server_id = int(data.split(":")[2])
        db.delete_server(server_id)
        await _edit_or_send(update, "\U0001F5D1 Server deleted.", kb_servers())

    elif data.startswith("srv:uninstconfirm:"):
        server_id = int(data.split(":")[2])
        await _edit_or_send(update, "This will SSH into the server and completely remove the agent. Continue?",
                             kb_confirm(f"srv:uninst:{server_id}", f"srv:view:{server_id}"))

    elif data.startswith("srv:uninst:"):
        server_id = int(data.split(":")[2])
        server = db.get_server(server_id)
        if not server:
            await query.answer("Server not found.", show_alert=True)
            return
        await query.edit_message_text("⏳ Connecting via SSH and uninstalling...")
        result = await _run_uninstall(server)
        if result["ok"]:
            db.delete_server(server_id)
            await _edit_or_send(update, "\U0001F9E8 Agent uninstalled and server removed.", kb_servers())
        else:
            await _edit_or_send(update, _fmt_error_with_log("❌ Uninstall failed", result["error"], result.get("log")), kb_server_detail(server))

    elif data == "settings:interval":
        await _edit_or_send(update, f"Current interval: <b>{scheduler.get_interval_minutes()} min</b>\nPick a new one:", kb_interval())

    elif data.startswith("settings:interval:set:"):
        minutes = int(data.split(":")[3])
        scheduler.set_interval_minutes(minutes)
        await _edit_or_send(update, f"✅ Check interval set to {minutes} min.", kb_settings())

    elif data == "settings:summary":
        await _edit_or_send(update, "\U0001F4CA <b>Periodic Summary Reports</b>\n\nSends average CPU/RAM per server over the chosen period.", kb_summary())

    elif data == "settings:summary:toggle":
        scheduler.set_summary_enabled(not scheduler.get_summary_enabled())
        await _edit_or_send(update, "⚙️ <b>Settings</b>", kb_settings())

    elif data.startswith("settings:summary:set:"):
        hours = float(data.split(":")[3])
        scheduler.set_summary_interval_hours(hours)
        scheduler.set_summary_enabled(True)
        await _edit_or_send(update, f"✅ Summary reports enabled, every {hours:g}h.", kb_settings())

    elif data == "backup:now":
        await query.edit_message_text("⏳ Preparing backup...")
        db_path = Path(config.DB_PATH)
        if not db_path.exists():
            await _edit_or_send(update, "❌ Database file not found.", kb_backup())
            return
        db.checkpoint_wal()  # otherwise the raw file copy can be an incomplete WAL snapshot
        await query.message.reply_document(document=open(db_path, "rb"), filename=f"monitorbot-backup-{db_path.stat().st_mtime_ns}.db")
        await _edit_or_send(update, "\U0001F4BE <b>Backup & Restore</b>", kb_backup())

    elif data == "flow:cancel":
        context.user_data.clear()
        await _edit_or_send(update, "Cancelled.", kb_main())


async def _run_uninstall(server) -> dict:
    return await asyncio.to_thread(
        deployer.uninstall_agent_via_ssh,
        server["ssh_host"], server["ssh_port"] or 22, server["ssh_username"],
        server["ssh_password"], server["ssh_key"],
    )


# ══════════════════════════════════════════════════════════════════
#  conversation: add server (manual)
# ══════════════════════════════════════════════════════════════════

async def add_manual_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _guard(update):
        return ConversationHandler.END
    context.user_data.clear()
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Send the <b>server name</b>:", parse_mode=ParseMode.HTML, reply_markup=kb_cancel_flow())
    return ADD_M_NAME


async def add_manual_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Send the <b>IP address</b>:", parse_mode=ParseMode.HTML, reply_markup=kb_cancel_flow())
    return ADD_M_IP


async def add_manual_ip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["ip"] = update.message.text.strip()
    await update.message.reply_text("Send the <b>agent port</b> (default 5100):", parse_mode=ParseMode.HTML, reply_markup=kb_cancel_flow())
    return ADD_M_PORT


async def add_manual_port(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["port"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please send a valid port number:", reply_markup=kb_cancel_flow())
        return ADD_M_PORT
    await update.message.reply_text("Send the <b>agent token</b>:", parse_mode=ParseMode.HTML, reply_markup=kb_cancel_flow())
    return ADD_M_TOKEN


async def add_manual_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["token"] = update.message.text.strip()
    await update.message.reply_text("Send a <b>group name</b> (or send - to skip):", parse_mode=ParseMode.HTML, reply_markup=kb_cancel_flow())
    return ADD_M_GROUP


async def add_manual_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group = update.message.text.strip()
    group = "" if group == "-" else group
    d = context.user_data
    try:
        db.add_server(d["name"], d["ip"], d["token"], port=d["port"], group_name=group)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {html.escape(str(e))}", parse_mode=ParseMode.HTML)
        context.user_data.clear()
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text(f"✅ Server <b>{html.escape(d['name'])}</b> added.", parse_mode=ParseMode.HTML)
    await update.message.reply_text("\U0001F4CB <b>Servers</b>", parse_mode=ParseMode.HTML, reply_markup=kb_servers())
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════
#  conversation: add server (SSH auto-deploy)
# ══════════════════════════════════════════════════════════════════

async def add_ssh_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _guard(update):
        return ConversationHandler.END
    context.user_data.clear()
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Send the <b>server name</b>:", parse_mode=ParseMode.HTML, reply_markup=kb_cancel_flow())
    return ADD_S_NAME


async def add_ssh_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Send the <b>IP address</b>:", parse_mode=ParseMode.HTML, reply_markup=kb_cancel_flow())
    return ADD_S_IP


async def add_ssh_ip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["ip"] = update.message.text.strip()
    await update.message.reply_text("Send the <b>SSH port</b> (default 22):", parse_mode=ParseMode.HTML, reply_markup=kb_cancel_flow())
    return ADD_S_PORT


async def add_ssh_port(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["ssh_port"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please send a valid port number:", reply_markup=kb_cancel_flow())
        return ADD_S_PORT
    await update.message.reply_text("Send the <b>SSH username</b> (e.g. root):", parse_mode=ParseMode.HTML, reply_markup=kb_cancel_flow())
    return ADD_S_USER


async def add_ssh_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["ssh_username"] = update.message.text.strip()
    await update.message.reply_text(
        "Send the <b>SSH password</b>, or send your <b>private key</b> (paste full PEM text):",
        parse_mode=ParseMode.HTML, reply_markup=kb_cancel_flow(),
    )
    return ADD_S_AUTH


async def add_ssh_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.upper().startswith("-----BEGIN"):
        context.user_data["ssh_private_key"] = text
        context.user_data["ssh_password"] = None
    else:
        context.user_data["ssh_password"] = text
        context.user_data["ssh_private_key"] = None
    await update.message.reply_text("Send a <b>group name</b> (or send - to skip):", parse_mode=ParseMode.HTML, reply_markup=kb_cancel_flow())
    return ADD_S_GROUP


async def add_ssh_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group = update.message.text.strip()
    group = "" if group == "-" else group
    d = context.user_data

    if db.get_server_by_name(d["name"]):
        await update.message.reply_text(f"❌ A server named «{html.escape(d['name'])}» already exists.")
        context.user_data.clear()
        return ConversationHandler.END

    msg = await update.message.reply_text("⏳ Connecting via SSH and installing the agent — this can take a few minutes...")
    result = await asyncio.to_thread(
        deployer.deploy_agent_via_ssh,
        d["ip"], d["ssh_port"], d["ssh_username"], d.get("ssh_password"), d.get("ssh_private_key"),
    )
    if not result["ok"]:
        await msg.edit_text(_fmt_error_with_log("❌ Install failed", result["error"], result.get("log")), parse_mode=ParseMode.HTML)
        context.user_data.clear()
        return ConversationHandler.END

    db.add_server(
        d["name"], d["ip"], result["token"], port=result["agent_port"] or config.AGENT_DEFAULT_PORT,
        group_name=group, ssh_host=d["ip"], ssh_port=d["ssh_port"], ssh_username=d["ssh_username"],
        ssh_password=d.get("ssh_password"), ssh_key=d.get("ssh_private_key"), installed_via="ssh-auto-deploy",
    )
    context.user_data.clear()
    await msg.edit_text(f"✅ Server <b>{html.escape(d['name'])}</b> installed and registered.", parse_mode=ParseMode.HTML)
    await update.message.reply_text("\U0001F4CB <b>Servers</b>", parse_mode=ParseMode.HTML, reply_markup=kb_servers())
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════
#  conversation: custom interval / custom summary hours
# ══════════════════════════════════════════════════════════════════

async def custom_interval_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _guard(update):
        return ConversationHandler.END
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Send the check interval in minutes:", reply_markup=kb_cancel_flow())
    return CUSTOM_INTERVAL


async def custom_interval_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        minutes = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please send a valid number of minutes:", reply_markup=kb_cancel_flow())
        return CUSTOM_INTERVAL
    scheduler.set_interval_minutes(minutes)
    await update.message.reply_text(f"✅ Check interval set to {minutes} min.")
    await update.message.reply_text("⚙️ <b>Settings</b>", parse_mode=ParseMode.HTML, reply_markup=kb_settings())
    return ConversationHandler.END


async def custom_summary_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _guard(update):
        return ConversationHandler.END
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Send the summary report interval in hours (e.g. 12):", reply_markup=kb_cancel_flow())
    return CUSTOM_SUMMARY


async def custom_summary_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        hours = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please send a valid number of hours:", reply_markup=kb_cancel_flow())
        return CUSTOM_SUMMARY
    scheduler.set_summary_interval_hours(hours)
    scheduler.set_summary_enabled(True)
    await update.message.reply_text(f"✅ Summary reports enabled, every {hours:g}h.")
    await update.message.reply_text("⚙️ <b>Settings</b>", parse_mode=ParseMode.HTML, reply_markup=kb_settings())
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════
#  conversation: restore DB from an uploaded file
# ══════════════════════════════════════════════════════════════════

async def restore_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _guard(update):
        return ConversationHandler.END
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "Send me the <code>.db</code> file to restore as a document.", parse_mode=ParseMode.HTML, reply_markup=kb_cancel_flow(),
    )
    return RESTORE_FILE


async def restore_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    doc = update.message.document
    if not doc:
        await update.message.reply_text("Please send the .db file as a document, or Cancel.", reply_markup=kb_cancel_flow())
        return RESTORE_FILE

    msg = await update.message.reply_text("⏳ Downloading and validating...")
    tg_file = await context.bot.get_file(doc.file_id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        tmp_path = Path(tmp.name)
    await tg_file.download_to_drive(str(tmp_path))

    if not db.validate_backup_file(tmp_path):
        tmp_path.unlink(missing_ok=True)
        await msg.edit_text("❌ This is not a valid Monitorbot database file.")
        return ConversationHandler.END

    db.restore_from_backup(tmp_path)
    await msg.edit_text("✅ Database restored successfully.")
    await update.message.reply_text("\U0001F5A5 <b>RM Server Monitor</b>", parse_mode=ParseMode.HTML, reply_markup=kb_main())
    return ConversationHandler.END


async def flow_cancel_in_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Cancelled.")
    await context.bot.send_message(update.effective_chat.id, "\U0001F5A5 <b>RM Server Monitor</b>", parse_mode=ParseMode.HTML, reply_markup=kb_main())
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════
#  wiring
# ══════════════════════════════════════════════════════════════════

def build_bot_application() -> Optional[Application]:
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN is not set — the Telegram bot stays disabled.")
        return None

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    cancel_fallback = CallbackQueryHandler(flow_cancel_in_conversation, pattern="^flow:cancel$")

    add_manual_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_manual_start, pattern="^add:manual$")],
        states={
            ADD_M_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_manual_name)],
            ADD_M_IP: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_manual_ip)],
            ADD_M_PORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_manual_port)],
            ADD_M_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_manual_token)],
            ADD_M_GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_manual_group)],
        },
        fallbacks=[cancel_fallback, CommandHandler("cancel", cmd_cancel)],
        per_message=False,
    )

    add_ssh_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_ssh_start, pattern="^add:ssh$")],
        states={
            ADD_S_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_ssh_name)],
            ADD_S_IP: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_ssh_ip)],
            ADD_S_PORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_ssh_port)],
            ADD_S_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_ssh_user)],
            ADD_S_AUTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_ssh_auth)],
            ADD_S_GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_ssh_group)],
        },
        fallbacks=[cancel_fallback, CommandHandler("cancel", cmd_cancel)],
        per_message=False,
    )

    interval_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(custom_interval_start, pattern="^settings:interval:custom$")],
        states={CUSTOM_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_interval_set)]},
        fallbacks=[cancel_fallback, CommandHandler("cancel", cmd_cancel)],
        per_message=False,
    )

    summary_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(custom_summary_start, pattern="^settings:summary:custom$")],
        states={CUSTOM_SUMMARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_summary_set)]},
        fallbacks=[cancel_fallback, CommandHandler("cancel", cmd_cancel)],
        per_message=False,
    )

    restore_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(restore_start, pattern="^backup:restore$")],
        states={RESTORE_FILE: [MessageHandler(filters.Document.ALL, restore_receive)]},
        fallbacks=[cancel_fallback, CommandHandler("cancel", cmd_cancel)],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_start))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(add_manual_conv)
    app.add_handler(add_ssh_conv)
    app.add_handler(interval_conv)
    app.add_handler(summary_conv)
    app.add_handler(restore_conv)
    app.add_handler(CallbackQueryHandler(on_callback))

    async def _alert_callback(server_row, kind, message):
        if not config.TELEGRAM_ADMIN_IDS:
            return
        icon = {"down": "\U0001F534", "recovered": "\U0001F7E2", "threshold": "⚠️"}.get(kind, "ℹ️")
        text = f"{icon} {html.escape(message)}"
        for admin_id in config.TELEGRAM_ADMIN_IDS:
            try:
                await app.bot.send_message(chat_id=admin_id, text=text, parse_mode=ParseMode.HTML)
            except Exception:
                logger.exception("Failed to send alert to admin %s", admin_id)

    async def _summary_callback(text: str):
        if not config.TELEGRAM_ADMIN_IDS:
            return
        for admin_id in config.TELEGRAM_ADMIN_IDS:
            try:
                await app.bot.send_message(chat_id=admin_id, text=f"<pre>{html.escape(text)}</pre>", parse_mode=ParseMode.HTML)
            except Exception:
                logger.exception("Failed to send summary report to admin %s", admin_id)

    scheduler.set_alert_callback(_alert_callback)
    scheduler.set_summary_callback(_summary_callback)
    return app
