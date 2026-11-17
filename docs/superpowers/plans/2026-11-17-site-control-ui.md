# Site Control UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Streamlit control panel (`site_ui/`) that draws STORE-001 as switch → port → device and injects/clears faults with buttons, showing each device's status exactly as the agent's `check_device` tool would.

**Architecture:** Three small modules. `site_ui/view.py` (pure, no Streamlit) turns the state file into a `SiteModel` by calling `mcp_server.checks.check_device` per device. `site_ui/actions.py` is the only writer: re-read state → one `mock_site.faults` function → atomic `save_state`. `site_ui/app.py` only draws and wires buttons to actions. AST tests enforce that `ui/` (the read-only dashboard) never imports `site_ui`, and that inside `site_ui/` only `actions.py` imports the writers.

**Tech Stack:** Python 3.10+ (UI itself 3.11+ via the existing `[ui]` extra), Streamlit ≥ 1.67 (`st.fragment(run_every=…)`, `AppTest`), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-17-site-control-ui-design.md`

**Conventions for every task**
- Run tests from the repo root: `C:\Users\MJ\precheck-agent`.
- Commit from **bash** with `git commit -q -F - <<'EOF' … EOF` (never PowerShell `Out-File`: it adds a BOM). Every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Do not push until Task 8.

## File map

| File | Status | Responsibility |
|---|---|---|
| `mock_site/faults.py` | modify | add `clear_port`; share switch/port validation with `inject_port_down` |
| `site_ui/__init__.py` | create | package marker |
| `site_ui/view.py` | create | state file → `SiteModel`; labels/dots; no Streamlit, no writes |
| `site_ui/actions.py` | create | the only writes; returns `ActionResult` |
| `site_ui/app.py` | create | Streamlit drawing + button wiring |
| `tests/test_faults.py` | modify | `clear_port` tests |
| `tests/test_site_view.py` | create | model + label tests (runs on 3.10) |
| `tests/test_site_actions.py` | create | action tests against temp state files |
| `tests/test_site_agreement.py` | create | actions → real tool read path, same file |
| `tests/test_ui_readonly.py` | modify | expose reusable scanners; forbid `ui/` → `site_ui` imports |
| `tests/test_site_ui_writes.py` | create | only `actions.py` imports writers; no direct file writes |
| `tests/test_site_app.py` | create | `AppTest` end-to-end clicks (skipped without Streamlit) |
| `pyproject.toml` | modify | add `site_ui` package |
| `CLAUDE.md` | modify | stack, structure, commands, build order |

---

### Task 1: `faults.clear_port`

**Files:**
- Modify: `mock_site/faults.py` (the `inject_port_down` function, ~lines 37-44)
- Test: `tests/test_faults.py` (append)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_faults.py`:

```python
def test_clear_port_removes_only_that_port():
    state = faults.inject_port_down(empty_state(), "SW-01", 3)
    state = faults.inject_port_down(state, "SW-01", 4)
    state = faults.inject_slow(state, "SW-01", 800)
    state = faults.clear_port(state, "SW-01", 3)
    assert state["faults"] == [
        {"type": "port_down", "device": "SW-01", "port": 4},
        {"type": "slow", "device": "SW-01", "ms": 800},
    ]


def test_clear_port_on_up_port_is_noop():
    state = faults.inject_offline(empty_state(), "SW-02")
    assert faults.clear_port(state, "SW-02", 5)["faults"] == state["faults"]


def test_clear_port_rejects_non_switch():
    with pytest.raises(ValueError):
        faults.clear_port(empty_state(), "CAM-01", 3)


def test_clear_port_rejects_unknown_device():
    with pytest.raises(ValueError):
        faults.clear_port(empty_state(), "SW-09", 3)


@pytest.mark.parametrize("port", [0, 25])
def test_clear_port_rejects_bad_port(port):
    with pytest.raises(ValueError):
        faults.clear_port(empty_state(), "SW-01", port)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_faults.py -q -k clear_port`
Expected: 6 FAILED with `AttributeError: module 'mock_site.faults' has no attribute 'clear_port'`

- [ ] **Step 3: Implement** — in `mock_site/faults.py` replace `inject_port_down` with:

```python
def _require_switch_port(switch_id: str, port: int) -> None:
    _require_device(switch_id)
    if INVENTORY[switch_id].type != "switch":
        raise ValueError(f"{switch_id} is not a switch")
    if not 1 <= port <= PORT_COUNT:
        raise ValueError(f"port must be 1-{PORT_COUNT}, got {port}")


def inject_port_down(state: dict, switch_id: str, port: int) -> dict:
    _require_switch_port(switch_id, port)
    return _add(state, {"type": "port_down", "device": switch_id, "port": port})


def clear_port(state: dict, switch_id: str, port: int) -> dict:
    """Plug the cable back in: remove only this port_down, keep the switch's condition."""
    _require_switch_port(switch_id, port)
    target = {"type": "port_down", "device": switch_id, "port": port}
    return {**state, "faults": [f for f in state["faults"] if f != target]}
```

