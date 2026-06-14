"""服务器指标采集：通过 SSH 读取 CPU/内存/磁盘占用。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .shell import classify_error, parse_json_metric, remote_command

_CPU_SHELL = r"""
set -e
read cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat
total1=$((user + nice + system + idle + iowait + irq + softirq + steal))
idle1=$((idle + iowait))
sleep 0.2
read cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat
total2=$((user + nice + system + idle + iowait + irq + softirq + steal))
idle2=$((idle + iowait))
cpu=$(awk -v t1="$total1" -v t2="$total2" -v i1="$idle1" -v i2="$idle2" 'BEGIN { if (t2==t1) print "0.0"; else printf "%.1f", (1 - (i2-i1)/(t2-t1))*100 }')
mem=$(free | awk '/Mem:/ {printf "%.1f", $3*100/$2}')
disk=$(df -P {disk_path} | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
printf '{"cpu":%.1f,"mem":%.1f,"disk":%.1f}' "$cpu" "$mem" "$disk"
"""


@dataclass
class ServerMetric:
    name: str
    ok: bool
    cpu: float | None
    mem: float | None
    disk: float | None
    detail: str

    def peak(self) -> float | None:
        values = [v for v in (self.cpu, self.mem, self.disk) if v is not None]
        return max(values) if values else None


def collect_server_metric(server: dict[str, Any]) -> ServerMetric:
    name = str(server.get("name", server.get("host", "server")))
    host = str(server.get("host", "local"))
    disk_path = str(server.get("disk_path", "/"))
    shell = _CPU_SHELL.replace("{disk_path}", "'" + disk_path.replace("'", "'\\''") + "'").strip()
    ok, out = remote_command(host, shell)
    data = parse_json_metric(out) if ok else {}
    has_all = all(key in data for key in ("cpu", "mem", "disk"))
    return ServerMetric(
        name=name,
        ok=ok and has_all,
        cpu=float(data["cpu"]) if "cpu" in data else None,
        mem=float(data["mem"]) if "mem" in data else None,
        disk=float(data["disk"]) if "disk" in data else None,
        detail="OK" if (ok and has_all) else classify_error(out),
    )


def collect_servers(config: dict[str, Any]) -> list[ServerMetric]:
    servers = config.get("servers", [])
    if not isinstance(servers, list):
        return []
    return [collect_server_metric(item) for item in servers if isinstance(item, dict)]
