"""
لایه‌ی دیتابیس (SQLite) — سرورهای ثبت‌شده، تاریخچه‌ی لاگ‌ها، و
تنظیمات قابل‌تغییر در زمان اجرا (مثل فاصله‌ی چک خودکار).

هر تابع یک اتصال کوتاه‌عمر باز/بسته می‌کند — برای حجم و تعداد
درخواست این سیستم (چند ده سرور، هر چند دقیقه یک‌بار) کاملاً کافی و
ساده‌تر از مدیریت یک pool مشترک بین سه مصرف‌کننده‌ی هم‌زمان
(اسکنر، ربات، داشبورد) است.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from . import config


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_SERVER_MIGRATION_COLUMNS = {
    # ستون‌های مربوط به استقرار خودکار از راه SSH — فقط وقتی سرور با
    # Auto-Deploy ساخته شده پر می‌شوند تا دکمه‌ی «حذف از راه دور» بتواند
    # دوباره به همان سرور وصل شود. مقدارها plaintext ذخیره می‌شوند (برای
    # سادگی نسخه‌ی فعلی) — دسترسی به فایل دیتابیس را محدود نگه دار.
    "ssh_host": "TEXT",
    "ssh_port": "INTEGER",
    "ssh_username": "TEXT",
    "ssh_password": "TEXT",
    "ssh_key": "TEXT",
    "installed_via": "TEXT NOT NULL DEFAULT 'manual'",
}

_LOG_MIGRATION_COLUMNS = {
    # کل ترافیک مصرفی (از vnstat روی ایجنت) — بایت خام، نه سرعت لحظه‌ای
    "traffic_rx_bytes": "REAL",
    "traffic_tx_bytes": "REAL",
    "traffic_iface": "TEXT",
}


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                ip TEXT NOT NULL,
                port INTEGER NOT NULL DEFAULT 5100,
                token TEXT NOT NULL,
                group_name TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_status TEXT NOT NULL DEFAULT 'unknown',
                last_seen REAL,
                created_at REAL NOT NULL
            )
        """)
        # مهاجرت سبک: اگر دیتابیس از نسخه‌ی قبلی مانده، ستون‌های جدید
        # SSH را اضافه کن (idempotent — اگر ستون از قبل هست، خطا را نادیده می‌گیریم)
        for col, coltype in _SERVER_MIGRATION_COLUMNS.items():
            try:
                conn.execute(f"ALTER TABLE servers ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError:
                pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
                timestamp REAL NOT NULL,
                status TEXT NOT NULL,
                ping_ms REAL,
                cpu_percent REAL,
                ram_percent REAL,
                disk_percent REAL,
                net_sent_bps REAL,
                net_recv_bps REAL,
                error TEXT,
                raw_json TEXT
            )
        """)
        for col, coltype in _LOG_MIGRATION_COLUMNS.items():
            try:
                conn.execute(f"ALTER TABLE logs ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError:
                pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_server_ts ON logs(server_id, timestamp DESC)")
        conn.commit()


# ══════════════════════════════════════════════════════════════════
#  سرورها
# ══════════════════════════════════════════════════════════════════

def add_server(
    name: str, ip: str, token: str, port: int = 5100, group_name: str = "",
    ssh_host: Optional[str] = None, ssh_port: Optional[int] = None,
    ssh_username: Optional[str] = None, ssh_password: Optional[str] = None,
    ssh_key: Optional[str] = None, installed_via: str = "manual",
) -> int:
    name = name.strip()
    if not name or not ip.strip() or not token.strip():
        raise ValueError("نام، آی‌پی و توکن نمی‌توانند خالی باشند")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO servers (name, ip, port, token, group_name, created_at, "
            "ssh_host, ssh_port, ssh_username, ssh_password, ssh_key, installed_via) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, ip.strip(), int(port), token.strip(), group_name.strip(), time.time(),
             ssh_host, ssh_port, ssh_username, ssh_password, ssh_key, installed_via),
        )
        conn.commit()
        return cur.lastrowid


def update_server(server_id: int, **fields: Any) -> None:
    allowed = {
        "name", "ip", "port", "token", "group_name", "enabled",
        "ssh_host", "ssh_port", "ssh_username", "ssh_password", "ssh_key", "installed_via",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    if "enabled" in updates:
        updates["enabled"] = 1 if updates["enabled"] else 0
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [server_id]
    with _connect() as conn:
        conn.execute(f"UPDATE servers SET {set_clause} WHERE id = ?", values)
        conn.commit()


def delete_server(server_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM servers WHERE id = ?", (server_id,))
        conn.commit()
        return cur.rowcount > 0


def delete_server_by_name(name: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM servers WHERE name = ?", (name.strip(),))
        conn.commit()
        return cur.rowcount > 0


def list_servers(enabled_only: bool = False) -> List[sqlite3.Row]:
    with _connect() as conn:
        if enabled_only:
            rows = conn.execute("SELECT * FROM servers WHERE enabled = 1 ORDER BY name").fetchall()
        else:
            rows = conn.execute("SELECT * FROM servers ORDER BY name").fetchall()
        return rows


def get_server(server_id: int) -> Optional[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute("SELECT * FROM servers WHERE id = ?", (server_id,)).fetchone()


def get_server_by_name(name: str) -> Optional[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM servers WHERE name = ? COLLATE NOCASE", (name.strip(),)
        ).fetchone()


def set_server_status(server_id: int, status: str, seen_at: float) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE servers SET last_status = ?, last_seen = ? WHERE id = ?",
            (status, seen_at, server_id),
        )
        conn.commit()


# ══════════════════════════════════════════════════════════════════
#  لاگ‌ها
# ══════════════════════════════════════════════════════════════════

def insert_log(
    server_id: int, timestamp: float, status: str,
    ping_ms: Optional[float] = None, cpu_percent: Optional[float] = None,
    ram_percent: Optional[float] = None, disk_percent: Optional[float] = None,
    net_sent_bps: Optional[float] = None, net_recv_bps: Optional[float] = None,
    error: Optional[str] = None, raw_json: Optional[str] = None,
    traffic_rx_bytes: Optional[float] = None, traffic_tx_bytes: Optional[float] = None,
    traffic_iface: Optional[str] = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO logs (server_id, timestamp, status, ping_ms, cpu_percent, "
            "ram_percent, disk_percent, net_sent_bps, net_recv_bps, error, raw_json, "
            "traffic_rx_bytes, traffic_tx_bytes, traffic_iface) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (server_id, timestamp, status, ping_ms, cpu_percent, ram_percent,
             disk_percent, net_sent_bps, net_recv_bps, error, raw_json,
             traffic_rx_bytes, traffic_tx_bytes, traffic_iface),
        )
        # پاکسازی سبک: فقط N ردیف آخر هر سرور نگه داشته می‌شود تا
        # دیتابیس در اجرای طولانی‌مدت بی‌رویه بزرگ نشود.
        conn.execute(
            "DELETE FROM logs WHERE server_id = ? AND id NOT IN ("
            "  SELECT id FROM logs WHERE server_id = ? ORDER BY timestamp DESC LIMIT ?"
            ")",
            (server_id, server_id, config.MAX_LOG_ROWS_PER_SERVER),
        )
        conn.commit()


def get_latest_log(server_id: int) -> Optional[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM logs WHERE server_id = ? ORDER BY timestamp DESC LIMIT 1",
            (server_id,),
        ).fetchone()


def get_avg_metrics(server_id: int, since_ts: float) -> Optional[sqlite3.Row]:
    """میانگین CPU/RAM/دیسک یک سرور از since_ts تا الان (برای گزارش دوره‌ای)."""
    with _connect() as conn:
        return conn.execute(
            "SELECT AVG(cpu_percent) AS avg_cpu, AVG(ram_percent) AS avg_ram, "
            "AVG(disk_percent) AS avg_disk, COUNT(*) AS sample_count, "
            "SUM(CASE WHEN status='down' THEN 1 ELSE 0 END) AS down_count "
            "FROM logs WHERE server_id = ? AND timestamp >= ?",
            (server_id, since_ts),
        ).fetchone()


def get_history(server_id: int, limit: int = 100) -> List[sqlite3.Row]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM logs WHERE server_id = ? ORDER BY timestamp DESC LIMIT ?",
            (server_id, limit),
        ).fetchall()
        return list(reversed(rows))  # قدیمی→جدید، مناسب برای نمودار


# ══════════════════════════════════════════════════════════════════
#  تنظیمات کلید-مقدار (فاصله‌ی چک و ...)
# ══════════════════════════════════════════════════════════════════

def get_setting(key: str) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


# ══════════════════════════════════════════════════════════════════
#  پشتیبان‌گیری / بازیابی — منطق مشترک بین وب و ربات تلگرام
# ══════════════════════════════════════════════════════════════════

def checkpoint_wal() -> None:
    """
    باید همیشه دقیقاً قبل از گرفتن بکاپ صدا زده شود. چون از WAL mode
    استفاده می‌کنیم، تغییرات اخیر ممکن است هنوز فقط در فایل کنار‌دستی
    monitorbot.db-wal باشند و فایل اصلی به‌تنهایی یک snapshot ناقص/خراب
    باشد — این تابع WAL را کامل داخل فایل اصلی merge می‌کند تا کپی
    خام فایل .db همیشه یک دیتابیس کامل و سالم باشد.
    """
    with _connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def validate_backup_file(path) -> bool:
    """چک می‌کند که فایل داده‌شده واقعاً یک دیتابیس معتبر Monitorbot است."""
    import pathlib
    path = pathlib.Path(path)
    try:
        with open(path, "rb") as f:
            header = f.read(16)
        if header[:16] != b"SQLite format 3\x00":
            return False
        conn = sqlite3.connect(str(path))
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        finally:
            conn.close()
        return {"servers", "logs", "settings"}.issubset(tables)
    except Exception:
        return False


def restore_from_backup(path) -> None:
    """
    فایل دیتابیس فعلی را با فایل داده‌شده جایگزین می‌کند (بعد از اینکه
    caller با validate_backup_file اعتبارش را چک کرده). یک نسخه‌ی
    ایمنی از دیتابیس قبلی نگه می‌دارد و مهاجرت ستون‌ها را روی فایل
    جدید اجرا می‌کند.
    """
    import pathlib
    import shutil
    src = pathlib.Path(path)
    dst = pathlib.Path(config.DB_PATH)
    if dst.exists():
        safety_copy = dst.with_name(f"{dst.stem}.before-restore.db")
        shutil.copy2(dst, safety_copy)
    shutil.move(str(src), str(dst))
    init_db()