- [ ] **Step 4: Run to verify they pass (and nothing else broke)**

Run: `python -m pytest tests/test_faults.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add mock_site/faults.py tests/test_faults.py
git commit -q -F - <<'EOF'
Add faults.clear_port to bring one switch port back up

clear_device on a switch also clears its condition; the control panel
needs to plug one cable back in without touching anything else.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: `site_ui/view.py` — the site model

**Files:**
- Create: `site_ui/__init__.py` (empty)
- Create: `site_ui/view.py`
- Test: `tests/test_site_view.py`

Background for the implementer: `mcp_server.checks.check_device(device_id, state_path, sleep=...)` returns either a `DeviceCheck` (`status` `"online"`/`"offline"`, `latency_ms`) or a `ToolFailure` (`status` `"unknown"`, `message`). It enforces a 2000 ms deadline through the `sleep` it is given, so passing a no-op sleep is instant but a slow-5000 device still times out → `unknown`. That is the whole point: the panel shows what the agent will see.

- [ ] **Step 1: Write the failing tests** — create `tests/test_site_view.py`:

```python
"""site_ui.view: the topology model, as the agent's check_device tool sees it."""
from mock_site import faults
from mock_site.state import empty_state, save_state
from site_ui import view


def model_for(tmp_path, *changes):
    state = empty_state()
    for change in changes:
        state = change(state)
    path = tmp_path / "site_state.json"
    save_state(path, state)
    return view.site_model(path)


def test_healthy_site_is_all_online(tmp_path):
    m = model_for(tmp_path)
    assert m.error is None
    assert {d.status for d in m.devices.values()} == {"online"}
    assert m.counts == {"online": 14, "slow": 0, "offline": 0, "unknown": 0}


def test_missing_file_is_a_healthy_site(tmp_path):
    m = view.site_model(tmp_path / "missing.json")
    assert m.error is None
    assert m.counts["online"] == 14


def test_port_down_takes_its_camera_offline_with_cause(tmp_path):
    m = model_for(tmp_path, lambda s: faults.inject_port_down(s, "SW-01", 3))
    cam = m.devices["CAM-03"]
    assert cam.status == "offline"
    assert cam.cause == "via SW-01 port 3 down"
    assert m.ports["SW-01"][2] == view.PortView(port=3, cabled_to="CAM-03", down=True)
    assert m.devices["SW-01"].status == "online"
    assert m.devices["SW-01"].cause == "ports down: 3"


def test_slow_past_the_poll_deadline_is_unknown(tmp_path):
    m = model_for(tmp_path, lambda s: faults.inject_slow(s, "CAM-06", 5000))
    cam = m.devices["CAM-06"]
    assert cam.status == "unknown"
    assert cam.latency_ms is None
    assert "timed out" in cam.cause


def test_slow_within_the_deadline_is_online_and_slow(tmp_path):
    m = model_for(tmp_path, lambda s: faults.inject_slow(s, "CAM-06", 800))
    cam = m.devices["CAM-06"]
    assert (cam.status, cam.slow, cam.latency_ms, cam.cause) == ("online", True, 800, "slow 800ms")
    assert m.counts == {"online": 13, "slow": 1, "offline": 0, "unknown": 0}


def test_slow_switch_slows_its_devices_only(tmp_path):
    m = model_for(tmp_path, lambda s: faults.inject_slow(s, "SW-01", 800))
    cam = m.devices["CAM-01"]
    assert (cam.latency_ms, cam.slow, cam.cause) == (805, True, "switch SW-01 slow 800ms")
    pos = m.devices["POS-01"]
    assert (pos.latency_ms, pos.slow) == (5, False)


def test_offline_switch_takes_its_devices_offline(tmp_path):
    m = model_for(tmp_path, lambda s: faults.inject_offline(s, "SW-01"))
    assert m.devices["CAM-01"].status == "offline"
    assert m.devices["CAM-01"].cause == "switch SW-01 offline"


def test_timeout_is_unknown(tmp_path):
    m = model_for(tmp_path, lambda s: faults.inject_timeout(s, "POS-02"))
    assert m.devices["POS-02"].status == "unknown"


def test_ports_show_cabling(tmp_path):
    m = model_for(tmp_path)
    assert [p.cabled_to for p in m.ports["SW-01"][:9]] == [f"CAM-0{i}" for i in range(1, 9)] + [None]
    assert m.ports["SW-02"][3].cabled_to == "POS-04"
    assert m.ports["SW-02"][4].cabled_to is None
    assert len(m.ports["SW-01"]) == 24


