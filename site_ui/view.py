"""What the site control panel shows: the topology, as the agent's tools see it.

No Streamlit and no writes. Status comes from mcp_server.checks.check_state (the
function behind the agent's check_device tool), so a device that is slow past
the poll deadline shows as unknown here too.

Ports show the cabling and injected port faults (what you control), even while
the switch itself is unreachable; device dots show what a poll returns.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

from mcp_server.checks import check_state
from mcp_server.models import DeviceCheck
from mock_site.devices import INVENTORY, PORT_COUNT, PORT_MAP, SITE_ID, port_label
from mock_site.poll import DEFAULT_LATENCY_MS
from mock_site.state import DEFAULT_STATE_PATH, load_state

FAULT_TYPES = {"offline", "timeout", "slow", "port_down"}
STATE_ENV = "PRECHECK_STATE_PATH"   # same variable the MCP server reads
SWITCHES = [d for d, dev in INVENTORY.items() if dev.type == "switch"]
DOTS = {"online": "🟢", "slow": "🟡", "offline": "🔴", "unknown": "⚪"}
EMPTY_PORT = "▫️"


@dataclass
class DeviceView:
    device_id: str
    type: str
    switch_id: str | None
    status: str                 # online | offline | unknown
    latency_ms: int | None
    cause: str
    faults: list[dict]

    @property
    def slow(self) -> bool:
        return self.status == "online" and (self.latency_ms or 0) > DEFAULT_LATENCY_MS

    @property
    def display(self) -> str:
        return "slow" if self.slow else self.status


@dataclass
class PortView:
    port: int
    cabled_to: str | None
    down: bool


@dataclass
class SiteModel:
    site: str
    devices: dict[str, DeviceView] = field(default_factory=dict)
    ports: dict[str, list[PortView]] = field(default_factory=dict)
    faults: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(DOTS, 0)
        for d in self.devices.values():
            counts[d.display] += 1
        return counts


def state_path() -> Path:
    return Path(os.environ.get(STATE_ENV, DEFAULT_STATE_PATH))


def _no_sleep(_seconds: float) -> None:
    """The panel must be instant; the tool's deadline still applies."""


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _valid_fault(f) -> bool:
    """Same limits the faults module enforces, so every listed fault can be cleared."""
    if not isinstance(f, dict) or f.get("type") not in FAULT_TYPES:
        return False
    # str check first: an unhashable value (e.g. a list) would crash the dict lookup
    if not isinstance(f.get("device"), str) or f["device"] not in INVENTORY:
        return False
    if f["type"] == "port_down":
        return _is_int(f.get("port")) and 1 <= f["port"] <= PORT_COUNT
    if f["type"] == "slow":
        return _is_int(f.get("ms")) and f["ms"] > 0
    return True


def read_state(path: Path) -> tuple[dict | None, str | None]:
    """Load and validate the state file; (state, None) or (None, error text)."""
    try:
        state = load_state(path)
    except (OSError, ValueError) as exc:   # JSONDecodeError is a ValueError
        return None, f"cannot read {path}: {exc}"
    if not isinstance(state, dict) or not isinstance(state.get("faults"), list):
        return None, f"cannot read {path}: no 'faults' list"
    for f in state["faults"]:
        if not _valid_fault(f):
            return None, f"cannot read {path}: bad fault entry {f!r}"
    return state, None


def _describe(fault: dict) -> str:
    return f"slow {fault['ms']}ms" if fault["type"] == "slow" else fault["type"]


def _down_ports(switch_id: str, faults: list[dict]) -> list[int]:
    return sorted(f["port"] for f in faults
                  if f["type"] == "port_down" and f["device"] == switch_id)


def _own_causes(device_id: str, faults: list[dict]) -> list[tuple[str, str]]:
    causes = [(f["type"], _describe(f)) for f in faults
              if f["device"] == device_id and f["type"] != "port_down"]
    down = _down_ports(device_id, faults)
    if down:
        causes.append(("port_down", "ports down: " + ", ".join(map(str, down))))
    return causes


def _upstream_causes(device_id: str, faults: list[dict]) -> list[tuple[str, str]]:
    if device_id not in PORT_MAP:
        return []
    switch_id, port = PORT_MAP[device_id]
    causes = ([("port_down", f"via {switch_id} port {port} down")]
              if port in _down_ports(switch_id, faults) else [])
    return causes + [(f["type"], f"switch {switch_id} {_describe(f)}") for f in faults
                     if f["device"] == switch_id and f["type"] in ("offline", "slow")]


def _cause(device_id: str, check, faults: list[dict]) -> str:
    """Why the device shows its status. Unknown keeps the upstream reason;
    offline drops slowness (a device that never answered has no latency)."""
    if check.status == "unknown":
        own = [c for c in _own_causes(device_id, faults) if c[0] == "slow"]
        extra = [text for _type, text in own + _upstream_causes(device_id, faults)]
        return ", ".join([check.message, *extra])
    causes = _own_causes(device_id, faults) + _upstream_causes(device_id, faults)
    if check.status == "offline":
        causes = [c for c in causes if c[0] != "slow"]
    return ", ".join(text for _type, text in causes)


def _device(device_id: str, state: dict) -> DeviceView:
    faults = state["faults"]
    check = check_state(device_id, state, sleep=_no_sleep)
    return DeviceView(
        device_id=device_id,
        type=INVENTORY[device_id].type,
        switch_id=PORT_MAP.get(device_id, (None, None))[0],
        status=check.status,
        latency_ms=check.latency_ms if isinstance(check, DeviceCheck) else None,
        cause=_cause(device_id, check, faults),
        faults=[f for f in faults if f["device"] == device_id],
    )


def _ports(switch_id: str, faults: list[dict]) -> list[PortView]:
    down = set(_down_ports(switch_id, faults))
    return [PortView(port=p, cabled_to=port_label(switch_id, p), down=p in down)
            for p in range(1, PORT_COUNT + 1)]


def site_model(path: Path) -> SiteModel:
    state, error = read_state(Path(path))
    if error:
        return SiteModel(site=SITE_ID, error=error)
    faults = state["faults"]
    return SiteModel(
        site=state.get("site", SITE_ID),
        devices={d: _device(d, state) for d in INVENTORY},
        ports={sw: _ports(sw, faults) for sw in SWITCHES},
        faults=faults,
    )


def device_label(d: DeviceView) -> str:
    text = f"{DOTS[d.display]} {d.device_id}"
    if d.slow:
        text += f" {d.latency_ms}ms"
    if d.status == "unknown":
        text += " unknown"
    return text


def port_text(p: PortView) -> str:
    dot = DOTS["offline"] if p.down else DOTS["online"] if p.cabled_to else EMPTY_PORT
    return f"{dot}{p.port}"


def fault_text(f: dict) -> str:
    if f["type"] == "port_down":
        return f"port_down {f['device']} port {f['port']}"
    if f["type"] == "slow":
        return f"slow {f['device']} {f['ms']}ms"
    return f"{f['type']} {f['device']}"
