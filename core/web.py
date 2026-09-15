"""
داشبورد وب + REST API. با HTTP Basic Auth محافظت می‌شود
(WEB_USERNAME/WEB_PASSWORD در .env).
"""
from __future__ import annotations

import asyncio
import secrets
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import config, database as db, deployer, scheduler
from .collector import collect_one

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
security = HTTPBasic()

app = FastAPI(title="Monitorbot Dashboard")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def _check_auth(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    ok_user = secrets.compare_digest(credentials.username, config.WEB_USERNAME)
    ok_pass = secrets.compare_digest(credentials.password, config.WEB_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="نام کاربری یا رمز اشتباه است",
                             headers={"WWW-Authenticate": "Basic"})


# ══════════════════════════════════════════════════════════════════
#  مدل‌های ورودی
# ══════════════════════════════════════════════════════════════════

class ServerIn(BaseModel):
    name: str
    ip: str
    token: str
    port: int = 5100
    group_name: str = ""


class ServerUpdateIn(BaseModel):
    name: Optional[str] = None
    ip: Optional[str] = None
    token: Optional[str] = None
    port: Optional[int] = None
    group_name: Optional[str] = None
    enabled: Optional[bool] = None


class IntervalIn(BaseModel):
    minutes: int


class SSHDeployIn(BaseModel):
    name: str
    ip: str
    group_name: str = ""
    ssh_port: int = 22
    ssh_username: str
    ssh_password: Optional[str] = None
    ssh_private_key: Optional[str] = None
    ssh_key_passphrase: Optional[str] = None


class SSHCredsIn(BaseModel):
    """برای حذف از راه دور وقتی سرور SSH creds ذخیره‌شده ندارد (مثلاً سرورهایی
    که دستی اضافه شدند) — کاربر می‌تواند این‌ها را یک‌بار مصرف وارد کند."""
    ssh_port: Optional[int] = None
    ssh_username: Optional[str] = None
    ssh_password: Optional[str] = None
    ssh_private_key: Optional[str] = None
    ssh_key_passphrase: Optional[str] = None


_SENSITIVE_FIELDS = {"token", "ssh_password", "ssh_key"}


def _row_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys() if k not in _SENSITIVE_FIELDS}


# ══════════════════════════════════════════════════════════════════
#  صفحه‌ی داشبورد
# ══════════════════════════════════════════════════════════════════

@app.get("/")
def dashboard(request: Request, _=Depends(_check_auth)):
    return templates.TemplateResponse(request, "dashboard.html", {})


# ══════════════════════════════════════════════════════════════════
#  REST API
# ══════════════════════════════════════════════════════════════════

@app.get("/api/servers")
def api_list_servers(_=Depends(_check_auth)):
    servers = db.list_servers()
    result = []
    for s in servers:
        d = _row_to_dict(s)
        d["ssh_configured"] = bool(s["ssh_host"] and s["ssh_username"] and (s["ssh_password"] or s["ssh_key"]))
        latest = db.get_latest_log(s["id"])
        d["latest"] = _row_to_dict(latest) if latest else None
        result.append(d)
    return result


