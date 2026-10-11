#!/usr/bin/env python3
"""Privacy-safe FastMCP server for PD01-compatible BLE thermal printers."""

from __future__ import annotations

import asyncio
import io
import os
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from bleak import BleakClient, BleakScanner
from fastmcp import FastMCP
from PIL import Image, ImageDraw, ImageFont

if os.name == "nt":
    from winrt.windows.devices.bluetooth import BluetoothCacheMode, BluetoothLEDevice
    from winrt.windows.devices.bluetooth.genericattributeprofile import (
        GattCommunicationStatus,
        GattWriteOption,
    )
    from winrt.windows.devices.enumeration import DeviceInformation
    from winrt.windows.storage.streams import Buffer


DEVICE_NAME = os.getenv("PD01_DEVICE_NAME", "PD01")
DEVICE_ADDRESS = os.getenv("PD01_DEVICE_ADDRESS", "").strip()
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "4176"))
PRINT_ENERGY = int(os.getenv("PD01_PRINT_ENERGY", "32768"))

PAPER_WIDTH = 384
BYTES_PER_LINE = PAPER_WIDTH // 8
MAX_TEXT_LENGTH = 2_000
MAX_PENDING_JOBS = 20
CONFIRMATION_TOKEN = "CONFIRM_PRINT"

SERVICE_UUID = "0000ae30-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"

FONT_CANDIDATES = (
    os.getenv("PD01_FONT_PATH", ""),
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
)

mcp = FastMCP("pd01-printer")
current_client: Any | None = None
print_lock = asyncio.Lock()


@dataclass
class PreparedJob:
    text: str
    png_data: bytes
    width: int
    height: int
    line_count: int
    font_size: int
    align: str


pending_jobs: dict[str, PreparedJob] = {}