def test_unreadable_file_sets_error(tmp_path):
    path = tmp_path / "site_state.json"
    path.write_text("{not json", encoding="utf-8")
    m = view.site_model(path)
    assert m.error and "site_state.json" in m.error
    assert m.devices == {}
    assert m.counts == {"online": 0, "slow": 0, "offline": 0, "unknown": 0}


def test_wrong_shape_sets_error(tmp_path):
    path = tmp_path / "site_state.json"
    path.write_text('{"site": "STORE-001"}', encoding="utf-8")
    assert view.site_model(path).error


def test_state_path_follows_env(tmp_path, monkeypatch):
    monkeypatch.setenv(view.STATE_ENV, str(tmp_path / "x.json"))
    assert view.state_path() == tmp_path / "x.json"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_site_view.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'site_ui'`

- [ ] **Step 3: Implement** — create empty `site_ui/__init__.py`, then `site_ui/view.py`:

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_site_view.py -q`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add site_ui/__init__.py site_ui/view.py tests/test_site_view.py
git commit -q -F - <<'EOF'
Add site_ui.view: mock site topology as the agent's tools see it

Status per device comes from mcp_server.checks.check_device, so a device
slow past the poll deadline shows as unknown, matching the agent.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: labels (dots and text) in `view.py`

**Files:**
- Modify: `site_ui/view.py` (append)
- Test: `tests/test_site_view.py` (append)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_site_view.py`:

```python
def faulty(tmp_path):
    return model_for(
        tmp_path,
        lambda s: faults.inject_port_down(s, "SW-01", 3),
        lambda s: faults.inject_slow(s, "CAM-06", 800),
        lambda s: faults.inject_timeout(s, "POS-02"),
    )


def test_device_labels(tmp_path):
    m = faulty(tmp_path)
    assert view.device_label(m.devices["CAM-01"]) == "🟢 CAM-01"
    assert view.device_label(m.devices["CAM-03"]) == "🔴 CAM-03"
    assert view.device_label(m.devices["CAM-06"]) == "🟡 CAM-06 800ms"
    assert view.device_label(m.devices["POS-02"]) == "⚪ POS-02 unknown"


def test_port_text(tmp_path):
    ports = faulty(tmp_path).ports["SW-01"]
    assert [view.port_text(ports[i]) for i in (0, 2, 8)] == ["🟢1", "🔴3", "▫️9"]


def test_fault_text():
    assert view.fault_text({"type": "port_down", "device": "SW-01", "port": 3}) == "port_down SW-01 port 3"
    assert view.fault_text({"type": "slow", "device": "CAM-06", "ms": 800}) == "slow CAM-06 800ms"
    assert view.fault_text({"type": "offline", "device": "CAM-03"}) == "offline CAM-03"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_site_view.py -q -k "label or text"`
Expected: 3 FAILED with `AttributeError: module 'site_ui.view' has no attribute ...`

- [ ] **Step 3: Implement** — append to `site_ui/view.py`:

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_site_view.py -q`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add site_ui/view.py tests/test_site_view.py
git commit -q -F - <<'EOF'
Add status dots and labels for the site control panel

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: `site_ui/actions.py` — the only writes

**Files:**
- Create: `site_ui/actions.py`
- Test: `tests/test_site_actions.py`

- [ ] **Step 1: Write the failing tests** — create `tests/test_site_actions.py`:

