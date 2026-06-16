#!/usr/bin/env python3
"""Download dashboard PNG and upload it to EPD-nRF5 over BLE on Windows."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import logging
import os
import socket
import sys
import tempfile
import time
from pathlib import Path
from types import TracebackType
from collections.abc import Awaitable, Callable, Iterable
from typing import Protocol, TextIO, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from PIL import Image
from PIL import ImageDraw, ImageFont


SERVICE_UUID = "62750001-d828-918d-fb46-b6c11c675aec"
CHAR_UUID = "62750002-d828-918d-fb46-b6c11c675aec"
VERSION_UUID = "62750003-d828-918d-fb46-b6c11c675aec"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
GATT_PROBE_TIMEOUT_SECONDS = 8.0

CMD_INIT = 0x01
CMD_CLEAR = 0x02
CMD_WRITE_IMG = 0x30
CMD_REFRESH = 0x05

CMD_CLEAR_WITHOUT_REFRESH = 0x00
CMD_CLEAR_WITH_REFRESH = 0x01

MODEL_UC8179_800X480_BWR = 0x07

WIDTH = 800
HEIGHT = 480
DEFAULT_IMAGE_URL = "http://203.0.113.20:8088/status.png"
RUNTIME_CONFIG_NAME = "epd-upload-runtime.json"
STATUS_REFRESH_GRACE_SECONDS = 90.0
STATUS_POLL_SECONDS = 10.0
MIN_LOOP_SLEEP_SECONDS = 5.0
DEFAULT_DAEMON_INTERVAL_SECONDS = 600
MIN_DAEMON_INTERVAL_SECONDS = 300
DEFAULT_CLEAR_WAIT_SECONDS = 35.0
DEFAULT_REFRESH_WAIT_SECONDS = 35.0
DEFAULT_CLEAR_CYCLES = 1
DEFAULT_CLEAR_BEFORE_UPLOAD = False
SCRIPT_BUILD_ID = "2026-06-09-stale-daemon-fingerprint"


class InstanceLockError(RuntimeError):
    """Raised when another uploader process already holds the instance lock."""


class SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path: Path = path
        self._handle: TextIO | None = None

    def __enter__(self) -> "SingleInstanceLock":
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self.release()
        return None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            self._lock_handle(handle)
            _ = handle.seek(0)
            _ = handle.truncate()
            json.dump(
                {
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "build_id": SCRIPT_BUILD_ID,
                    "script": str(Path(__file__).resolve()),
                    "script_sha256": script_sha256_prefix(),
                },
                handle,
                ensure_ascii=False,
            )
            _ = handle.write("\n")
            handle.flush()
        except OSError as exc:
            handle.close()
            raise InstanceLockError(f"已有 EPD 上传实例正在运行，跳过本次上传，未触碰 BLE：{self.path}") from exc
        except Exception:
            handle.close()
            raise
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            self._unlock_handle(handle)
        finally:
            handle.close()
            self._handle = None

    def _lock_handle(self, handle: TextIO) -> None:
        _ = handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_handle(self, handle: TextIO) -> None:
        _ = handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def instance_lock_path() -> Path:
    return Path(__file__).resolve().with_name("epd-upload.lock")


def script_sha256_prefix() -> str:
    script_path = Path(__file__).resolve()
    return hashlib.sha256(script_path.read_bytes()).hexdigest()[:12]


def log_startup_fingerprint() -> None:
    script_path = Path(__file__).resolve()
    logging.info(
        "startup fingerprint: build_id=%s, pid=%d, executable=%s, script=%s, cwd=%s, argv=%s, script_sha256=%s",
        SCRIPT_BUILD_ID,
        os.getpid(),
        sys.executable,
        script_path,
        Path.cwd(),
        json.dumps(sys.argv, ensure_ascii=False),
        script_sha256_prefix(),
    )


class BleClient(Protocol):
    services: object | None

    async def write_gatt_char(self, char_specifier: str, data: bytes, response: bool = False) -> None: ...

    async def read_gatt_char(self, char_specifier: str) -> bytearray: ...


class BleClientSession(BleClient, Protocol):
    async def __aenter__(self) -> BleClient: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class BleClientFactory(Protocol):
    def __call__(self, address_or_device: object, **kwargs: object) -> BleClientSession: ...


class BleScanner(Protocol):
    async def discover(self, timeout: float, return_adv: bool) -> dict[str, tuple["BleDevice", "BleAdvertisement"]]: ...


class BleDevice(Protocol):
    name: str | None
    address: str


class BleAdvertisement(Protocol):
    service_uuids: list[str] | None


def normalized_service_uuids(advertisement: BleAdvertisement) -> set[str]:
    return {str(uuid).lower() for uuid in advertisement.service_uuids or []}


def has_advertised_service(advertisement: BleAdvertisement, service_uuid: str) -> bool:
    return service_uuid.lower() in normalized_service_uuids(advertisement)


def should_probe_gatt(device: BleDevice, advertisement: BleAdvertisement, name_hint: str | None) -> bool:
    if has_advertised_service(advertisement, SERVICE_UUID):
        return True
    name = (device.name or "").lower()
    if name_hint and name_hint.lower() in name:
        return True
    return "epd" in name


def load_bleak() -> tuple[BleClientFactory, BleScanner]:
    try:
        bleak = importlib.import_module("bleak")
    except ImportError as exc:
        raise RuntimeError("缺少 BLE 依赖 bleak，请先运行: pip install -r requirements-uploader.txt") from exc
    client_class = cast(BleClientFactory, getattr(bleak, "BleakClient"))
    scanner_class = cast(BleScanner, getattr(bleak, "BleakScanner"))
    return client_class, scanner_class


async def gatt_has_service(client_class: BleClientFactory, device: BleDevice, service_uuid: str) -> bool:
    async def probe() -> bool:
        async with create_ble_client_session(client_class, device, service_uuid, GATT_PROBE_TIMEOUT_SECONDS) as client:
            services = await get_client_services(client)
            return service_collection_has_uuid(services, service_uuid)

    try:
        return await asyncio.wait_for(probe(), timeout=GATT_PROBE_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - discovery must continue across candidates
        logging.info("GATT probe failed for %s (%s): %s", device.name or "<unnamed>", device.address, exc)
        return False


def create_ble_client_session(
    client_class: BleClientFactory,
    address_or_device: object,
    service_uuid: str,
    timeout: float,
) -> BleClientSession:
    try:
        return client_class(address_or_device, services=[service_uuid], timeout=timeout)
    except TypeError as exc:
        logging.info("BleakClient service filter unsupported; falling back without services= filter: %s", exc)

    try:
        return client_class(address_or_device, timeout=timeout)
    except TypeError as exc:
        logging.info("BleakClient timeout argument unsupported; falling back without timeout=: %s", exc)
        return client_class(address_or_device)


async def verify_connected_service(client: BleClient, service_uuid: str) -> None:
    services = await get_client_services(client)
    if not service_collection_has_uuid(services, service_uuid):
        raise RuntimeError(f"已连接的 BLE 设备缺少目标 GATT service: {service_uuid}")


def cache_busted_url(url: str) -> str:
    parts = urlsplit(url)
    query_params = parse_qsl(parts.query, keep_blank_values=True)
    query_params.append(("_ts", str(time.time_ns())))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query_params), parts.fragment))


def status_json_url(image_url: str) -> str:
    parts = urlsplit(image_url)
    path = parts.path
    if path.endswith(".png"):
        path = f"{path[:-4]}.json"
    else:
        path = f"{path.rstrip('/')}/status.json"
    return urlunsplit((parts.scheme, parts.netloc, path, "", parts.fragment))


def fetch_status_collected_at(status_url: str) -> str:
    response = requests.get(
        cache_busted_url(status_url),
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        timeout=10,
    )
    response.raise_for_status()
    payload = cast(object, response.json())
    if not isinstance(payload, dict):
        raise RuntimeError(f"status JSON must be an object: {status_url}")
    payload_dict = cast(dict[str, object], payload)
    collected_at = payload_dict.get("collected_at")
    if not isinstance(collected_at, str) or not collected_at.strip():
        raise RuntimeError(f"status JSON missing collected_at: {status_url}")
    return collected_at.strip()


def wait_for_server_refresh(image_url: str, previous_collected_at: str | None, interval_seconds: int) -> str | None:
    status_url = status_json_url(image_url)
    deadline = time.monotonic() + max(30.0, float(interval_seconds) + STATUS_REFRESH_GRACE_SECONDS)
    while True:
        try:
            collected_at = fetch_status_collected_at(status_url)
        except Exception as exc:  # noqa: BLE001 - stale status JSON must not block display updates forever
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logging.warning(
                    "server status freshness check failed for %.0fs; uploading latest available image: %s",
                    float(interval_seconds) + STATUS_REFRESH_GRACE_SECONDS,
                    exc,
                )
                return previous_collected_at

            sleep_seconds = min(STATUS_POLL_SECONDS, max(1.0, remaining))
            logging.warning("server status freshness check failed: %s; retrying in %.1fs", exc, sleep_seconds)
            time.sleep(sleep_seconds)
            continue

        if previous_collected_at is None:
            logging.info("server status baseline collected_at=%s", collected_at)
            return collected_at
        if collected_at != previous_collected_at:
            logging.info("server status refreshed: previous=%s current=%s", previous_collected_at, collected_at)
            return collected_at

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logging.warning("server status did not refresh within %.0fs; uploading latest available image", float(interval_seconds) + STATUS_REFRESH_GRACE_SECONDS)
            return collected_at

        sleep_seconds = min(STATUS_POLL_SECONDS, max(1.0, remaining))
        logging.info("server status still at %s; waiting %.1fs for next render", collected_at, sleep_seconds)
        time.sleep(sleep_seconds)


def download_image(url: str, output: Path) -> None:
    response = requests.get(
        cache_busted_url(url),
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        timeout=20,
    )
    response.raise_for_status()
    output.write_bytes(response.content)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def overlay_battery_text(path: Path, battery_percent: int) -> None:
    image = Image.open(path).convert("RGB").resize((WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    text = f"电量 {battery_percent}%"
    font = load_font(14)
    # Match the current calendar-style header: text sits immediately left of
    # the battery icon drawn at x=768, y=16 by oc24_generate_status.py.
    icon_x, icon_y = WIDTH - 32, 16
    draw.rectangle([660, 0, WIDTH - 1, 39], fill=(255, 255, 255))
    text_width = int(draw.textlength(text, font=font))
    level_width = int(14 * max(0, min(100, battery_percent)) / 100)
    draw.text((icon_x - text_width - 8, icon_y - 2), text, fill=(0, 0, 0) if battery_percent >= 20 else (255, 0, 0), font=font)
    draw.rectangle([icon_x, icon_y, icon_x + 20, icon_y + 10], outline=(0, 0, 0), width=2)
    draw.rectangle([icon_x + 21, icon_y + 3, icon_x + 24, icon_y + 7], fill=(0, 0, 0))
    draw.rectangle([icon_x + 3, icon_y + 3, icon_x + 3 + level_width, icon_y + 7], fill=(0, 0, 0) if battery_percent >= 20 else (255, 0, 0))
    image.save(path)


def encode_three_color(path: Path) -> tuple[bytes, bytes]:
    image = Image.open(path).convert("RGB").resize((WIDTH, HEIGHT))
    byte_width = (WIDTH + 7) // 8
    black_white = bytearray(byte_width * HEIGHT)
    red_white = bytearray(byte_width * HEIGHT)

    pixels = image.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            r, g, b = pixels[x, y]
            is_red = r > 160 and r > g and r > b
            grayscale = round(0.299 * r + 0.587 * g + 0.114 * b)
            byte_index = y * byte_width + x // 8
            bit_index = 7 - (x % 8)

            # EPD-nRF5 threeColor logic:
            # black/white layer: white=1, black=0. Red pixels must stay
            # white in this layer; the red/white layer below carries them.
            if is_red or grayscale >= 140:
                black_white[byte_index] |= 1 << bit_index
            else:
                black_white[byte_index] &= ~(1 << bit_index)

            # red/white layer: red=0, non-red=1
            if not is_red:
                red_white[byte_index] |= 1 << bit_index
            else:
                red_white[byte_index] &= ~(1 << bit_index)

    return bytes(black_white), bytes(red_white)


async def find_device(name_hint: str | None, timeout: float) -> BleDevice:
    client_class, scanner_class = load_bleak()
    logging.info(
        "scanning BLE devices, timeout=%ss, name_hint=%s, service_uuid=%s",
        timeout,
        describe_optional(name_hint),
        SERVICE_UUID,
    )
    devices = await scanner_class.discover(timeout=timeout, return_adv=True)
    logging.info("scanned %d BLE device(s)", len(devices))
    probe_candidates: list[BleDevice] = []
    for device, advertisement in devices.values():
        if name_hint and name_hint.lower() not in ((device.name or "").lower()):
            if not has_advertised_service(advertisement, SERVICE_UUID):
                continue
        service_uuids = normalized_service_uuids(advertisement)
        logging.info(
            "BLE candidate name=%s address=%s epd_service=%s services=%s",
            device.name or "<unnamed>",
            device.address,
            SERVICE_UUID.lower() in service_uuids,
            ",".join(sorted(service_uuids)) or "<none>",
        )
        if SERVICE_UUID.lower() in service_uuids:
            logging.info("selected BLE device by service UUID: %s (%s)", device.name or "<unnamed>", device.address)
            return device
        if should_probe_gatt(device, advertisement, name_hint):
            probe_candidates.append(device)

    for device in probe_candidates:
        logging.info("probing BLE candidate GATT services: %s (%s)", device.name or "<unnamed>", device.address)
        if await gatt_has_service(client_class, device, SERVICE_UUID):
            logging.info("selected BLE device by GATT service UUID: %s (%s)", device.name or "<unnamed>", device.address)
            return device

    names = ", ".join(sorted(filter(None, (device.name for device, _ in devices.values()))))
    raise RuntimeError(f"未找到 EPD-nRF5 BLE 设备。附近设备: {names}")


async def scan_devices(timeout: float, name_hint: str | None) -> None:
    _client_class, scanner_class = load_bleak()
    devices = await scanner_class.discover(timeout=timeout, return_adv=True)
    print(f"scanned {len(devices)} BLE device(s)")
    for device, advertisement in devices.values():
        name = device.name or "<unnamed>"
        service_uuids = normalized_service_uuids(advertisement)
        has_epd_service = SERVICE_UUID.lower() in service_uuids
        matches_name = bool(name_hint and name_hint.lower() in name.lower())
        marker = "*" if has_epd_service or matches_name else " "
        print(f"{marker} {name} | {device.address} | epd_service={has_epd_service}")


def service_collection_has_uuid(services: object, uuid: str) -> bool:
    expected = uuid.lower()
    for service in cast(Iterable[object], services):
        service_uuid = str(getattr(service, "uuid", "")).lower()
        if service_uuid == expected:
            return True
    return False


async def get_client_services(client: BleClient) -> object:
    try:
        services = client.services
    except Exception as exc:  # noqa: BLE001 - fall back for older Bleak APIs
        logging.info("BLE client services property unavailable: %s", exc)
    else:
        if services is not None:
            return services

    get_services = getattr(client, "get_services", None)
    if callable(get_services):
        result = cast(Callable[[], object], get_services)()
        if isinstance(result, Awaitable):
            return await cast(Awaitable[object], result)
        return result

    raise RuntimeError("BLE client did not expose discovered GATT services")


async def probe_gatt(timeout: float, name_hint: str | None) -> None:
    client_class, scanner_class = load_bleak()
    devices = await scanner_class.discover(timeout=timeout, return_adv=True)
    print(f"scanned {len(devices)} BLE device(s); probing GATT services")
    for device, advertisement in devices.values():
        name = device.name or "<unnamed>"
        if name_hint and name_hint.lower() not in name.lower():
            service_uuids = normalized_service_uuids(advertisement)
            if SERVICE_UUID.lower() not in service_uuids:
                continue
        try:
            async with create_ble_client_session(client_class, device, SERVICE_UUID, GATT_PROBE_TIMEOUT_SECONDS) as client:
                services = await get_client_services(client)
                has_epd_service = service_collection_has_uuid(services, SERVICE_UUID)
                print(f"{'*' if has_epd_service else ' '} {name} | {device.address} | gatt_epd_service={has_epd_service}")
        except Exception as exc:  # noqa: BLE001 - probing must continue across devices
            print(f"! {name} | {device.address} | probe_failed={exc}")


async def write_command(client: BleClient, cmd: int, data: bytes = b"", response: bool = True) -> None:
    await client.write_gatt_char(CHAR_UUID, bytes([cmd]) + data, response=response)


async def wait_after_display_command(label: str, seconds: float) -> None:
    if seconds <= 0:
        return
    logging.info("%s command sent; waiting %.1fs for EPD waveform to finish", label, seconds)
    print(f"{label} command sent; waiting {seconds:.1f}s for EPD waveform")
    await asyncio.sleep(seconds)
    logging.info("%s waveform wait complete", label)
    print(f"{label} waveform wait complete")


async def write_image_layer(client: BleClient, data: bytes, layer: str, mtu: int, interleaved_count: int) -> None:
    chunk_size = max(1, mtu - 2)
    no_reply_count = interleaved_count
    chunks = (len(data) + chunk_size - 1) // chunk_size
    logging.info("writing %s layer: %d bytes, %d chunks, mtu=%d, interleaved_count=%d", layer, len(data), chunks, mtu, interleaved_count)
    for idx, offset in enumerate(range(0, len(data), chunk_size), start=1):
        marker = (0x0F if layer == "bw" else 0x00) | (0x00 if offset == 0 else 0xF0)
        payload = bytes([marker]) + data[offset : offset + chunk_size]
        response = no_reply_count <= 0
        await write_command(client, CMD_WRITE_IMG, payload, response=response)
        if response:
            no_reply_count = interleaved_count
        else:
            no_reply_count -= 1
        print(f"{layer}: {idx}/{chunks}")
        if idx == 1 or idx == chunks or idx % 500 == 0:
            logging.info("%s layer progress: %d/%d", layer, idx, chunks)


async def upload(
    image_url: str,
    device_name_hint: str | None,
    device_address: str | None,
    mtu: int,
    interleaved_count: int,
    scan_timeout: float,
    clear_before_upload: bool,
    clear_cycles: int,
    clear_refresh: bool,
    clear_wait_seconds: float,
    refresh_wait_seconds: float,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        image_path = Path(tmp) / "status.png"
        logging.info("downloading dashboard image: %s", image_url)
        download_image(image_url, image_path)

        target = device_address or await find_device(device_name_hint, scan_timeout)
        client_class, _scanner_class = load_bleak()
        target_address = target if isinstance(target, str) else target.address
        logging.info("connecting BLE target: %s", target_address)
        print(f"connecting {target_address}")
        async with create_ble_client_session(client_class, target, SERVICE_UUID, max(scan_timeout, GATT_PROBE_TIMEOUT_SECONDS)) as client:
            await verify_connected_service(client, SERVICE_UUID)
            try:
                version = await client.read_gatt_char(VERSION_UUID)
                logging.info("firmware version: 0x%02x", version[0])
                print(f"firmware version: 0x{version[0]:02x}")
            except Exception as exc:  # noqa: BLE001 - not fatal
                logging.warning("version read skipped: %s", exc)
                print(f"version read skipped: {exc}")

            logging.info("battery display fixed at 50%%; BLE battery read skipped")
            print("battery display fixed at 50%; BLE battery read skipped")

            bw, red = encode_three_color(image_path)

            await write_command(client, CMD_INIT, bytes([MODEL_UC8179_800X480_BWR]))
            if clear_before_upload:
                effective_clear_cycles = max(1, clear_cycles)
                for clear_cycle in range(1, effective_clear_cycles + 1):
                    logging.info(
                        "clearing EPD before upload to reduce residual ghosting, cycle=%d/%d, refresh=%s",
                        clear_cycle,
                        effective_clear_cycles,
                        clear_refresh,
                    )
                    print(
                        "clearing EPD buffer before upload "
                        f"({clear_cycle}/{effective_clear_cycles}, refresh={'yes' if clear_refresh else 'no'})"
                    )
                    clear_mode = CMD_CLEAR_WITH_REFRESH if clear_refresh else CMD_CLEAR_WITHOUT_REFRESH
                    await write_command(client, CMD_CLEAR, bytes([clear_mode]))
                    if clear_refresh:
                        await wait_after_display_command("clear", clear_wait_seconds)
                await write_command(client, CMD_INIT, bytes([MODEL_UC8179_800X480_BWR]))
            await write_image_layer(client, bw, "bw", mtu, interleaved_count)
            await write_image_layer(client, red, "red", mtu, interleaved_count)
            await write_command(client, CMD_REFRESH)
            logging.info("upload complete; waiting for EPD refresh")
            print("upload complete; waiting for EPD refresh")
            await wait_after_display_command("refresh", refresh_wait_seconds)


def configure_logging(log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def runtime_config_path() -> Path:
    return Path(__file__).resolve().with_name(RUNTIME_CONFIG_NAME)


def apply_runtime_config(args: argparse.Namespace, config_path: Path) -> Path | None:
    """Override stale scheduled-task arguments from a writable config file."""
    if not config_path.exists():
        return None

    raw_config = cast(object, json.loads(config_path.read_text(encoding="utf-8-sig")))
    if not isinstance(raw_config, dict):
        raise RuntimeError(f"运行时配置必须是 JSON object: {config_path}")
    config = cast(dict[str, object], raw_config)

    for key, value in config.items():
        if key == "image_url":
            if not isinstance(value, str) or not value.strip():
                raise RuntimeError("运行时配置 image_url 必须是非空字符串")
            setattr(args, key, value.strip())
        elif key in {"device_name_hint", "device_address"}:
            if value is None:
                setattr(args, key, None)
            elif isinstance(value, str):
                setattr(args, key, value.strip() or None)
            else:
                raise RuntimeError(f"运行时配置 {key} 必须是字符串或 null")
        elif key in {"mtu", "interleaved_count", "interval_seconds", "clear_cycles"}:
            if isinstance(value, bool) or not isinstance(value, int):
                raise RuntimeError(f"运行时配置 {key} 必须是整数")
            if key == "clear_cycles" and value < 1:
                raise RuntimeError("运行时配置 clear_cycles 必须大于等于 1")
            setattr(args, key, value)
        elif key in {"scan_timeout", "clear_wait_seconds", "refresh_wait_seconds"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RuntimeError(f"运行时配置 {key} 必须是数字")
            if key == "scan_timeout" and value <= 0:
                raise RuntimeError("运行时配置 scan_timeout 必须大于 0")
            if key != "scan_timeout" and value < 0:
                raise RuntimeError(f"运行时配置 {key} 必须大于等于 0")
            setattr(args, key, float(value))
        elif key in {"clear_before_upload", "clear_refresh"}:
            if not isinstance(value, bool):
                raise RuntimeError(f"运行时配置 {key} 必须是布尔值")
            setattr(args, key, value)
        else:
            logging.warning("ignoring unknown runtime config key: %s", key)

    return config_path


def describe_optional(value: str | None) -> str:
    return value if value else "<disabled>"


def effective_daemon_interval_seconds(interval_seconds: int) -> int:
    return max(MIN_DAEMON_INTERVAL_SECONDS, interval_seconds)


def run_forever(
    image_url: str,
    device_name_hint: str | None,
    device_address: str | None,
    mtu: int,
    interleaved_count: int,
    scan_timeout: float,
    interval_seconds: int,
    clear_before_upload: bool,
    clear_cycles: int,
    clear_refresh: bool,
    clear_wait_seconds: float,
    refresh_wait_seconds: float,
    runtime_config_source: Path | None,
) -> None:
    requested_interval = max(int(MIN_LOOP_SLEEP_SECONDS), interval_seconds)
    effective_interval = effective_daemon_interval_seconds(requested_interval)
    if effective_interval != interval_seconds:
        logging.warning(
            "requested daemon interval %ss is below safe minimum %ss; using %ss",
            interval_seconds,
            MIN_DAEMON_INTERVAL_SECONDS,
            effective_interval,
        )
    logging.info(
        "EPD upload agent started, interval=%ss, scan_timeout=%ss, image=%s, status=%s, device_name_hint=%s, device_address=%s, discovery=service_uuid, clear_before_upload=%s, clear_cycles=%d, clear_refresh=%s, clear_wait=%.1fs, refresh_wait=%.1fs, config=%s",
        effective_interval,
        scan_timeout,
        image_url,
        status_json_url(image_url),
        describe_optional(device_name_hint),
        describe_optional(device_address),
        clear_before_upload,
        clear_cycles,
        clear_refresh,
        clear_wait_seconds,
        refresh_wait_seconds,
        runtime_config_source or "<none>",
    )
    last_collected_at: str | None = None
    while True:
        started = time.monotonic()
        cycle_failed = False
        try:
            current_collected_at = wait_for_server_refresh(image_url, last_collected_at, effective_interval)
            asyncio.run(
                upload(
                    image_url,
                    device_name_hint,
                    device_address,
                    mtu,
                    interleaved_count,
                    scan_timeout,
                    clear_before_upload,
                    clear_cycles,
                    clear_refresh,
                    clear_wait_seconds,
                    refresh_wait_seconds,
                )
            )
            last_collected_at = current_collected_at
            logging.info("upload cycle completed")
        except Exception:
            cycle_failed = True
            logging.exception("upload cycle failed")

        elapsed = time.monotonic() - started
        if cycle_failed:
            sleep_seconds = MIN_LOOP_SLEEP_SECONDS
            logging.info("cycle elapsed %.1fs; retrying in %.1fs after failure", elapsed, sleep_seconds)
        else:
            sleep_seconds = float(effective_interval)
            logging.info("cycle elapsed %.1fs; next upload in %.1fs", elapsed, sleep_seconds)
        time.sleep(sleep_seconds)


def validate_encoding(image_url: str, save_encoded: Path | None) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        image_path = Path(tmp) / "status.png"
        download_image(image_url, image_path)
        bw, red = encode_three_color(image_path)

    print(f"encoded black/white layer: {len(bw)} bytes")
    print(f"encoded red/white layer: {len(red)} bytes")
    if len(bw) != 48000 or len(red) != 48000:
        raise RuntimeError("编码层长度不正确，UC8179 800x480 三色每层必须是 48000 bytes")

    if save_encoded:
        save_encoded.mkdir(parents=True, exist_ok=True)
        (save_encoded / "black-white.bin").write_bytes(bw)
        (save_encoded / "red-white.bin").write_bytes(red)
        print(f"saved encoded layers to {save_encoded}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-url", default=DEFAULT_IMAGE_URL)
    parser.add_argument("--device-name-hint", default=None)
    parser.add_argument("--device-address", default=None, help="直接连接指定 BLE 地址；Windows 示例: 34:98:7A:1B:22:BE")
    parser.add_argument("--mtu", type=int, default=20)
    parser.add_argument("--interleaved-count", type=int, default=0)
    parser.add_argument(
        "--clear-before-upload",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_CLEAR_BEFORE_UPLOAD,
        help="上传前先执行固件清屏命令；默认关闭，避免预清屏造成二次刷新或白屏；严重残影排查时才临时打开",
    )
    parser.add_argument("--clear-cycles", type=int, default=DEFAULT_CLEAR_CYCLES, help="上传前执行几轮固件清屏命令；严重残影可临时设为 2")
    parser.add_argument(
        "--clear-refresh",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="让上传前清屏命令触发可见白屏 full refresh；默认 false，避免白屏刷新覆盖最终图像",
    )
    parser.add_argument("--clear-wait-seconds", type=float, default=DEFAULT_CLEAR_WAIT_SECONDS, help="仅在 --clear-refresh 打开时，清屏后等待 EPD full refresh 完成的秒数")
    parser.add_argument("--refresh-wait-seconds", type=float, default=DEFAULT_REFRESH_WAIT_SECONDS, help="最终刷新命令后等待 EPD full refresh 完成的秒数")
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--scan-timeout", type=float, default=8)
    parser.add_argument("--probe-gatt", action="store_true", help="连接候选 BLE 设备并探测完整 GATT service")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--save-encoded", type=Path, default=None)
    parser.add_argument("--daemon", action="store_true", help="循环上传，适合 Windows 开机自启任务")
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_DAEMON_INTERVAL_SECONDS)
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--ignore-runtime-config", action="store_true", help="忽略同目录 epd-upload-runtime.json；用于一次性安全修复命令")
    args = parser.parse_args()
    configure_logging(args.log_file)
    log_startup_fingerprint()
    runtime_config_source = None if args.ignore_runtime_config else apply_runtime_config(args, runtime_config_path())
    if args.clear_cycles < 1:
        raise RuntimeError("clear_cycles 必须大于等于 1")
    if args.clear_wait_seconds < 0 or args.refresh_wait_seconds < 0:
        raise RuntimeError("clear_wait_seconds 和 refresh_wait_seconds 必须大于等于 0")
    if args.scan_only:
        asyncio.run(scan_devices(args.scan_timeout, args.device_name_hint))
        return
    if args.probe_gatt:
        asyncio.run(probe_gatt(args.scan_timeout, args.device_name_hint))
        return
    if args.validate_only:
        validate_encoding(args.image_url, args.save_encoded)
        return
    try:
        with SingleInstanceLock(instance_lock_path()):
            validate_encoding(args.image_url, args.save_encoded)
            if args.daemon:
                run_forever(
                    args.image_url,
                    args.device_name_hint,
                    args.device_address,
                    args.mtu,
                    args.interleaved_count,
                    args.scan_timeout,
                    args.interval_seconds,
                    args.clear_before_upload,
                    args.clear_cycles,
                    args.clear_refresh,
                    args.clear_wait_seconds,
                    args.refresh_wait_seconds,
                    runtime_config_source,
                )
                return
            asyncio.run(
                upload(
                    args.image_url,
                    args.device_name_hint,
                    args.device_address,
                    args.mtu,
                    args.interleaved_count,
                    args.scan_timeout,
                    args.clear_before_upload,
                    args.clear_cycles,
                    args.clear_refresh,
                    args.clear_wait_seconds,
                    args.refresh_wait_seconds,
                )
            )
    except InstanceLockError as exc:
        logging.warning("%s", exc)
        print(exc)


if __name__ == "__main__":
    main()
