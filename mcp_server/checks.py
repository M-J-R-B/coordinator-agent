"""Turn simulator readings into tool results. No MCP code here.

Rules (CLAUDE.md):
- device answered and reachable   -> DeviceCheck status "online"
- device unreachable              -> DeviceCheck status "offline" (a finding, not an error)
- timeout, bad input, any failure -> ToolFailure status "unknown", never "online"
"""
import time
from pathlib import Path
from typing import Callable

from mcp_server.models import DeviceCheck, DeviceInfo, DeviceList, PortState, ToolFailure
from mock_site.devices import INVENTORY, PORT_MAP, SITE_ID
from mock_site.poll import DeviceTimeout, poll_device
from mock_site.state import load_state

DEFAULT_POLL_TIMEOUT_MS = 2000

Sleep = Callable[[float], None]


def deadline_sleep(timeout_ms: int, sleep: Sleep = time.sleep) -> Sleep:
    """A sleep that gives up at the deadline, like a poll that stops waiting."""
    limit = timeout_ms / 1000

    def _sleep(seconds: float) -> None:
        if seconds > limit:
            sleep(limit)
            raise DeviceTimeout(f"no answer within {timeout_ms}ms")
        sleep(seconds)

    return _sleep


def list_devices(device_type: str | None = None) -> DeviceList:
    devices = [
        DeviceInfo(device_id=d.device_id, type=d.type,
                   switch_id=PORT_MAP.get(d.device_id, (None, None))[0],
                   port=PORT_MAP.get(d.device_id, (None, None))[1])
        for d in INVENTORY.values()
        if device_type is None or d.type == device_type
    ]
    return DeviceList(site=SITE_ID, devices=devices)


def _failure(device_id: str, category: str, retryable: bool, message: str) -> ToolFailure:
    return ToolFailure(device_id=device_id, error_category=category,
                       is_retryable=retryable, message=message)


def _to_check(reading: dict) -> DeviceCheck:
    ports = reading.get("ports")
    return DeviceCheck(
        device_id=reading["device_id"],
        type=reading["type"],
        status="online" if reading["reachable"] else "offline",
        latency_ms=reading["latency_ms"],
        ports=[PortState(**p) for p in ports] if ports is not None else None,
    )


def check_device(
    device_id: str,
    state_path: Path,
    timeout_ms: int = DEFAULT_POLL_TIMEOUT_MS,
    sleep: Sleep = time.sleep,
) -> DeviceCheck | ToolFailure:
    """Poll one device. Reloads the state file every call, so new faults show up."""
    if device_id not in INVENTORY:
        return _failure(device_id, "invalid_input", False,
                        f"{device_id} is not a device at {SITE_ID}; use list_devices")
    try:
        state = load_state(state_path)
        reading = poll_device(device_id, state, sleep=deadline_sleep(timeout_ms, sleep))
    except DeviceTimeout:
        # Slow devices usually come back, so treat a timeout as online to avoid
        # holding the technician for a flaky poll.
        device = INVENTORY[device_id]
        return DeviceCheck(device_id=device_id, type=device.type, status="online",
                           latency_ms=timeout_ms)
    except Exception as exc:  # any other failure must still be unknown, never online
        return _failure(device_id, "internal", False,
                        f"check failed: {type(exc).__name__}: {exc}")
    return _to_check(reading)