```python
"""site_ui.actions: every change goes load -> one faults.* call -> atomic save."""
import pytest

from mock_site.state import empty_state, load_state
from site_ui import actions


@pytest.fixture
def path(tmp_path):
    return tmp_path / "site_state.json"


def faults_in(path):
    return load_state(path)["faults"]


def test_inject_offline_writes_the_file(path):
    result = actions.inject(path, "offline", "CAM-01")
    assert result.ok and "CAM-01" in result.message
    assert faults_in(path) == [{"type": "offline", "device": "CAM-01"}]


def test_inject_timeout(path):
    assert actions.inject(path, "timeout", "POS-02").ok
    assert faults_in(path) == [{"type": "timeout", "device": "POS-02"}]


def test_inject_slow(path):
    assert actions.inject(path, "slow", "CAM-06", ms=800).ok
    assert faults_in(path) == [{"type": "slow", "device": "CAM-06", "ms": 800}]


def test_port_down_then_up(path):
    result = actions.inject(path, "port_down", "SW-01", port=3)
    assert result.ok and "SW-01 port 3" in result.message
    assert faults_in(path) == [{"type": "port_down", "device": "SW-01", "port": 3}]
    assert actions.bring_port_up(path, "SW-01", 3).ok
    assert faults_in(path) == []


def test_bring_port_up_keeps_the_switch_condition(path):
    actions.inject(path, "slow", "SW-01", ms=800)
    actions.inject(path, "port_down", "SW-01", port=3)
    actions.inject(path, "port_down", "SW-01", port=4)
    actions.bring_port_up(path, "SW-01", 3)
    assert faults_in(path) == [{"type": "slow", "device": "SW-01", "ms": 800},
                               {"type": "port_down", "device": "SW-01", "port": 4}]


def test_clear_device(path):
    actions.inject(path, "offline", "CAM-01")
    actions.inject(path, "offline", "CAM-02")
    assert actions.clear_device(path, "CAM-01").ok
    assert faults_in(path) == [{"type": "offline", "device": "CAM-02"}]


@pytest.mark.parametrize("kind, device, kw", [
    ("offline", "CAM-99", {}),
    ("port_down", "CAM-01", {"port": 3}),
    ("port_down", "SW-01", {"port": 25}),
    ("port_down", "SW-01", {}),
    ("slow", "CAM-01", {"ms": 0}),
    ("slow", "CAM-01", {}),
    ("melt", "CAM-01", {}),
])
def test_bad_input_changes_nothing(path, kind, device, kw):
    actions.inject(path, "offline", "CAM-02")
    before = path.read_bytes()
    result = actions.inject(path, kind, device, **kw)
    assert not result.ok and result.message
    assert path.read_bytes() == before


def test_bad_input_on_missing_file_creates_nothing(path):
    assert not actions.inject(path, "offline", "CAM-99").ok
    assert not path.exists()


def test_bad_port_up_changes_nothing(path):
    assert not actions.bring_port_up(path, "CAM-01", 3).ok
    assert not path.exists()


def test_unreadable_file_blocks_actions(path):
    path.write_text("{not json", encoding="utf-8")
    result = actions.inject(path, "offline", "CAM-01")
    assert not result.ok and "Reset" in result.message
    assert path.read_text(encoding="utf-8") == "{not json"


def test_reset_overwrites_an_unreadable_file(path):
    path.write_text("{not json", encoding="utf-8")
    assert actions.reset(path).ok
    assert load_state(path) == empty_state()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_site_actions.py -q`
Expected: collection error `ImportError: cannot import name 'actions' from 'site_ui'`

- [ ] **Step 3: Implement** — create `site_ui/actions.py`:

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_site_actions.py -q`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add site_ui/actions.py tests/test_site_actions.py
git commit -q -F - <<'EOF'
Add site_ui.actions: the only writes from the site control panel

Re-read at click time, one mock_site.faults call, atomic save. Bad input
or an unreadable file writes nothing; reset recovers an unreadable file.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: agreement test — panel writes what the agent's tool reads

**Files:**
- Test: `tests/test_site_agreement.py`

This test needs no new code; it proves the wiring: the panel and the MCP server resolve the **same** state file, and faults written by `actions` are what the real `check_device` reads.

- [ ] **Step 1: Write the test** — create `tests/test_site_agreement.py`:

```python
"""The panel writes the file the agent's tool reads, and shows what that tool returns."""
from mcp_server.checks import check_device
from mcp_server.server import _state_path
from mock_site.devices import INVENTORY
from site_ui import actions, view


def no_sleep(_seconds):
    pass


def test_panel_and_mcp_server_use_the_same_state_file(tmp_path, monkeypatch):
    monkeypatch.setenv(view.STATE_ENV, str(tmp_path / "site_state.json"))
    assert view.state_path() == _state_path(None)
    monkeypatch.delenv(view.STATE_ENV)
    assert view.state_path() == _state_path(None)


def test_panel_shows_what_the_tool_returns(tmp_path):
    path = tmp_path / "site_state.json"
    for result in (actions.inject(path, "port_down", "SW-01", port=3),
                   actions.inject(path, "slow", "CAM-06", ms=5000),
                   actions.inject(path, "slow", "SW-02", ms=300),
                   actions.inject(path, "timeout", "POS-04"),
                   actions.inject(path, "offline", "CAM-08")):
        assert result.ok, result.message
    model = view.site_model(path)
    for device_id in INVENTORY:
        tool = check_device(device_id, path, sleep=no_sleep)
        shown = model.devices[device_id]
        assert shown.status == tool.status, device_id
        assert shown.latency_ms == getattr(tool, "latency_ms", None), device_id
    statuses = {d: model.devices[d].display for d in ("CAM-03", "CAM-06", "POS-01", "POS-04", "CAM-08")}
    assert statuses == {"CAM-03": "offline", "CAM-06": "unknown", "POS-01": "slow",
                        "POS-04": "unknown", "CAM-08": "offline"}
