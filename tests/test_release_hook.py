"""The release hook, end to end: inject a fault, run the post-check, try to release.

Device results come from the real simulator, through the MCP server's own
check_device logic, so injected faults (and the port cascade) behave exactly
as in a live run. Only the model is scripted: after polling, it always tries
release_technician. The hook alone must stop it.
"""
import json
from pathlib import Path

import pytest

from agent.run import run_check
from mcp_server import checks
from mock_site import faults
from mock_site.devices import INVENTORY
from mock_site.state import empty_state, load_state, save_state
from tests.fakes import FakeQuery, release, script

RELEASE = "mcp__decision__release_technician"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def site(tmp_path):
    state = tmp_path / "state.json"
    save_state(state, empty_state())
    dirs = {"baseline_dir": tmp_path / "baselines", "reports_dir": tmp_path / "reports",
            "events_dir": tmp_path / "events", "state_path": state}
    return state, dirs


def inject(state: Path, fn, *args) -> None:
    save_state(state, fn(load_state(state), *args))


def poll_simulator(state: Path) -> dict[str, dict]:
    """What check_device returns for every device right now (no real sleeping)."""
    return {d: checks.check_device(d, state, sleep=lambda _s: None).model_dump()
            for d in INVENTORY}


async def precheck(state: Path, dirs: dict) -> None:
    report = await run_check("precheck", query_fn=FakeQuery(script(poll_simulator(state))), **dirs)
    assert report["baseline_saved"] is True


async def postcheck_trying_release(state: Path, dirs: dict) -> tuple[dict, FakeQuery]:
    fake = FakeQuery(script(poll_simulator(state), release("all looks fine to me")))
    return await run_check("postcheck", query_fn=fake, **dirs), fake


def gate_events(report: dict) -> list[dict]:
    lines = Path(report["event_log"]).read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, lines)
            if e["type"] == "hook_decision" and e["hook"] == "release_gate"]


def assert_blocked(report: dict, fake: FakeQuery, blocking: list[str]) -> None:
    # The hook denied the call, so the release tool never ran...
    assert "release_technician" not in fake.executed
    assert [tool for tool, _ in fake.denials] == [RELEASE]
    assert report["agent_decision"]["released"] is False
    # ...and it said why, naming the blocking devices.
    reason = report["agent_decision"]["release_denials"][0]
    assert all(device in reason for device in blocking)
    events = gate_events(report)
    assert [e["decision"] for e in events] == ["deny"]
    assert events[0]["blocking"] == blocking
    assert report["decision"] == "hold"


@pytest.mark.anyio
@pytest.mark.parametrize("fault, args, blocking, in_reason", [
    (faults.inject_port_down, ("SW-01", 3), ["CAM-03"], "CAM-03 new_offline (SW-01 port 3 down)"),
    (faults.inject_offline, ("POS-02",), ["POS-02"], "POS-02 new_offline"),
    # whole switch down: it and everything cabled to it (blocking is in inventory order)
    (faults.inject_offline, ("SW-02",), ["SW-02", "POS-01", "POS-02", "POS-03", "POS-04"],
     "SW-02 new_offline"),
    (faults.inject_timeout, ("CAM-01",), ["CAM-01"], "CAM-01 unknown"),
    (faults.inject_slow, ("POS-03", 3000), ["POS-03"], "POS-03 unknown"),  # over the 2s deadline
], ids=["port-down", "device-offline", "switch-offline", "timeout", "slow-over-deadline"])
async def test_hook_blocks_release_after_injected_fault(site, fault, args, blocking, in_reason):
    state, dirs = site
    await precheck(state, dirs)
    inject(state, fault, *args)          # the technician's work breaks something

    report, fake = await postcheck_trying_release(state, dirs)

    assert_blocked(report, fake, blocking)
    assert in_reason in report["agent_decision"]["release_denials"][0]


# --- controls: the hook must not block a release that is allowed ---

@pytest.mark.anyio
async def test_hook_allows_release_when_no_fault_injected(site):
    state, dirs = site
    await precheck(state, dirs)
    report, fake = await postcheck_trying_release(state, dirs)
    assert fake.executed == ["release_technician"]
    assert [e["decision"] for e in gate_events(report)] == ["allow"]
    assert report["decision"] == "release"


@pytest.mark.anyio
async def test_hook_allows_release_when_fault_was_pre_existing(site):
    state, dirs = site
    inject(state, faults.inject_offline, "CAM-05")   # broken before the tech arrived
    await precheck(state, dirs)
    report, fake = await postcheck_trying_release(state, dirs)
    assert fake.executed == ["release_technician"]
    assert report["decision"] == "release"
    cam5 = next(d for d in report["diff"]["devices"] if d["device_id"] == "CAM-05")
    assert cam5["classification"] == "pre-existing"


@pytest.mark.anyio
async def test_hook_allows_release_once_fault_is_fixed(site):
    state, dirs = site
    await precheck(state, dirs)
    inject(state, faults.inject_port_down, "SW-01", 3)
    blocked, _ = await postcheck_trying_release(state, dirs)
    assert blocked["decision"] == "hold"

    inject(state, faults.clear_device, "SW-01")       # tech plugs the cable back in
    report, fake = await postcheck_trying_release(state, dirs)
    assert fake.executed == ["release_technician"]
    assert report["decision"] == "release"