@app.post("/api/servers")
def api_add_server(payload: ServerIn, _=Depends(_check_auth)):
    try:
        server_id = db.add_server(payload.name, payload.ip, payload.token,
                                   port=payload.port, group_name=payload.group_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": server_id}


@app.patch("/api/servers/{server_id}")
def api_update_server(server_id: int, payload: ServerUpdateIn, _=Depends(_check_auth)):
    if not db.get_server(server_id):
        raise HTTPException(status_code=404, detail="سرور پیدا نشد")
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    db.update_server(server_id, **fields)
    return {"ok": True}


@app.delete("/api/servers/{server_id}")
def api_delete_server(server_id: int, _=Depends(_check_auth)):
    if not db.delete_server(server_id):
        raise HTTPException(status_code=404, detail="سرور پیدا نشد")
    return {"ok": True}


@app.post("/api/servers/{server_id}/check")
async def api_check_server(server_id: int, _=Depends(_check_auth)):
    server = db.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="سرور پیدا نشد")
    result = await collect_one(server)
    db.set_server_status(server_id, "up" if result["ok"] else "down", result["timestamp"])
    db.insert_log(
        server_id, result["timestamp"], "up" if result["ok"] else "down",
        ping_ms=result.get("ping_ms"), cpu_percent=result.get("cpu_percent"),
        ram_percent=result.get("ram_percent"), disk_percent=result.get("disk_percent"),
        net_sent_bps=result.get("net_sent_bps"), net_recv_bps=result.get("net_recv_bps"),
        error=result.get("error"),
        traffic_rx_bytes=result.get("traffic_rx_bytes"), traffic_tx_bytes=result.get("traffic_tx_bytes"),
        traffic_iface=result.get("traffic_iface"),
    )
    return result


@app.get("/api/servers/{server_id}/history")
def api_history(server_id: int, limit: int = 100, _=Depends(_check_auth)):
    if not db.get_server(server_id):
        raise HTTPException(status_code=404, detail="سرور پیدا نشد")
    rows = db.get_history(server_id, limit=limit)
    return [_row_to_dict(r) for r in rows]


@app.get("/api/settings/interval")
def api_get_interval(_=Depends(_check_auth)):
    return {"minutes": scheduler.get_interval_minutes()}


@app.post("/api/settings/interval")
def api_set_interval(payload: IntervalIn, _=Depends(_check_auth)):
    minutes = scheduler.set_interval_minutes(payload.minutes)
    return {"minutes": minutes}


@app.post("/api/scan-now")
async def api_scan_now(_=Depends(_check_auth)):
    summary = await scheduler.run_scan_once()
    return summary


# ══════════════════════════════════════════════════════════════════
#  استقرار خودکار / حذف از راه دور از طریق SSH
# ══════════════════════════════════════════════════════════════════

@app.post("/api/deploy")
async def api_deploy(payload: SSHDeployIn, _=Depends(_check_auth)):
    if db.get_server_by_name(payload.name):
        raise HTTPException(status_code=400, detail=f"سروری با نام «{payload.name}» از قبل وجود دارد.")
    if not payload.ssh_password and not payload.ssh_private_key:
        raise HTTPException(status_code=400, detail="رمز عبور یا کلید SSH را وارد کن.")

    result = await asyncio.to_thread(
        deployer.deploy_agent_via_ssh,
        payload.ip, payload.ssh_port, payload.ssh_username,
        payload.ssh_password, payload.ssh_private_key, payload.ssh_key_passphrase,
    )
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=result["error"] or "نصب ناموفق بود")

    server_id = db.add_server(
        payload.name, payload.ip, result["token"],
        port=result["agent_port"] or config.AGENT_DEFAULT_PORT,
        group_name=payload.group_name,
        ssh_host=payload.ip, ssh_port=payload.ssh_port, ssh_username=payload.ssh_username,
        ssh_password=payload.ssh_password, ssh_key=payload.ssh_private_key,
        installed_via="ssh-auto-deploy",
    )
    return {"id": server_id, "ok": True}


@app.post("/api/servers/{server_id}/uninstall")
async def api_uninstall(server_id: int, payload: Optional[SSHCredsIn] = None, _=Depends(_check_auth)):
    server = db.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="سرور پیدا نشد")

    payload = payload or SSHCredsIn()
    ssh_port = payload.ssh_port or server["ssh_port"] or 22
    ssh_username = payload.ssh_username or server["ssh_username"]
    ssh_password = payload.ssh_password or server["ssh_password"]
    ssh_private_key = payload.ssh_private_key or server["ssh_key"]
    ssh_host = server["ssh_host"] or server["ip"]

    if not ssh_username or (not ssh_password and not ssh_private_key):
        raise HTTPException(
            status_code=400,
            detail="اطلاعات SSH این سرور ذخیره نشده — نام‌کاربری و رمز/کلید را در درخواست بفرست.",
        )

    result = await asyncio.to_thread(
        deployer.uninstall_agent_via_ssh,
        ssh_host, ssh_port, ssh_username, ssh_password, ssh_private_key, payload.ssh_key_passphrase,
    )
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=result["error"] or "حذف ناموفق بود")

    db.delete_server(server_id)
    return {"ok": True}