```

- [ ] **Step 2: Run**

Run: `python -m pytest tests/test_site_agreement.py -q`
Expected: 2 passed. (If it fails, the bug is in Task 2 or 4 — fix there, not here.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_site_agreement.py
git commit -q -F - <<'EOF'
Test that the site panel and the agent's tool share one state file

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: AST guards

**Files:**
- Modify: `tests/test_ui_readonly.py` (whole file shown below)
- Create: `tests/test_site_ui_writes.py`

- [ ] **Step 1: Refactor `tests/test_ui_readonly.py`** into reusable scanners and add the `site_ui` import ban. Replace the whole file with:

```python
"""The report UI is read-only: enforce it on the source, not just by convention.

Fails if anything in ui/ imports a module or name that changes state (runs a
check, injects a fault, saves a baseline/report/state), imports the site
control panel, or calls a writing file API. The scanners are reused by
tests/test_site_ui_writes.py.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
UI_DIR = REPO / "ui"

FORBIDDEN_MODULES = {"agent.run", "agent.baseline", "agent.report", "agent.decision",
                     "agent.hooks", "mock_site.faults", "mock_site.state",
                     "mock_site.__main__", "mcp_server.server", "subprocess", "shutil"}
FORBIDDEN_NAMES = {"write_json_atomic", "save_state", "save_baseline", "save_report",
                   "finalize", "run_check", "EventLog"}
# Path / file-object methods that change the filesystem.
WRITING_METHODS = {"write_text", "write_bytes", "unlink", "mkdir", "rename", "rmdir",
                   "touch", "symlink_to", "hardlink_to", "chmod"}
# os.<name>(...) calls that change the filesystem.
WRITING_OS = {"replace", "remove", "rename", "unlink", "makedirs", "mkdir", "rmdir",
              "removedirs", "truncate"}


def writes(func: ast.Attribute, call: ast.Call) -> bool:
    if isinstance(func.value, ast.Name) and func.value.id == "os":
        return func.attr in WRITING_OS
    if func.attr == "replace":
        # Path.replace(target) takes one argument; str.replace(old, new) takes two.
        return len(call.args) == 1
    return func.attr in WRITING_METHODS


def _opens_for_writing(call: ast.Call) -> bool:
    modes = [a.value for a in call.args[1:2] if isinstance(a, ast.Constant)]
    modes += [k.value.value for k in call.keywords
              if k.arg == "mode" and isinstance(k.value, ast.Constant)]
    return not all(set(str(m)) <= set("rbt") for m in modes)


def write_calls(tree: ast.AST) -> list[str]:
    """Every call in the tree that writes to the filesystem, as 'line: what'."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and writes(func, node):
            found.append(f"{node.lineno}: .{func.attr}()")
        if isinstance(func, ast.Name) and func.id == "open" and _opens_for_writing(node):
            found.append(f"{node.lineno}: open() for writing")
    return found


def imported_modules(tree: ast.AST) -> list[str]:
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return mods


def sources(directory: Path = UI_DIR):
    files = sorted(directory.glob("*.py"))
    assert files, f"{directory.name}/ has no Python files"
    return [(f, ast.parse(f.read_text(encoding="utf-8"))) for f in files]


def test_no_state_changing_imports():
    for path, tree in sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                bad = [a.name for a in node.names if a.name in FORBIDDEN_MODULES]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                bad = [module] if module in FORBIDDEN_MODULES else []
                bad += [a.name for a in node.names if a.name in FORBIDDEN_NAMES]
            else:
                continue
            assert not bad, f"{path.name}:{node.lineno} imports {bad}"


def test_ui_does_not_import_the_site_control_panel():
    for path, tree in sources():
        bad = [m for m in imported_modules(tree) if m == "site_ui" or m.startswith("site_ui.")]
        assert not bad, f"{path.name} imports {bad}"


def test_no_file_writes():
    for path, tree in sources():
        found = write_calls(tree)
        assert not found, f"{path.name}: {found}"


def test_scanner_catches_writes_and_ignores_string_replace():
    """The scanner itself: flags real writes, not str.replace."""
    def flagged(src: str) -> bool:
        return bool(write_calls(ast.parse(src)))
    assert flagged("p.write_text('x')")
    assert flagged("os.replace(a, b)")
    assert flagged("p.replace(target)")
    assert flagged("p.mkdir()")
    assert flagged("open(p, 'w')")
    assert flagged("open(p, mode='a')")
    assert not flagged("s.replace('T', ' ')")
    assert not flagged("p.read_text()")
    assert not flagged("open(p, 'rb')")
```

- [ ] **Step 2: Run to verify the refactor kept it green**

Run: `python -m pytest tests/test_ui_readonly.py -q`
Expected: 4 passed

- [ ] **Step 3: Write the `site_ui` guard** — create `tests/test_site_ui_writes.py`:

```python
"""site_ui/ changes the site only through actions.py, and never writes files directly.

app.py and view.py may read (load_state, check_device) but may not import
mock_site.faults or save_state. actions.py writes only via save_state.
"""
import ast

from tests.test_ui_readonly import REPO, sources, write_calls

