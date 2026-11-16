import json

import pytest

from agent.events import EventLog
from agent.hooks import Gate, make_coordinator_guard, make_record_hooks, make_release_gate
from agent.recorder import Recorder
from tests.fakes import failure, healthy_site, offline, online


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def log():
    return EventLog(None, "c1")


def decisions(log):
    return [e for e in log.events if e["type"] == "hook_decision"]


def check_input(device_id, agent_id="id-cctv", **extra):
    data = {"tool_name": "mcp__devices__check_device", "tool_input": {"device_id": device_id},
            "tool_use_id": "t1", **extra}
    if agent_id:
        data["agent_id"] = agent_id
    return data


def denied(output) -> bool:
    return output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def fill(recorder, site):
    for device_id, payload in site.items():
        recorder.record(device_id, json.dumps(payload), is_error=payload["status"] == "unknown")


# --- recording ---

@pytest.mark.anyio
async def test_post_tool_use_records_success():
    r = Recorder()
    on_success, _ = make_record_hooks(r)
    out = await on_success(check_input("CAM-01", tool_response=json.dumps(online("CAM-01"))), "t1", None)
    assert out == {}
    assert r.results["CAM-01"]["status"] == "online"


@pytest.mark.anyio
async def test_post_tool_use_failure_records_unknown():
    r = Recorder()
    _, on_failure = make_record_hooks(r)
    await on_failure(check_input("CAM-02", error=json.dumps(failure("CAM-02"))), "t1", None)
    assert r.results["CAM-02"]["error_category"] == "timeout"


# --- coordinator must delegate ---

@pytest.mark.anyio
async def test_subagent_may_call_device_tools(log):
    assert await make_coordinator_guard(log)(check_input("CAM-01"), "t1", None) == {}
    assert decisions(log)[0]["decision"] == "allow"


@pytest.mark.anyio
async def test_coordinator_cannot_call_device_tools_directly(log):
    out = await make_coordinator_guard(log)(check_input("CAM-01", agent_id=None), "t1", None)
    assert denied(out)
    assert "subagent" in out["hookSpecificOutput"]["permissionDecisionReason"]
    event = decisions(log)[0]
    assert event["hook"] == "coordinator_guard"
    assert (event["decision"], event["agent"]) == ("deny", "coordinator")
    assert event["input"] == {"device_id": "CAM-01"}


# --- release gate ---

def release_input():
    return {"tool_name": "mcp__decision__release_technician",
            "tool_input": {"reason": "looks fine"}, "tool_use_id": "r1"}


@pytest.mark.anyio
async def test_release_allowed_when_nothing_new(log):
    baseline = healthy_site(CAM_05=offline("CAM-05"))
    r = Recorder()
    fill(r, baseline)
    gate = Gate(baseline, r)
    assert await make_release_gate(gate, log)(release_input(), "r1", None) == {}
    assert gate.denials == []
    assert decisions(log)[0]["decision"] == "allow"
    assert decisions(log)[0]["hook"] == "release_gate"


@pytest.mark.anyio
async def test_release_denied_on_new_offline_with_cause_in_reason(log):
    r = Recorder()
    fill(r, healthy_site(SW_01=online("SW-01", ports_down=(3,)), CAM_03=offline("CAM-03")))
    gate = Gate(healthy_site(), r)
    out = await make_release_gate(gate, log)(release_input(), "r1", None)
    assert denied(out)
    assert decisions(log)[0]["blocking"] == ["CAM-03"]
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "CAM-03 new_offline (SW-01 port 3 down)" in reason
    assert "hold_and_escalate" in reason
    assert gate.denials == [reason]


@pytest.mark.anyio
async def test_release_denied_when_devices_not_yet_checked(log):
    r = Recorder()
    r.record("CAM-01", json.dumps(online("CAM-01")), is_error=False)
    out = await make_release_gate(Gate(healthy_site(), r), log)(release_input(), "r1", None)
    assert denied(out)
    assert "POS-04 unknown" in out["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.anyio
async def test_release_denied_on_unknown(log):
    r = Recorder()
    fill(r, healthy_site(CAM_02=failure("CAM-02")))
    out = await make_release_gate(Gate(healthy_site(), r), log)(release_input(), "r1", None)
    assert denied(out)