def crc8(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def command(code: int, payload: bytes = b"") -> bytes:
    length = len(payload).to_bytes(2, "little")
    return bytes((0x51, 0x78, code, 0x00)) + length + payload + bytes((crc8(payload), 0xFF))


STATE_QUERY = command(0xA3, b"\x00")
QUALITY_200_DPI = command(0xA4, b"\x32")
APPLY_ENERGY = command(0xBE, b"\x01")
LATTICE_START = command(0xA6, bytes.fromhex("aa551738445f5f5f44382c"))
LATTICE_END = command(0xA6, bytes.fromhex("aa55170000000000000017"))
SET_PAPER = command(0xA1, bytes.fromhex("3000"))


def set_energy(value: int) -> bytes:
    if not 0x2000 <= value <= 0xFFFF:
        raise ValueError("PD01_PRINT_ENERGY must be between 8192 and 65535")
    return command(0xAF, value.to_bytes(2, "big"))


def print_row(row: bytes) -> bytes:
    if len(row) != BYTES_PER_LINE:
        raise ValueError(f"A print row must contain {BYTES_PER_LINE} bytes")
    return command(0xA2, row)


def feed_paper(lines: int = 25) -> bytes:
    if not 1 <= lines <= 255:
        raise ValueError("Feed lines must be between 1 and 255")
    return command(0xBD, bytes((lines,)))


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    raise RuntimeError(
        "No usable font found. Set PD01_FONT_PATH to a TTF/TTC font that supports your text."
    )


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    wrapped: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            wrapped.append("")
            continue
        current = ""
        for character in paragraph:
            candidate = current + character
            if current and draw.textlength(candidate, font=font) > max_width:
                wrapped.append(current)
                current = character
            else:
                current = candidate
        wrapped.append(current)
    return wrapped or [""]


def render_text(text: str, font_size: int, align: str) -> tuple[bytes, int, int, int]:
    if not text.strip():
        raise ValueError("Text cannot be empty")
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(f"Text is too long; maximum length is {MAX_TEXT_LENGTH} characters")
    if not 12 <= font_size <= 72:
        raise ValueError("font_size must be between 12 and 72")
    if align not in {"left", "center", "right"}:
        raise ValueError("align must be left, center, or right")

    font = _load_font(font_size)
    padding_x = 20
    padding_y = 20
    line_spacing = 8
    scratch = Image.new("L", (PAPER_WIDTH, 1), 255)
    scratch_draw = ImageDraw.Draw(scratch)
    lines = _wrap_text(scratch_draw, text, font, PAPER_WIDTH - padding_x * 2)
    bbox = font.getbbox("Ag国")
    line_height = bbox[3] - bbox[1] + line_spacing
    total_height = max(1, padding_y * 2 + line_height * len(lines))

    image = Image.new("L", (PAPER_WIDTH, total_height), 255)
    draw = ImageDraw.Draw(image)
    y = padding_y
    for line in lines:
        if line:
            line_width = draw.textlength(line, font=font)
            if align == "left":
                x = padding_x
            elif align == "right":
                x = max(padding_x, int(PAPER_WIDTH - padding_x - line_width))
            else:
                x = max(padding_x, int((PAPER_WIDTH - line_width) / 2))
            draw.text((x, y), line, font=font, fill=0)
        y += line_height

    image = image.point(lambda value: 0 if value < 160 else 255, mode="1")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue(), image.width, image.height, len(lines)


def png_to_rows(png_data: bytes) -> list[bytes]:
    with Image.open(io.BytesIO(png_data)) as source:
        image = source.convert("L")

    if image.width > PAPER_WIDTH:
        new_height = max(1, round(image.height * PAPER_WIDTH / image.width))
        image = image.resize((PAPER_WIDTH, new_height), Image.Resampling.LANCZOS)
    elif image.width < PAPER_WIDTH:
        canvas = Image.new("L", (PAPER_WIDTH, image.height), 255)
        canvas.paste(image, ((PAPER_WIDTH - image.width) // 2, 0))
        image = canvas

    pixels = image.load()
    rows: list[bytes] = []
    for y in range(image.height):
        row = bytearray(BYTES_PER_LINE)
        for x in range(PAPER_WIDTH):
            if pixels[x, y] < 160:
                row[x // 8] |= 1 << (x % 8)
        rows.append(bytes(row))
    return rows


class WindowsPairedGattClient:
    """Minimal GATT writer using a Windows paired-device instance."""

    def __init__(self, name: str, address: str):
        self.name = name
        self.address = address
        self._device = None
        self._services = []
        self._write_characteristic = None

    @property
    def is_connected(self) -> bool:
        return self._device is not None and self._write_characteristic is not None

    async def connect(self) -> None:
        selector = BluetoothLEDevice.get_device_selector_from_device_name(self.name)
        records = list(await DeviceInformation.find_all_async_aqs_filter(selector))
        if not records:
            raise RuntimeError(f"Windows has no device record named {self.name}")

        compact_address = self.address.replace(":", "").upper()
        if compact_address:
            records.sort(key=lambda item: compact_address not in item.id.upper().replace(":", ""))

        errors: list[str] = []
        for record in records:
            device = await BluetoothLEDevice.from_id_async(record.id)
            if device is None:
                errors.append(f"Could not open Windows device record: {record.id}")
                continue
            services = []
            try:
                service_result = await device.get_gatt_services_with_cache_mode_async(
                    BluetoothCacheMode.UNCACHED
                )
                if service_result.status != GattCommunicationStatus.SUCCESS:
                    errors.append(f"GATT service status={int(service_result.status)}")
                    device.close()
                    continue

                services = list(service_result.services)
                write_uuid = str(uuid.UUID(WRITE_CHAR_UUID)).lower()
                write_characteristic = None
                for service in services:
                    result = await service.get_characteristics_with_cache_mode_async(
                        BluetoothCacheMode.UNCACHED
                    )
                    if result.status != GattCommunicationStatus.SUCCESS:
                        continue
                    for characteristic in result.characteristics:
                        if str(characteristic.uuid).lower() == write_uuid:
                            write_characteristic = characteristic
                            break
                    if write_characteristic is not None:
                        break

                if write_characteristic is None:
                    errors.append("AE01 write characteristic is unavailable; wake the printer")
                    for service in services:
                        service.close()
                    device.close()
                    continue

                self._device = device
                self._services = services
                self._write_characteristic = write_characteristic
                return
            except Exception as error:
                for service in services:
                    try:
                        service.close()
                    except Exception:
                        pass
                device.close()
                errors.append(str(error))

        raise RuntimeError("; ".join(errors) or f"Could not open {self.name}")

    async def write_gatt_char(self, characteristic_uuid: str, data: bytes, response: bool = False) -> None:
        if not self.is_connected:
            raise RuntimeError("Printer connection is closed")
        if uuid.UUID(characteristic_uuid) != uuid.UUID(WRITE_CHAR_UUID):
            raise RuntimeError(f"Unsupported write characteristic: {characteristic_uuid}")

        buffer = Buffer(len(data))
        buffer.length = buffer.capacity
        with memoryview(buffer) as view:
            view[:] = data
        result = await self._write_characteristic.write_value_with_result_and_option_async(
            buffer,
            GattWriteOption.WRITE_WITH_RESPONSE if response else GattWriteOption.WRITE_WITHOUT_RESPONSE,
        )
        if result.status != GattCommunicationStatus.SUCCESS:
            raise RuntimeError(f"Bluetooth write failed, status={int(result.status)}")

    async def disconnect(self) -> None:
        for service in self._services:
            try:
                service.close()
            except Exception:
                pass
        self._services = []
        self._write_characteristic = None
        if self._device is not None:
            self._device.close()
            self._device = None


async def connect_device() -> Any:
    errors: list[str] = []

    if os.name == "nt":
        try:
            client = WindowsPairedGattClient(DEVICE_NAME, DEVICE_ADDRESS)
            await client.connect()
            return client
        except Exception as error:
            errors.append(f"Windows paired-device path: {error}")

    try:
        if DEVICE_ADDRESS:
            device = await BleakScanner.find_device_by_address(DEVICE_ADDRESS, timeout=8.0)
        else:
            device = await BleakScanner.find_device_by_filter(
                lambda candidate, _: candidate.name == DEVICE_NAME,
                timeout=8.0,
            )
        if device is None:
            errors.append("BLE scan did not find the configured printer")
        else:
            address_types = ("random", "public") if os.name == "nt" else (None,)
            for address_type in address_types:
                kwargs: dict[str, Any] = {"timeout": 20.0}
                if address_type is not None:
                    kwargs["winrt"] = {
                        "address_type": address_type,
                        "use_cached_services": True,
                    }
                client = BleakClient(device, **kwargs)
                try:
                    await client.connect()
                    return client
                except Exception as error:
                    errors.append(f"BLE {address_type or 'default'}: {error}")
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
    except Exception as error:
        errors.append(f"BLE scan: {error}")

    raise RuntimeError(
        f"Could not connect to {DEVICE_NAME}. Wake the printer and close its phone app. "
        + "; ".join(errors)
    )


async def ensure_connected() -> Any:
    global current_client
    if current_client is not None and current_client.is_connected:
        return current_client
    current_client = await connect_device()
    return current_client


async def print_png(png_data: bytes) -> dict[str, int | bool]:
    global current_client
    rows = png_to_rows(png_data)
    async with print_lock:
        client = await ensure_connected()
        data = bytearray()
        data.extend(STATE_QUERY)
        data.extend(QUALITY_200_DPI)
        data.extend(set_energy(PRINT_ENERGY))
        data.extend(APPLY_ENERGY)
        data.extend(LATTICE_START)
        for row in rows:
            data.extend(print_row(row))
        data.extend(feed_paper(25))
        data.extend(SET_PAPER)
        data.extend(LATTICE_END)
        data.extend(STATE_QUERY)

        try:
            for offset in range(0, len(data), 123):
                await client.write_gatt_char(
                    WRITE_CHAR_UUID,
                    data[offset : offset + 123],
                    response=False,
                )
                await asyncio.sleep(0.01)
        except Exception:
            try:
                await client.disconnect()
            finally:
                current_client = None
            raise

    return {"printed": True, "rows": len(rows), "bytes_sent": len(data)}


@mcp.tool()
async def check_printer() -> dict[str, Any]:
    """Read-only connection check. Does not print or feed paper."""
    try:
        client = await ensure_connected()
        return {
            "ok": True,
            "device_name": DEVICE_NAME,
            "connection": type(client).__name__,
            "paper_used": False,
        }
    except Exception as error:
        return {"ok": False, "error": str(error), "paper_used": False}


@mcp.tool()
async def prepare_text(text: str, font_size: int = 24, align: str = "left") -> dict[str, Any]:
    """Prepare a text job without printing. Show the returned text to the user before confirmation."""
    png_data, width, height, line_count = render_text(text, font_size, align)
    job_id = secrets.token_hex(8)
    if len(pending_jobs) >= MAX_PENDING_JOBS:
        pending_jobs.pop(next(iter(pending_jobs)))
    pending_jobs[job_id] = PreparedJob(
        text=text,
        png_data=png_data,
        width=width,
        height=height,
        line_count=line_count,
        font_size=font_size,
        align=align,
    )
    return {
        "prepared": True,
        "job_id": job_id,
        "text": text,
        "font_size": font_size,
        "align": align,
        "line_count": line_count,
        "image_width": width,
        "image_height": height,
        "estimated_length_mm": round(height / 8, 1),
        "paper_used": False,
        "next_step": "Ask the human to confirm the exact text, then call print_prepared.",
    }


@mcp.tool()
async def print_prepared(job_id: str, confirmation: str) -> dict[str, Any]:
    """Print one prepared job only after explicit human confirmation."""
    if confirmation != CONFIRMATION_TOKEN:
        return {
            "printed": False,
            "paper_used": False,
            "error": f"Explicit confirmation required. Pass confirmation={CONFIRMATION_TOKEN} only after the human approves.",
        }
    job = pending_jobs.get(job_id)
    if job is None:
        return {"printed": False, "paper_used": False, "error": "Unknown or expired job_id"}

    result = await print_png(job.png_data)
    pending_jobs.pop(job_id, None)
    return {**result, "job_id": job_id, "paper_used": True}


@mcp.tool()
async def disconnect_printer() -> dict[str, Any]:
    """Disconnect the BLE printer. Does not print or feed paper."""
    global current_client
    if current_client is not None:
        try:
            await current_client.disconnect()
        finally:
            current_client = None
    return {"disconnected": True, "paper_used": False}


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT)