SITE_UI = REPO / "site_ui"


def writer_imports(tree: ast.AST) -> list[str]:
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name == "mock_site.faults"]
        elif isinstance(node, ast.ImportFrom):
            names = {a.name for a in node.names}
            if node.module == "mock_site.faults" or (node.module == "mock_site" and "faults" in names):
                bad.append("mock_site.faults")
            if "save_state" in names:
                bad.append("save_state")
    return bad


def test_only_actions_imports_state_writers():
    for path, tree in sources(SITE_UI):
        if path.name != "actions.py":
            assert not writer_imports(tree), f"{path.name} imports {writer_imports(tree)}"


def test_guard_sees_the_writers_in_actions():
    """Self-test: if this fails the guard above is blind, not the code clean."""
    tree = dict(sources(SITE_UI))[SITE_UI / "actions.py"]
    assert set(writer_imports(tree)) == {"mock_site.faults", "save_state"}


def test_site_ui_never_writes_files_directly():
    for path, tree in sources(SITE_UI):
        found = write_calls(tree)
        assert not found, f"{path.name}: {found}"
```

- [ ] **Step 4: Run**

Run: `python -m pytest tests/test_ui_readonly.py tests/test_site_ui_writes.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add tests/test_ui_readonly.py tests/test_site_ui_writes.py
git commit -q -F - <<'EOF'
Guard the UI split with AST tests

ui/ may not import site_ui; inside site_ui only actions.py imports
mock_site.faults or save_state, and nothing writes files directly.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 7: `site_ui/app.py` — the Streamlit panel

**Files:**
- Create: `site_ui/app.py`
- Test: `tests/test_site_app.py`

Streamlit notes (verified on 1.67 with `AppTest`): buttons inside `@st.fragment(run_every=…)` can be clicked in `AppTest`; `at.button(key=…)`, `.label`, `.disabled`, `b.key` all work; an `on_click` callback can read `st.session_state["slow-ms"]` and set `st.session_state["reset-confirm"] = False`. All writes happen in `on_click` callbacks, which run *before* the rerun, so the redraw already shows the new state.

Widget keys (tests depend on these): `dev-<ID>`, `port-<SW>-<n>`, `act-port-down`, `act-port-up`, `act-offline`, `act-timeout`, `slow-ms`, `act-slow`, `act-clear`, `reset-confirm`, `reset`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_site_app.py`:

```python
"""The site control panel, run headless with AppTest. Skipped without Streamlit."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from mock_site.state import empty_state, load_state  # noqa: E402
from site_ui import actions, view  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "site_ui" / "app.py")


@pytest.fixture
def state(tmp_path, monkeypatch):
    path = tmp_path / "site_state.json"
    monkeypatch.setenv(view.STATE_ENV, str(path))
    return path


def run_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception, at.exception
    return at


def click(at, key) -> AppTest:
    at.button(key=key).click().run()
    assert not at.exception, at.exception
    return at


def test_draws_the_topology(state):
    at = run_app()
    keys = {b.key for b in at.button}
    assert {"dev-SW-01", "dev-SW-02", "dev-CAM-08", "dev-POS-04",
            "port-SW-01-1", "port-SW-02-24"} <= keys
    assert at.button(key="dev-CAM-01").label == "🟢 CAM-01"


def test_take_port_down_turns_its_camera_red(state):
    at = click(run_app(), "port-SW-01-3")
    click(at, "act-port-down")
    assert at.button(key="dev-CAM-03").label == "🔴 CAM-03"
    assert at.button(key="port-SW-01-3").label == "🔴3"
    assert load_state(state)["faults"] == [{"type": "port_down", "device": "SW-01", "port": 3}]


def test_bring_port_up(state):
    actions.inject(state, "port_down", "SW-01", port=3)
    at = click(run_app(), "port-SW-01-3")
    click(at, "act-port-up")
    assert load_state(state)["faults"] == []
    assert at.button(key="dev-CAM-03").label == "🟢 CAM-03"


def test_set_slow_uses_the_ms_input(state):
    at = click(run_app(), "dev-CAM-06")
    at.number_input(key="slow-ms").set_value(5000).run()
    click(at, "act-slow")
    assert load_state(state)["faults"] == [{"type": "slow", "device": "CAM-06", "ms": 5000}]
    assert at.button(key="dev-CAM-06").label == "⚪ CAM-06 unknown"   # past the 2000ms deadline


def test_offline_then_clear(state):
    at = click(run_app(), "dev-POS-02")
    click(at, "act-offline")
    assert at.button(key="dev-POS-02").label == "🔴 POS-02"
    click(at, "act-clear")
    assert load_state(state)["faults"] == []


def test_reset_needs_confirmation(state):
    actions.inject(state, "offline", "CAM-01")
    at = run_app()
    assert at.button(key="reset").disabled
    at.checkbox(key="reset-confirm").check().run()
    click(at, "reset")
    assert load_state(state)["faults"] == []
    assert at.checkbox(key="reset-confirm").value is False


def test_unreadable_file_hides_fault_controls_and_offers_overwrite(state):
    state.write_text("{not json", encoding="utf-8")
    at = run_app()
    assert at.error
    keys = {b.key for b in at.button}
    assert not [k for k in keys if k.startswith(("act-", "port-", "dev-"))]
    assert at.button(key="reset").label == "Overwrite unreadable file with a healthy site"
    at.checkbox(key="reset-confirm").check().run()
    click(at, "reset")
    assert load_state(state) == empty_state()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_site_app.py -q`
Expected: 7 FAILED/errors (app file does not exist). On Python 3.10 without Streamlit: 1 skipped — run this task on 3.11+.

- [ ] **Step 3: Implement** — create `site_ui/app.py`:

```python
"""Site control panel for STORE-001: inject and clear faults on the mock site.

