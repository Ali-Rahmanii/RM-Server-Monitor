"""
زمان‌بند پس‌زمینه — چرخه‌ای زنجیره‌ای (chain-based) که هر بار خودش را
N دقیقه بعد از پایان اجرای قبلی دوباره برنامه‌ریزی می‌کند (نه با
تایمر ثابت)، تا اگر یک دور طول کشید، فشار اضافه روی سرورها نیاید.

هشدار فقط روی «تغییر وضعیت» ارسال می‌شود (down/recovered و عبور از
آستانه‌ی منابع) — نه در هر چرخه — تا اسپم نشود.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from . import config, database as db
from .collector import collect_one

logger = logging.getLogger("monitorbot.scheduler")

_SCAN_LOCK = asyncio.Lock()
_stop_event: Optional[asyncio.Event] = None
_summary_stop_event: Optional[asyncio.Event] = None
_alert_callback = None  # از bot.py ست می‌شود، اختیاری
_summary_callback = None  # از bot.py ست می‌شود، اختیاری


def set_alert_callback(callback) -> None:
    """callback(server_row, kind, message) -> awaitable، برای ارسال هشدار تلگرام."""
    global _alert_callback
    _alert_callback = callback


def set_summary_callback(callback) -> None:
    """callback(text: str) -> awaitable، برای ارسال گزارش دوره‌ای از راه ربات تلگرام."""
    global _summary_callback
    _summary_callback = callback


def get_summary_enabled() -> bool:
    return db.get_setting("summary_enabled") == "1"


def set_summary_enabled(enabled: bool) -> None:
    db.set_setting("summary_enabled", "1" if enabled else "0")


def get_summary_interval_hours() -> float:
    raw = db.get_setting("summary_interval_hours")
    if raw is not None:
        try:
            val = float(raw)
            if val > 0:
                return val
        except ValueError:
            pass
    return config.DEFAULT_SUMMARY_INTERVAL_HOURS


def set_summary_interval_hours(hours: float) -> float:
    hours = max(0.5, float(hours))
    db.set_setting("summary_interval_hours", str(hours))
    return hours


def get_interval_minutes() -> int:
    raw = db.get_setting("interval_minutes")
    if raw is not None:
        try:
            val = int(raw)
            if val >= config.MIN_INTERVAL_MINUTES:
                return val
        except ValueError:
            pass
    return config.DEFAULT_INTERVAL_MINUTES


def set_interval_minutes(minutes: int) -> int:
    minutes = max(config.MIN_INTERVAL_MINUTES, int(minutes))
    db.set_setting("interval_minutes", str(minutes))
    return minutes


async def _maybe_alert(server_row, previous_status: str, result: dict) -> None:
    if _alert_callback is None:
        return
    new_status = "up" if result["ok"] else "down"
    try:
        if previous_status != "down" and new_status == "down":
            await _alert_callback(
                server_row, "down",
                f"سرور «{server_row['name']}» ({server_row['ip']}) از دسترس خارج شد.\nخطا: {result.get('error') or '-'}"
            )
        elif previous_status == "down" and new_status == "up":
            await _alert_callback(
                server_row, "recovered",
                f"سرور «{server_row['name']}» ({server_row['ip']}) دوباره برگشت."
            )
        elif result["ok"]:
            alerts = []
            cpu, ram, disk = result.get("cpu_percent"), result.get("ram_percent"), result.get("disk_percent")
            if cpu is not None and cpu >= config.CPU_ALERT_THRESHOLD:
                alerts.append(f"CPU: {cpu:.0f}%")
            if ram is not None and ram >= config.RAM_ALERT_THRESHOLD:
                alerts.append(f"RAM: {ram:.0f}%")
            if disk is not None and disk >= config.DISK_ALERT_THRESHOLD:
                alerts.append(f"دیسک: {disk:.0f}%")
            if alerts:
                await _alert_callback(
                    server_row, "threshold",
                    f"مصرف بالا در «{server_row['name']}» ({server_row['ip']}):\n" + "، ".join(alerts)
                )
    except Exception:
        logger.exception("خطا در ارسال هشدار برای سرور %s", server_row["name"])


async def run_scan_once() -> dict:
    """
    یک دور کامل روی همه‌ی سرورهای فعال. برگرداندن خلاصه‌ی نتیجه.
    قفل‌شده تا یک اجرای دستی (/status) و چرخه‌ی خودکار هم‌زمان
    مزاحم هم نشوند.
    """
    async with _SCAN_LOCK:
        started = time.monotonic()
        servers = db.list_servers(enabled_only=True)
        ok_count = 0
        down_count = 0
        for server_row in servers:
            previous_status = server_row["last_status"]
            try:
                result = await collect_one(server_row)
            except Exception as e:
                logger.exception("خطای غیرمنتظره هنگام چک سرور %s", server_row["name"])
                result = {"ok": False, "error": str(e), "ping_ms": None,
                           "cpu_percent": None, "ram_percent": None, "disk_percent": None,
                           "net_sent_bps": None, "net_recv_bps": None, "raw": None,
                           "timestamp": time.time()}

            new_status = "up" if result["ok"] else "down"
            if result["ok"]:
                ok_count += 1
            else:
                down_count += 1

            db.set_server_status(server_row["id"], new_status, result["timestamp"])
            db.insert_log(
                server_row["id"], result["timestamp"], new_status,
                ping_ms=result.get("ping_ms"), cpu_percent=result.get("cpu_percent"),
                ram_percent=result.get("ram_percent"), disk_percent=result.get("disk_percent"),
                net_sent_bps=result.get("net_sent_bps"), net_recv_bps=result.get("net_recv_bps"),
                error=result.get("error"),
                raw_json=_safe_json(result.get("raw")),
                traffic_rx_bytes=result.get("traffic_rx_bytes"), traffic_tx_bytes=result.get("traffic_tx_bytes"),
                traffic_iface=result.get("traffic_iface"),
            )
            await _maybe_alert(server_row, previous_status, result)

        elapsed = time.monotonic() - started
        logger.info("دور چک تمام شد: %d آنلاین / %d آفلاین از %d سرور، %.1f ثانیه",
                     ok_count, down_count, len(servers), elapsed)
        return {"total": len(servers), "ok": ok_count, "down": down_count, "elapsed": elapsed}


def _safe_json(obj) -> Optional[str]:
    if obj is None:
        return None
    import json
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return None


async def scheduler_loop() -> None:
    """
    حلقه‌ی اصلی: چک می‌کند، صبر می‌کند به اندازه‌ی interval فعلی
    (که هر بار می‌تواند تغییر کرده باشد)، و دوباره. زنجیره‌ای —
    شمارش فاصله از پایان دور قبلی شروع می‌شود نه از شروعش.
    """
    global _stop_event
    _stop_event = asyncio.Event()
    logger.info("زمان‌بند شروع به کار کرد.")
    while not _stop_event.is_set():
        try:
            await run_scan_once()
        except Exception:
            logger.exception("خطای غیرمنتظره در چرخه‌ی زمان‌بند")

        interval_seconds = get_interval_minutes() * 60
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass  # زمان تمام شد، دور بعدی شروع می‌شود


def stop_scheduler() -> None:
    if _stop_event is not None:
        _stop_event.set()


def build_summary_report(period_hours: float) -> str:
    """گزارش خلاصه‌ی میانگین CPU/RAM برای همه‌ی سرورها در N ساعت اخیر (متن ساده)."""
    since_ts = time.time() - period_hours * 3600
    servers = db.list_servers()
    lines = [f"Periodic Summary Report — last {period_hours:g}h"]
    if not servers:
        lines.append("No servers registered.")
        return "\n".join(lines)
    for s in servers:
        avg = db.get_avg_metrics(s["id"], since_ts)
        if not avg or not avg["sample_count"]:
            lines.append(f"- {s['name']}: no data in this period")
            continue
        cpu_txt = f"{avg['avg_cpu']:.1f}%" if avg["avg_cpu"] is not None else "-"
        ram_txt = f"{avg['avg_ram']:.1f}%" if avg["avg_ram"] is not None else "-"
        down = avg["down_count"] or 0
        samples = avg["sample_count"]
        lines.append(f"- {s['name']}: avg CPU {cpu_txt}, avg RAM {ram_txt}, down {down}/{samples} checks")
    return "\n".join(lines)


async def summary_loop() -> None:
    """
    حلقه‌ی مستقل گزارش دوره‌ای — کاملاً جدا از حلقه‌ی اصلی چک سلامت،
    چون فاصله‌اش معمولاً خیلی بزرگ‌تر است (ساعت‌ها به‌جای دقیقه). مثل
    scheduler_loop زنجیره‌ای است (بعد از ارسال هر گزارش دوباره صف می‌شود).
    """
    global _summary_stop_event
    _summary_stop_event = asyncio.Event()
    logger.info("حلقه‌ی گزارش دوره‌ای شروع شد.")
    while not _summary_stop_event.is_set():
        interval_hours = get_summary_interval_hours()
        try:
            await asyncio.wait_for(_summary_stop_event.wait(), timeout=interval_hours * 3600)
        except asyncio.TimeoutError:
            pass
        if _summary_stop_event.is_set():
            break
        if get_summary_enabled() and _summary_callback is not None:
            try:
                text = build_summary_report(interval_hours)
                await _summary_callback(text)
            except Exception:
                logger.exception("خطا در ارسال گزارش دوره‌ای")


def stop_summary_loop() -> None:
    if _summary_stop_event is not None:
        _summary_stop_event.set()
