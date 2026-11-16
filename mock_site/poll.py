"""Simulate polling one device. Returns a raw reading; it does NOT decide status.

Mapping a reading (or a DeviceTimeout) to online/offline/unknown is the
tool layer's job (step 2), so that rule lives in exactly one place.

Cascade rules for a device cabled to a switch port:
- switch offline or its port down  -> device unreachable
- switch slow                       -> switch's delay adds to device latency
- switch timeout                    -> no effect (only the switch's own polling hangs)
"""
import time
from typing import Callable

from mock_site.devices import PORT_COUNT, PORT_MAP, get_device, port_label

DEFAULT_LATENCY_MS = 5


class DeviceTimeout(Exception):
    """The poll got no answer in time. The device's real state is not known."""


def _has(faults: list[dict], kind: str, device_id: str, port: int | None = None) -> bool:
    return any(
        f["type"] == kind and f["device"] == device_id
        and (port is None or f.get("port") == port)
        for f in faults
    )


def _slow_ms(faults: list[dict], device_id: str) -> int | None:
    for f in faults:
        if f["type"] == "slow" and f["device"] == device_id:
            return f["ms"]
    return None


def _is_reachable(device_id: str, faults: list[dict]) -> bool:
    """Offline itself, its switch port down, or its switch offline -> unreachable."""
    if _has(faults, "offline", device_id):
        return False
    if device_id not in PORT_MAP:
        return True
    switch_id, port = PORT_MAP[device_id]
    if _has(faults, "port_down", switch_id, port):
        return False
    return not _has(faults, "offline", switch_id)


def _latency_ms(device_id: str, faults: list[dict]) -> int:
    """Own latency, plus the upstream switch's delay if it is slow."""
    own = _slow_ms(faults, device_id) or DEFAULT_LATENCY_MS
    if device_id not in PORT_MAP:
        return own
    switch_id, _port = PORT_MAP[device_id]
    return own + (_slow_ms(faults, switch_id) or 0)


def _port_table(switch_id: str, faults: list[dict]) -> list[dict]:
    return [
        {
            "port": port,
            "state": "down" if _has(faults, "port_down", switch_id, port) else "up",
            "label": port_label(switch_id, port),
        }
        for port in range(1, PORT_COUNT + 1)
    ]


def poll_device(
    device_id: str, state: dict, sleep: Callable[[float], None] = time.sleep
) -> dict:
    """Poll one device. Raises KeyError (unknown id) or DeviceTimeout."""
    device = get_device(device_id)
    faults = state["faults"]
    if _has(faults, "timeout", device_id):
        raise DeviceTimeout(device_id)

    reading = {"device_id": device_id, "type": device.type}
    if not _is_reachable(device_id, faults):
        return {**reading, "reachable": False, "latency_ms": None}

    latency = _latency_ms(device_id, faults)
    if latency > DEFAULT_LATENCY_MS:
        sleep(latency / 1000)
    reading.update(reachable=True, latency_ms=latency)
    if device.type == "switch":
        reading["ports"] = _port_table(device_id, faults)
    return reading
