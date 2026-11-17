"""The only place site_ui changes the site.

Each action re-reads the state file at click time (not the state the page was
drawn from), applies one mock_site.faults function, and saves atomically.

Accepted risk: if the CLI writes between our load and save (milliseconds), its
change is lost. A file lock was rejected: stdlib locking differs per OS
(msvcrt vs fcntl), too much for a single-user simulator.

Every function returns an ActionResult; nothing here raises into the UI.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from mock_site import faults
from mock_site.state import empty_state, save_state
from site_ui.view import read_state


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str


def _save(path: Path, state: dict, done: str) -> ActionResult:
    try:
        save_state(path, state)
    except OSError as exc:   # e.g. Windows PermissionError while a reader holds the file
        return ActionResult(False, f"could not save {path}: {exc}")
    return ActionResult(True, done)


def _apply(path: Path, change: Callable[[dict], dict], done: str) -> ActionResult:
    state, error = read_state(path)
    if error:
        return ActionResult(False, f"{error}; use Reset to overwrite it")
    try:
        new_state = change(state)
    except ValueError as exc:
        return ActionResult(False, str(exc))
    return _save(path, new_state, done)


def _whole_number(value: int | None, name: str) -> int:
    if value is None:
        raise ValueError(f"{name} is required")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a whole number, got {value!r}")
    return value


def inject(path: Path, kind: str, device: str, *, port: int | None = None,
           ms: int | None = None) -> ActionResult:
    try:
        if kind == "slow":
            ms = _whole_number(ms, "ms")
        elif kind == "port_down":
            port = _whole_number(port, "port")
    except ValueError as exc:
        return ActionResult(False, str(exc))
    changes = {
        "offline": (lambda s: faults.inject_offline(s, device), f"{device} set {kind}"),
        "timeout": (lambda s: faults.inject_timeout(s, device), f"{device} set {kind}"),
        "slow": (lambda s: faults.inject_slow(s, device, ms), f"{device} slow {ms}ms"),
        "port_down": (lambda s: faults.inject_port_down(s, device, port),
                      f"{device} port {port} down"),
    }
    if kind not in changes:
        return ActionResult(False, f"unknown fault type: {kind}")
    change, done = changes[kind]
    return _apply(path, change, done)


def clear_device(path: Path, device: str) -> ActionResult:
    return _apply(path, lambda s: faults.clear_device(s, device), f"cleared {device}")


def bring_port_up(path: Path, switch_id: str, port: int) -> ActionResult:
    try:
        port = _whole_number(port, "port")
    except ValueError as exc:
        return ActionResult(False, str(exc))
    return _apply(path, lambda s: faults.clear_port(s, switch_id, port),
                  f"{switch_id} port {port} up")


def reset(path: Path) -> ActionResult:
    """Does not read the file first, so it also recovers an unreadable one."""
    return _save(path, empty_state(), "all faults cleared")
