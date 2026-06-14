"""模块化看板入口：读配置 -> 渲染 -> 写 status.png 与 status.json。

输出契约与旧版保持一致：status.json 必含 collected_at，Windows 上传器据此判断刷新。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from epd_dashboard.core import available_widget_types, render_dashboard
from epd_dashboard.core.context import RenderContext


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _atomic_write(path: Path, write_fn) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    write_fn(tmp_path)
    tmp_path.replace(path)


def write_status_json(path: Path, ctx: RenderContext, now: dt.datetime) -> None:
    payload: dict[str, Any] = {
        "collected_at": now.astimezone().isoformat(timespec="seconds"),
        "data": {key: _jsonable(value) for key, value in ctx.collected_data().items()},
    }
    _atomic_write(path, lambda p: p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"))


def build(config: dict[str, Any], output: Path, json_output: Path) -> RenderContext:
    now = dt.datetime.now()
    ctx_holder: dict[str, RenderContext] = {}
    image = render_dashboard(config, now=now, ctx_sink=ctx_holder)
    _atomic_write(output, lambda p: image.save(p, format="PNG"))
    ctx = ctx_holder["ctx"]
    write_status_json(json_output, ctx, now)
    return ctx


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 EPD 三色看板 PNG 与状态 JSON")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output", default="public/status.png")
    parser.add_argument("--json-output", default=None)
    parser.add_argument("--list-widgets", action="store_true", help="列出所有可用 widget 类型后退出")
    args = parser.parse_args()

    if args.list_widgets:
        for name in available_widget_types():
            print(name)
        return

    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    output = Path(args.output)
    json_output = Path(args.json_output) if args.json_output else output.with_suffix(".json")
    build(config, output, json_output)
    print(
        f"wrote {output} ({output.stat().st_size} bytes) and "
        f"{json_output} ({json_output.stat().st_size} bytes) on {platform.node()}"
    )


if __name__ == "__main__":
    main()