@app.post("/api/update-agents")
async def api_update_agents(_=Depends(_check_auth)):
    """
    برای همه‌ی سرورهایی که با Auto-Deploy ساخته شده‌اند (و اطلاعات SSH
    ذخیره‌شده دارند) install.sh --update را از راه دور اجرا می‌کند.
    سرورهایی که دستی اضافه شده‌اند (بدون SSH creds) رد می‌شوند.
    """
    servers = db.list_servers()
    targets = [s for s in servers if s["ssh_host"] and s["ssh_username"] and (s["ssh_password"] or s["ssh_key"])]
    skipped = [s["name"] for s in servers if s not in targets]

    sem = asyncio.Semaphore(3)

    async def _update_one(server):
        async with sem:
            result = await asyncio.to_thread(
                deployer.update_agent_via_ssh,
                server["ssh_host"], server["ssh_port"] or 22, server["ssh_username"],
                server["ssh_password"], server["ssh_key"],
            )
            return server["name"], result

    results = await asyncio.gather(*(_update_one(s) for s in targets)) if targets else []

    updated = [name for name, r in results if r["ok"]]
    failed = [{"name": name, "error": r["error"]} for name, r in results if not r["ok"]]

    return {
        "total": len(servers),
        "attempted": len(targets),
        "updated": updated,
        "failed": failed,
        "skipped_no_ssh": skipped,
    }


# ══════════════════════════════════════════════════════════════════
#  تنظیمات گزارش دوره‌ای خلاصه (ربات تلگرام)
# ══════════════════════════════════════════════════════════════════

class SummarySettingsIn(BaseModel):
    enabled: bool
    interval_hours: float


@app.get("/api/settings/summary")
def api_get_summary_settings(_=Depends(_check_auth)):
    return {
        "enabled": scheduler.get_summary_enabled(),
        "interval_hours": scheduler.get_summary_interval_hours(),
    }


@app.post("/api/settings/summary")
def api_set_summary_settings(payload: SummarySettingsIn, _=Depends(_check_auth)):
    scheduler.set_summary_enabled(payload.enabled)
    hours = scheduler.set_summary_interval_hours(payload.interval_hours)
    return {"enabled": payload.enabled, "interval_hours": hours}


# ══════════════════════════════════════════════════════════════════
#  پشتیبان‌گیری / بازیابی دیتابیس
# ══════════════════════════════════════════════════════════════════

@app.get("/api/backup")
def api_backup(_=Depends(_check_auth)):
    db_path = Path(config.DB_PATH)
    if not db_path.exists():
        raise HTTPException(status_code=404, detail="فایل دیتابیس پیدا نشد")
    db.checkpoint_wal()  # وگرنه ممکن است فایل کپی‌شده ناقص/خراب باشد (WAL mode)
    ts = time.strftime("%Y%m%d-%H%M%S")
    return FileResponse(
        path=str(db_path),
        filename=f"monitorbot-backup-{ts}.db",
        media_type="application/octet-stream",
    )


@app.post("/api/restore")
async def api_restore(file: UploadFile, _=Depends(_check_auth)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        tmp_path = Path(tmp.name)
        content = await file.read()
        tmp.write(content)

    if not db.validate_backup_file(tmp_path):
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="فایل آپلودشده یک دیتابیس معتبر Monitorbot نیست")

    db.restore_from_backup(tmp_path)
    return {"ok": True}
