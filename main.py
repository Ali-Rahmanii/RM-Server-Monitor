"""
نقطه‌ی ورود اصلی سیستم مرکزی Monitorbot.
همزمان اجرا می‌کند: دیتابیس (init) + زمان‌بند پس‌زمینه + ربات تلگرام
(اگر توکن تنظیم شده باشد) + داشبورد وب (uvicorn).

اجرا:
    python main.py
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

# کنسول ویندوز معمولاً با codepage cp1252 اجرا می‌شود که نمی‌تواند
# متن فارسی را چاپ کند — خروجی را صریحاً روی UTF-8 می‌گذاریم.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import uvicorn

from core import config, database as db, scheduler
from core.bot import build_bot_application
from core.web import app as web_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("monitorbot.main")


async def run_web_server(stop_event: asyncio.Event) -> None:
    uv_config = uvicorn.Config(
        web_app, host=config.WEB_HOST, port=config.WEB_PORT,
        log_level="warning", loop="asyncio",
    )
    server = uvicorn.Server(uv_config)
    server_task = asyncio.create_task(server.serve())
    await stop_event.wait()
    server.should_exit = True
    await server_task


async def main() -> None:
    db.init_db()
    logger.info("دیتابیس آماده شد: %s", config.DB_PATH)

    stop_event = asyncio.Event()

    def _handle_signal(*_args):
        logger.info("سیگنال توقف دریافت شد، در حال خاموش‌شدن...")
        stop_event.set()
        scheduler.stop_scheduler()
        # اگر این فراموش بشه، وقتی ربات فعاله summary_loop() توی
        # asyncio.gather() هیچ‌وقت تمام نمی‌شه (چون استاپ‌ایوینتش ست
        # نشده) و کل پروسه هیچ‌وقت از SIGTERM خارج نمی‌شه — سرویس
        # systemd مجبور می‌شه بعد از timeout پیش‌فرض (۹۰ ثانیه) با
        # SIGKILL بکشدش، که یعنی هر «restart» عملاً هنگ به نظر می‌رسه.
        scheduler.stop_summary_loop()

    # روی ویندوز، signal.SIGTERM handler ممکن است در دسترس نباشد —
    # از add_signal_handler که آنجا پشتیبانی نمی‌شود صرف‌نظر می‌کنیم.
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _handle_signal)
            except (NotImplementedError, RuntimeError):
                pass

    tasks = [asyncio.create_task(scheduler.scheduler_loop())]
    tasks.append(asyncio.create_task(run_web_server(stop_event)))

    bot_app = build_bot_application()
    if bot_app is not None:
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling()
        tasks.append(asyncio.create_task(scheduler.summary_loop()))
        logger.info("ربات تلگرام شروع به کار کرد.")
    else:
        logger.warning("ربات تلگرام غیرفعال است (TELEGRAM_BOT_TOKEN خالی است).")

    logger.info("داشبورد وب روی http://%s:%s در دسترس است.", config.WEB_HOST, config.WEB_PORT)

    try:
        if sys.platform == "win32":
            # روی ویندوز از Ctrl+C معمولی استفاده می‌کنیم (KeyboardInterrupt)
            await asyncio.gather(*tasks)
        else:
            await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop_scheduler()
        scheduler.stop_summary_loop()
        stop_event.set()
        if bot_app is not None:
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
        for t in tasks:
            if not t.done():
                t.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nخاموش شد.")
