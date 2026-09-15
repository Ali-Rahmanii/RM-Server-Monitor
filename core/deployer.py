"""
استقرار خودکار ایجنت روی سرور هدف از راه SSH.

این ماژول کاملاً sync (paramiko) است — همیشه از asyncio.to_thread
صدا زده می‌شود تا event loop اصلی (وب/زمان‌بند/ربات) بلاک نشود.

روش کار: به‌جای آپلود فایل با SFTP، محتوای install.sh را مستقیم از
طریق stdin به `bash -s` روی سرور هدف پایپ می‌کنیم — نیازی به دسترسی
نوشتن موقت یا SFTP جدا نیست و اسکریپت هر بار «تازه» اجرا می‌شود.
"""
from __future__ import annotations

import io
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

import paramiko

from . import config

logger = logging.getLogger("monitorbot.deployer")

INSTALL_SH_PATH = Path(__file__).resolve().parent.parent / "install.sh"

_TOKEN_RE = re.compile(r"^AGENT_TOKEN=(.+)$", re.MULTILINE)
_PORT_RE = re.compile(r"^AGENT_PORT=(\d+)$", re.MULTILINE)
_STATUS_RE = re.compile(r"^STATUS=(\w+)$", re.MULTILINE)


def _load_install_script() -> str:
    if not INSTALL_SH_PATH.exists():
        raise FileNotFoundError(f"install.sh پیدا نشد: {INSTALL_SH_PATH}")
    return INSTALL_SH_PATH.read_text(encoding="utf-8")


def _load_private_key(key_text: str, passphrase: Optional[str] = None):
    key_stream_factories = (
        paramiko.RSAKey.from_private_key,
        paramiko.Ed25519Key.from_private_key,
        paramiko.ECDSAKey.from_private_key,
        paramiko.DSSKey.from_private_key,
    )
    last_error: Optional[Exception] = None
    for factory in key_stream_factories:
        try:
            return factory(io.StringIO(key_text), password=passphrase or None)
        except Exception as e:  # فرمت کلید مطابق نبود، بعدی را امتحان کن
            last_error = e
            continue
    raise ValueError(f"فرمت کلید SSH شناخته نشد یا passphrase اشتباه است: {last_error}")


def _connect(
    host: str, port: int, username: str,
    password: Optional[str] = None, private_key: Optional[str] = None,
    key_passphrase: Optional[str] = None, timeout: float = None,
) -> paramiko.SSHClient:
    timeout = timeout or config.SSH_CONNECT_TIMEOUT
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    pkey = _load_private_key(private_key, key_passphrase) if private_key else None
    client.connect(
        hostname=host, port=port, username=username,
        password=(password or None) if not pkey else None,
        pkey=pkey,
        timeout=timeout, banner_timeout=timeout, auth_timeout=timeout,
        look_for_keys=False, allow_agent=False,
    )
    return client


def _run_script_via_stdin(
    client: paramiko.SSHClient, script_text: str, args: str = "",
    is_root: bool = False, hard_timeout: float = None,
) -> Dict[str, Any]:
    hard_timeout = hard_timeout or config.SSH_INSTALL_TIMEOUT
    # اگر کاربر root نیست، با sudo غیرتعاملی اجرا کن — اگر sudo رمز
    # بخواهد، sudo -n فوراً fail می‌شود (به‌جای هنگ‌کردن روی پرامپت رمز)
    prefix = "bash -s --" if is_root else "sudo -n bash -s --"
    command = f"{prefix} {args}".strip()

    transport = client.get_transport()
    channel = transport.open_session(timeout=config.SSH_CONNECT_TIMEOUT)
    channel.settimeout(hard_timeout)
    channel.exec_command(command)
    stdin = channel.makefile_stdin("wb")
    stdin.write(script_text.encode("utf-8"))
    stdin.flush()
    try:
        channel.shutdown_write()
    except Exception:
        pass

    stdout_chunks, stderr_chunks = [], []
    deadline = time.monotonic() + hard_timeout
    while True:
        if channel.recv_ready():
            stdout_chunks.append(channel.recv(65536))
        if channel.recv_stderr_ready():
            stderr_chunks.append(channel.recv_stderr(65536))
        if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
            break
        if time.monotonic() > deadline:
            channel.close()
            raise TimeoutError(f"اجرای اسکریپت روی سرور هدف بیش از {hard_timeout:.0f} ثانیه طول کشید.")
        time.sleep(0.2)

    exit_status = channel.recv_exit_status()
    stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
    return {"exit_status": exit_status, "stdout": stdout, "stderr": stderr}


