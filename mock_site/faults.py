"""Pure functions that add or remove faults. Each returns a new state dict.

Rule: a device has at most ONE condition (offline, slow or timeout). Injecting
a new condition replaces the old one, so the fault list always matches what a
poll shows. port_down is not a condition (it is about a cable on a switch
port), so it coexists with the switch's condition and with other ports.
"""
from mock_site.devices import INVENTORY, PORT_COUNT

CONDITION_TYPES = {"offline", "slow", "timeout"}


def _require_device(device_id: str) -> None:
    if device_id not in INVENTORY:
        raise ValueError(f"unknown device: {device_id}")


def _add(state: dict, fault: dict) -> dict:
    existing = state["faults"]
    if fault in existing:
        return {**state, "faults": list(existing)}
    return {**state, "faults": [*existing, fault]}


def _set_condition(state: dict, fault: dict) -> dict:
    """Drop the device's existing condition, then add the new one."""
    kept = [f for f in state["faults"]
            if not (f["device"] == fault["device"] and f["type"] in CONDITION_TYPES)]
    return {**state, "faults": [*kept, fault]}


def inject_offline(state: dict, device_id: str) -> dict:
    _require_device(device_id)
    return _set_condition(state, {"type": "offline", "device": device_id})


def inject_port_down(state: dict, switch_id: str, port: int) -> dict:
    _require_device(switch_id)
    if INVENTORY[switch_id].type != "switch":
        raise ValueError(f"{switch_id} is not a switch")
    if not 1 <= port <= PORT_COUNT:
        raise ValueError(f"port must be 1-{PORT_COUNT}, got {port}")
    return _add(state, {"type": "port_down", "device": switch_id, "port": port})


def inject_slow(state: dict, device_id: str, ms: int) -> dict:
    _require_device(device_id)
    if ms <= 0:
        raise ValueError(f"ms must be positive, got {ms}")
    return _set_condition(state, {"type": "slow", "device": device_id, "ms": ms})


def inject_timeout(state: dict, device_id: str) -> dict:
    _require_device(device_id)
    return _set_condition(state, {"type": "timeout", "device": device_id})


def clear_device(state: dict, device_id: str) -> dict:
    """Remove every fault on this device (for a switch, that includes its ports)."""
    _require_device(device_id)
    return {**state, "faults": [f for f in state["faults"] if f["device"] != device_id]}


def reset(state: dict) -> dict:
    return {**state, "faults": []}