Run:   python -m streamlit run site_ui/app.py --server.address localhost --server.port 8502
State: $PRECHECK_STATE_PATH, default <repo>/data/site_state.json (the file the agent polls).
Every write goes through site_ui.actions, inside on_click callbacks.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # `streamlit run` puts site_ui/ first

import streamlit as st  # noqa: E402

from site_ui import actions, view  # noqa: E402

REFRESH_SECONDS = 2


# ---- callbacks (run before the rerun, so the redraw shows the new state) ----

def _select(selection: tuple) -> None:
    st.session_state["sel"] = selection


def _run(action, *args, **kwargs) -> None:
    st.session_state["last"] = action(view.state_path(), *args, **kwargs)


def _slow(device_id: str) -> None:
    _run(actions.inject, "slow", device_id, ms=int(st.session_state["slow-ms"]))


def _reset() -> None:
    _run(actions.reset)
    st.session_state["reset-confirm"] = False


# ---- drawing ----

def header(model: view.SiteModel) -> None:
    c = model.counts
    st.title(f"{model.site} site control")
    st.caption(f"🟢 {c['online']}  🟡 {c['slow']}  🔴 {c['offline']}  ⚪ {c['unknown']}"
               f" · {len(model.faults)} active faults · state: {view.state_path()}"
               f" · refresh {REFRESH_SECONDS}s")


def device_button(where, d: view.DeviceView) -> None:
    where.button(view.device_label(d), key=f"dev-{d.device_id}",
                 on_click=_select, args=(("device", d.device_id),))


def switch_block(model: view.SiteModel, switch_id: str) -> None:
    device_button(st, model.devices[switch_id])
    ports = model.ports[switch_id]
    for row in (ports[:12], ports[12:]):
        for col, p in zip(st.columns(12), row):
            col.button(view.port_text(p), key=f"port-{switch_id}-{p.port}",
                       on_click=_select, args=(("port", switch_id, p.port),))
    attached = [d for d in model.devices.values() if d.switch_id == switch_id]
    for col, d in zip(st.columns(len(attached)), attached):
        device_button(col, d)


def port_panel(model: view.SiteModel, switch_id: str, port: int) -> None:
    p = model.ports[switch_id][port - 1]
    st.subheader(f"{switch_id} · port {port}")
    st.write(f"Cabled to: {p.cabled_to or 'nothing'} · state: {'down' if p.down else 'up'}")
    if p.down:
        st.button("Bring port up", key="act-port-up",
                  on_click=_run, args=(actions.bring_port_up, switch_id, port))
    else:
        st.button("Take port down", key="act-port-down", on_click=_run,
                  args=(actions.inject, "port_down", switch_id), kwargs={"port": port})


def device_panel(model: view.SiteModel, device_id: str) -> None:
    d = model.devices[device_id]
    st.subheader(view.device_label(d))
    st.write(f"Status: {d.status}" + (f" · cause: {d.cause}" if d.cause else ""))
    left, right = st.columns(2)
    left.button("Offline", key="act-offline", on_click=_run,
                args=(actions.inject, "offline", device_id))
    right.button("Timeout", key="act-timeout", on_click=_run,
                 args=(actions.inject, "timeout", device_id))
    st.number_input("Slow (ms)", min_value=1, value=800, step=100, key="slow-ms")
    st.button("Set slow", key="act-slow", on_click=_slow, args=(device_id,))
    note = " (also brings its ports up)" if d.type == "switch" else ""
    st.button(f"Clear {device_id}{note}", key="act-clear", on_click=_run,
              args=(actions.clear_device, device_id))


def panel(model: view.SiteModel) -> None:
    selection = st.session_state.get("sel")
    if selection is None:
        st.info("Select a port or a device.")
    elif selection[0] == "port":
        port_panel(model, selection[1], selection[2])
    else:
        device_panel(model, selection[1])


