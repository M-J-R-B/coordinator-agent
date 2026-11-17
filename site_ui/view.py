"""What the site control panel shows: the topology, as the agent's tools see it.

No Streamlit and no writes. Status comes from mcp_server.checks.check_device,
the same function behind the agent's check_device tool, so a device that is
slow past the poll deadline shows as unknown here too.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

from mcp_server.checks import check_device
from mock_site.devices import INVENTORY, PORT_COUNT, PORT_MAP, SITE_ID, port_label
from mock_site.poll import DEFAULT_LATENCY_MS
from mock_site.state import DEFAULT_STATE_PATH, load_state

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
    """The panel must be instant; check_device's deadline still applies."""


def _read(path: Path) -> tuple[dict | None, str | None]:
    try:
        state = load_state(path)
    except (OSError, ValueError) as exc:   # JSONDecodeError is a ValueError
        return None, f"cannot read {path}: {exc}"
    if not isinstance(state, dict) or not isinstance(state.get("faults"), list):
        return None, f"cannot read {path}: no 'faults' list"
    return state, None


def _describe(fault: dict) -> str:
    return f"slow {fault['ms']}ms" if fault["type"] == "slow" else fault["type"]


def _down_ports(switch_id: str, faults: list[dict]) -> list[int]:
    return sorted(f["port"] for f in faults
                  if f["type"] == "port_down" and f["device"] == switch_id)


def _cause(device_id: str, check, faults: list[dict]) -> str:
    if check.status == "unknown":
        return check.message
    parts = [_describe(f) for f in faults
             if f["device"] == device_id and f["type"] != "port_down"]
    down = _down_ports(device_id, faults)
    if down:
        parts.append("ports down: " + ", ".join(map(str, down)))
    if device_id in PORT_MAP:
        switch_id, port = PORT_MAP[device_id]
        if port in _down_ports(switch_id, faults):
            parts.append(f"via {switch_id} port {port} down")
        parts += [f"switch {switch_id} {_describe(f)}" for f in faults
                  if f["device"] == switch_id and f["type"] in ("offline", "slow")]
    return ", ".join(parts)


def _device(device_id: str, path: Path, faults: list[dict]) -> DeviceView:
    check = check_device(device_id, path, sleep=_no_sleep)
    return DeviceView(
        device_id=device_id,
        type=INVENTORY[device_id].type,
        switch_id=PORT_MAP.get(device_id, (None, None))[0],
        status=check.status,
        latency_ms=getattr(check, "latency_ms", None),
        cause=_cause(device_id, check, faults),
        faults=[f for f in faults if f["device"] == device_id],
    )


def _ports(switch_id: str, faults: list[dict]) -> list[PortView]:
    down = set(_down_ports(switch_id, faults))
    return [PortView(port=p, cabled_to=port_label(switch_id, p), down=p in down)
            for p in range(1, PORT_COUNT + 1)]


def site_model(path: Path) -> SiteModel:
    state, error = _read(Path(path))
    if error:
        return SiteModel(site=SITE_ID, error=error)
    faults = state["faults"]
    return SiteModel(
        site=state.get("site", SITE_ID),
        devices={d: _device(d, Path(path), faults) for d in INVENTORY},
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
