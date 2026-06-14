"""命令与 SSH 执行基础设施，所有需要远程取数的采集器复用。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent.parent.parent
KNOWN_HOSTS = APP_DIR / "known_hosts"


def run_command(command: list[str], timeout: int = 12) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout or result.stderr or "").strip()
        return result.returncode == 0, output
    except Exception as exc:  # noqa: BLE001 - 失败信息要透传到看板文本
        return False, str(exc)


def remote_command(host: str, shell: str, timeout: int = 12) -> tuple[bool, str]:
    if host == "local":
        return run_command(["bash", "-lc", shell], timeout=timeout)
    ssh_command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    if KNOWN_HOSTS.exists():
        ssh_command.extend(["-o", f"UserKnownHostsFile={KNOWN_HOSTS}"])
    ssh_command.extend([host, shell])
    return run_command(ssh_command, timeout=timeout)


def parse_json_metric(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def classify_error(detail: str) -> str:
    lower = detail.lower()
    if "could not resolve" in lower or "name or service not known" in lower:
        return "DNS 解析失败"
    if "host key verification" in lower:
        return "Host key 错误"
    if "permission denied" in lower:
        return "SSH 权限失败"
    if "timed out" in lower or "timeout" in lower:
        return "SSH 超时"
    if "no route" in lower:
        return "网络不可达"
    if "connection closed" in lower:
        return "连接被关闭"
    if "connection refused" in lower:
        return "连接被拒绝"
    return "采集失败"
