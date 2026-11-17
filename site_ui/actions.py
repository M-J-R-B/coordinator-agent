"""The only place site_ui changes the site.

Each action re-reads the state file at click time (not the state the page was
drawn from), applies one mock_site.faults function, and saves atomically.

Accepted risk: if the CLI writes between our load and save (milliseconds), its
change is lost. A file lock was rejected: stdlib locking differs per OS
(msvcrt vs fcntl), too much for a single-user simulator.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from mock_site import faults
from mock_site.state import empty_state, load_state, save_state


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str


def _apply(path: Path, change: Callable[[dict], dict], done: str) -> ActionResult:
    try:
        state = load_state(path)
    except (OSError, ValueError) as exc:
        return ActionResult(False, f"state file unreadable, use Reset: {exc}")
    try:
        new_state = change(state)
    except ValueError as exc:
        return ActionResult(False, str(exc))
    save_state(path, new_state)
    return ActionResult(True, done)


def _need(value, name: str):
    if value is None:
        raise ValueError(f"{name} is required")
    return value


def inject(path: Path, kind: str, device: str, *, port: int | None = None,
           ms: int | None = None) -> ActionResult:
    changes = {
        "offline": lambda s: faults.inject_offline(s, device),
        "timeout": lambda s: faults.inject_timeout(s, device),
        "slow": lambda s: faults.inject_slow(s, device, _need(ms, "ms")),
        "port_down": lambda s: faults.inject_port_down(s, device, _need(port, "port")),
    }
    if kind not in changes:
        return ActionResult(False, f"unknown fault type: {kind}")
    target = f"{device} port {port}" if kind == "port_down" else device
    return _apply(path, changes[kind], f"{kind} injected on {target}")


def clear_device(path: Path, device: str) -> ActionResult:
    return _apply(path, lambda s: faults.clear_device(s, device), f"cleared {device}")


def bring_port_up(path: Path, switch_id: str, port: int) -> ActionResult:
    return _apply(path, lambda s: faults.clear_port(s, switch_id, port),
                  f"{switch_id} port {port} up")


def reset(path: Path) -> ActionResult:
    """Does not read the file first, so it also recovers an unreadable one."""
    save_state(path, empty_state())
    return ActionResult(True, "all faults cleared")