def faults_box(model: view.SiteModel) -> None:
    st.markdown(f"**Active faults ({len(model.faults)})**")
    for f in model.faults:
        st.markdown(f"- {view.fault_text(f)}")


def last_result() -> None:
    last = st.session_state.get("last")
    if last:
        (st.success if last.ok else st.error)(last.message)


def reset_box(unreadable: bool) -> None:
    label = ("Overwrite unreadable file with a healthy site" if unreadable
             else "Reset all faults")
    confirmed = st.checkbox("Confirm reset", key="reset-confirm")
    st.button(label, key="reset", disabled=not confirmed, on_click=_reset)


@st.fragment(run_every=REFRESH_SECONDS)
def body() -> None:
    model = view.site_model(view.state_path())
    header(model)
    if model.error:
        st.error(model.error)
        last_result()
        reset_box(unreadable=True)
        return
    left, right = st.columns([3, 1])
    with left:
        for switch_id in view.SWITCHES:
            with st.container(border=True):
                switch_block(model, switch_id)
    with right:
        panel(model)
        last_result()
        faults_box(model)
        reset_box(unreadable=False)


st.set_page_config(page_title="Site control", layout="wide")
body()
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_site_app.py tests/test_site_ui_writes.py -q`
Expected: 10 passed (7 app + 3 guard, the guard now also scanning `app.py`)

- [ ] **Step 5: Commit**

```bash
git add site_ui/app.py tests/test_site_app.py
git commit -q -F - <<'EOF'
Add the site control panel Streamlit app

Topology of STORE-001 with per-port and per-device fault buttons, auto
refresh every 2s, confirmed reset, and recovery from an unreadable file.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 8: packaging, docs, full verification, push

**Files:**
- Modify: `pyproject.toml` (`[tool.setuptools] packages`)
- Modify: `CLAUDE.md` (Stack, Structure, Build order, Working style → Commands)
- Modify: `docs/superpowers/specs/2026-11-17-site-control-ui-design.md` (three wording fixes found while planning)

- [ ] **Step 1: `pyproject.toml`** — change the packages line to:

```toml
packages = ["mock_site", "mcp_server", "agent", "ui", "site_ui"]
```

- [ ] **Step 2: `CLAUDE.md`**
  - Stack: replace `- Streamlit for a read-only UI` with `- Streamlit for a read-only report UI and a mock-site control panel`
  - Structure: after the `mock_site/` line add `` - `site_ui/`    control panel for the mock site (only `actions.py` writes) ``
  - Build order, under Done, after `9. Read-only Streamlit UI` add `10. Mock-site control panel (site_ui)`
  - Commands: after the read-only UI command add
    `` `python -m streamlit run site_ui/app.py --server.address localhost --server.port 8502` for the mock-site control panel (also needs the `[ui]` extra). ``

- [ ] **Step 3: Spec wording fixes** (decided while planning; keep spec and code in agreement)
  - Unknown device label is `⚪ <ID> unknown` (the agent's word), not "timeout".
  - Unreadable state file: fault controls are **not drawn** (rather than drawn disabled); only Reset is shown.
  - Last action result is a persistent `st.success`/`st.error` under the panel; no `st.toast` (YAGNI).

- [ ] **Step 4: Full suite**

Run: `python -m pytest -q`
Expected: all passed, 2 skipped (the live model tests). Count ≈ 229 + 49 new.

- [ ] **Step 5: Manual smoke run on a scratch state file** (bash; does not touch `data/`)

```bash
S="$TEMP/site-ui-smoke.json"
PRECHECK_STATE_PATH="$S" python -m mock_site --state "$S" inject port-down SW-01 3
PRECHECK_STATE_PATH="$S" python -m streamlit run site_ui/app.py --server.address localhost \
  --server.port 8502 --server.headless true --browser.gatherUsageStats false
```
Run the second command with `run_in_background: true`, then:
`curl.exe -s http://127.0.0.1:8502/_stcore/health` → `ok`; confirm the log shows `localhost:8502` and **no** Network/External URL. Ask the user to look at http://localhost:8502 (CAM-03 should be 🔴), then stop the server.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml CLAUDE.md docs/superpowers/specs/2026-11-17-site-control-ui-design.md
git commit -q -F - <<'EOF'
Package site_ui and document the mock-site control panel

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git cat-file commit HEAD | sed -n '/^$/,$p' | sed -n 2p | od -c | head -1   # no BOM bytes
```

- [ ] **Step 7: Push and watch CI** (only after the user approves the push)

```bash
git push -q origin main
gh run watch "$(gh run list --branch main --limit 1 --json databaseId -q '.[0].databaseId')" --exit-status
```
Expected: `test (3.10)` green with `tests/test_site_app.py` skipped; `test (3.13)` green with it run.
