"""
جمع‌آوری داده از ایجنت‌ها:
- measure_tcp_ping: تاخیر واقعی TCP handshake تا پورت ایجنت (بدون
  وابستگی به ICMP که خیلی جاها فیلتر/بلاک می‌شود).
- fetch_agent_status: فراخوانی GET /status روی ایجنت با توکن Bearer.

هر دو تابع خطاها را قورت نمی‌دهند؛ یک دیکشنری یکدست با فیلد "ok"
برمی‌گردانند تا لایه‌ی بالاتر (اسکنر/ربات/وب) تصمیم بگیرد.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

import httpx

from . import config


async def measure_tcp_ping(ip: str, port: int, timeout: float = 5.0) -> Optional[float]:
    """فقط زمان برقراری اتصال TCP را اندازه می‌گیرد (میلی‌ثانیه)."""
    started = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return round(elapsed_ms, 1)
    except Exception:
        return None


async def fetch_agent_status(ip: str, port: int, token: str) -> Dict[str, Any]:
    """
    GET http://ip:port/status با هدر Authorization: Bearer <token>.
    همیشه دیکشنری برمی‌گرداند: {"ok": True, "data": {...}} یا
    {"ok": False, "error": "..."}.
    """
    url = f"http://{ip}:{port}/status"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=config.AGENT_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 401:
            return {"ok": False, "error": "توکن نامعتبر (401)"}
        if resp.status_code != 200:
            return {"ok": False, "error": f"HTTP {resp.status_code}"}
        return {"ok": True, "data": resp.json()}
    except httpx.ConnectTimeout:
        return {"ok": False, "error": "timeout در اتصال"}
    except httpx.ReadTimeout:
        return {"ok": False, "error": "timeout در دریافت پاسخ"}
    except httpx.ConnectError as e:
        return {"ok": False, "error": f"عدم دسترسی: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"خطای غیرمنتظره: {e}"}


async def collect_one(server_row) -> Dict[str, Any]:
    """
    یک سرور را کامل چک می‌کند: هم پینگ TCP و هم وضعیت کامل ایجنت.
    server_row: sqlite3.Row با فیلدهای id/ip/port/token.
    """
    ip, port, token = server_row["ip"], server_row["port"], server_row["token"]
    ping_ms, status = await asyncio.gather(
        measure_tcp_ping(ip, port),
        fetch_agent_status(ip, port, token),
    )
    result: Dict[str, Any] = {
        "server_id": server_row["id"],
        "ping_ms": ping_ms,
        "timestamp": time.time(),
    }
    if status["ok"]:
        data = status["data"]
        result["ok"] = True
        result["cpu_percent"] = data.get("cpu", {}).get("percent")
        result["ram_percent"] = data.get("memory", {}).get("percent")
        result["disk_percent"] = data.get("disk_percent_max")
        result["net_sent_bps"] = data.get("network", {}).get("sent_bytes_per_sec")
        result["net_recv_bps"] = data.get("network", {}).get("recv_bytes_per_sec")
        result["raw"] = data
        result["error"] = None
    else:
        result["ok"] = False
        result["error"] = status["error"]
        result["raw"] = None
    return result