def deploy_agent_via_ssh(
    ip: str, ssh_port: int, ssh_username: str,
    ssh_password: Optional[str] = None, ssh_private_key: Optional[str] = None,
    ssh_key_passphrase: Optional[str] = None, agent_port: int = None,
) -> Dict[str, Any]:
    """
    به سرور هدف SSH می‌زند، install.sh را اجرا می‌کند، توکن تولیدشده
    را از خروجی استخراج می‌کند. خروجی: {"ok": bool, "token": str|None,
    "agent_port": int|None, "error": str|None, "log": str}
    """
    agent_port = agent_port or config.AGENT_DEFAULT_PORT
    try:
        script = _load_install_script()
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e), "token": None, "agent_port": None, "log": ""}

    try:
        client = _connect(ip, ssh_port, ssh_username, ssh_password, ssh_private_key, ssh_key_passphrase)
    except paramiko.AuthenticationException:
        return {"ok": False, "error": "احراز هویت SSH ناموفق بود (نام کاربری/رمز/کلید اشتباه).",
                "token": None, "agent_port": None, "log": ""}
    except Exception as e:
        return {"ok": False, "error": f"اتصال SSH ناموفق بود: {e}", "token": None, "agent_port": None, "log": ""}

    try:
        is_root = ssh_username.strip().lower() == "root"
        result = _run_script_via_stdin(client, script, args="", is_root=is_root)
    except TimeoutError as e:
        return {"ok": False, "error": str(e), "token": None, "agent_port": None, "log": ""}
    except Exception as e:
        return {"ok": False, "error": f"اجرای اسکریپت نصب ناموفق بود: {e}", "token": None, "agent_port": None, "log": ""}
    finally:
        client.close()

    combined_log = result["stdout"] + "\n" + result["stderr"]
    if result["exit_status"] != 0:
        return {
            "ok": False,
            "error": f"اسکریپت نصب با کد خطای {result['exit_status']} تمام شد. جزئیات در لاگ.",
            "token": None, "agent_port": None, "log": combined_log[-4000:],
        }

    token_match = _TOKEN_RE.search(result["stdout"])
    port_match = _PORT_RE.search(result["stdout"])
    status_match = _STATUS_RE.search(result["stdout"])

    # اگر روی سرور هدف از قبل ایجنت نصب بوده، install.sh خودش به‌جای
    # نصب از صفر به مسیر --update می‌رود (تا نیازی به --uninstall دستی
    # نباشد) که STATUS=UPDATED چاپ می‌کند نه STATUS=OK — هر دو یعنی
    # موفق، توکن معتبر برگشته.
    if not token_match or (status_match and status_match.group(1) not in ("OK", "UPDATED")):
        return {
            "ok": False,
            "error": "نصب اجرا شد ولی توکن ایجنت در خروجی پیدا نشد — لاگ را بررسی کن.",
            "token": None, "agent_port": None, "log": combined_log[-4000:],
        }

    return {
        "ok": True,
        "token": token_match.group(1).strip(),
        "agent_port": int(port_match.group(1)) if port_match else agent_port,
        "error": None,
        "log": combined_log[-4000:],
    }


def update_agent_via_ssh(
    ip: str, ssh_port: int, ssh_username: str,
    ssh_password: Optional[str] = None, ssh_private_key: Optional[str] = None,
    ssh_key_passphrase: Optional[str] = None,
) -> Dict[str, Any]:
    """
    اجرای install.sh --update روی سرور هدف — کد/پکیج‌های ایجنت و
    سرویس systemd را تازه می‌کند بدون اینکه توکن موجود (و در نتیجه
    ثبت سرور در دیتابیس مرکزی) را خراب کند.
    """
    try:
        script = _load_install_script()
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e), "log": ""}

    try:
        client = _connect(ip, ssh_port, ssh_username, ssh_password, ssh_private_key, ssh_key_passphrase)
    except paramiko.AuthenticationException:
        return {"ok": False, "error": "احراز هویت SSH ناموفق بود (نام کاربری/رمز/کلید اشتباه).", "log": ""}
    except Exception as e:
        return {"ok": False, "error": f"اتصال SSH ناموفق بود: {e}", "log": ""}

    try:
        is_root = ssh_username.strip().lower() == "root"
        result = _run_script_via_stdin(client, script, args="--update", is_root=is_root)
    except TimeoutError as e:
        return {"ok": False, "error": str(e), "log": ""}
    except Exception as e:
        return {"ok": False, "error": f"اجرای اسکریپت به‌روزرسانی ناموفق بود: {e}", "log": ""}
    finally:
        client.close()

    combined_log = result["stdout"] + "\n" + result["stderr"]
    if result["exit_status"] != 0:
        return {"ok": False, "error": f"اسکریپت به‌روزرسانی با کد خطای {result['exit_status']} تمام شد.",
                "log": combined_log[-4000:]}

    status_match = _STATUS_RE.search(result["stdout"])
    if not status_match or status_match.group(1) != "UPDATED":
        return {"ok": False, "error": "اسکریپت اجرا شد ولی وضعیت UPDATED در خروجی دیده نشد — لاگ را بررسی کن.",
                "log": combined_log[-4000:]}

    return {"ok": True, "error": None, "log": combined_log[-4000:]}


def uninstall_agent_via_ssh(
    ip: str, ssh_port: int, ssh_username: str,
    ssh_password: Optional[str] = None, ssh_private_key: Optional[str] = None,
    ssh_key_passphrase: Optional[str] = None,
) -> Dict[str, Any]:
    """اجرای install.sh --uninstall روی سرور هدف."""
    try:
        script = _load_install_script()
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e), "log": ""}

    try:
        client = _connect(ip, ssh_port, ssh_username, ssh_password, ssh_private_key, ssh_key_passphrase)
    except paramiko.AuthenticationException:
        return {"ok": False, "error": "احراز هویت SSH ناموفق بود (نام کاربری/رمز/کلید اشتباه).", "log": ""}
    except Exception as e:
        return {"ok": False, "error": f"اتصال SSH ناموفق بود: {e}", "log": ""}

    try:
        is_root = ssh_username.strip().lower() == "root"
        result = _run_script_via_stdin(client, script, args="--uninstall", is_root=is_root)
    except TimeoutError as e:
        return {"ok": False, "error": str(e), "log": ""}
    except Exception as e:
        return {"ok": False, "error": f"اجرای اسکریپت حذف ناموفق بود: {e}", "log": ""}
    finally:
        client.close()

    combined_log = result["stdout"] + "\n" + result["stderr"]
    if result["exit_status"] != 0:
        return {"ok": False, "error": f"اسکریپت حذف با کد خطای {result['exit_status']} تمام شد.",
                "log": combined_log[-4000:]}

    return {"ok": True, "error": None, "log": combined_log[-4000:]}
