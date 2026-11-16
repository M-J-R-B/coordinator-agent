"""End-to-end check flow with the scripted fake CLI (no model calls)."""
import json

import pytest

from agent.baseline import load_baseline, save_baseline
from agent.run import run_check
from tests.fakes import (Check, FakeQuery, escalate, healthy_site, offline, online,
                         release, result_message, script)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def dirs(tmp_path):
    return {"baseline_dir": tmp_path / "baselines", "reports_dir": tmp_path / "reports"}


def with_baseline(dirs, site=None):
    save_baseline("STORE-001", site or healthy_site(), "pre-1", "t0", dirs["baseline_dir"])


async def run(kind, fake, dirs, **kw):
    return await run_check(kind, query_fn=fake, **dirs, **kw)


def unplugged_site():
    return healthy_site(SW_01=online("SW-01", ports_down=(3,)), CAM_03=offline("CAM-03"))


# --- precheck ---

@pytest.mark.anyio
async def test_precheck_saves_baseline_and_report(dirs):
    report = await run("precheck", FakeQuery(script(healthy_site(CAM_05=offline("CAM-05")))), dirs)
    assert load_baseline("STORE-001", dirs["baseline_dir"])["devices"]["CAM-05"]["status"] == "offline"
    assert report["baseline_saved"] is True
    saved = json.loads((dirs["reports_dir"] / f"{report['check_id']}.json").read_text())
    assert saved == report


@pytest.mark.anyio
async def test_precheck_cannot_release(dirs):
    fake = FakeQuery(script(healthy_site(), release()))
    await run("precheck", fake, dirs)
    assert fake.executed == []
    assert fake.denials[0][0] == "mcp__decision__release_technician"


@pytest.mark.anyio
async def test_prompt_and_options_passed_to_agent(dirs):
    fake = FakeQuery(script(healthy_site()))
    await run("precheck", fake, dirs, model="claude-sonnet-5-5")
    call = fake.calls[0]
    assert "STORE-001" in call["prompt"]
    assert call["options"].model == "claude-sonnet-5-5"


@pytest.mark.anyio
async def test_coordinator_direct_check_denied_and_not_recorded(dirs):
    fake = FakeQuery([Check("CAM-01", online("CAM-01"), agent_id=""), result_message()])
    report = await run("precheck", fake, dirs)
    assert fake.denials and "subagent" in fake.denials[0][1]
    cam = next(d for d in report["devices"] if d["device_id"] == "CAM-01")
    assert cam["error_category"] == "not_checked"


@pytest.mark.anyio
async def test_precheck_agent_error_does_not_overwrite_baseline(dirs):
    with_baseline(dirs)
    fake = FakeQuery([result_message("boom", is_error=True, subtype="error_during_execution")])
    report = await run("precheck", fake, dirs)
    assert report["baseline_saved"] is False
    assert load_baseline("STORE-001", dirs["baseline_dir"])["check_id"] == "pre-1"


@pytest.mark.anyio
async def test_precheck_sdk_exception_is_reported_not_raised(dirs):
    report = await run("precheck", FakeQuery(raises=RuntimeError("CLI not found")), dirs)
    assert report["baseline_saved"] is False
    assert "CLI not found" in report["agent"]["error"]


# --- postcheck ---

@pytest.mark.anyio
async def test_postcheck_without_baseline_holds_and_skips_agent(dirs):
    fake = FakeQuery(script(healthy_site(), release()))
    report = await run("postcheck", fake, dirs)
    assert report["decision"] == "hold"
    assert "baseline" in report["error"]
    assert fake.calls == []


@pytest.mark.anyio
async def test_postcheck_release_when_nothing_new(dirs):
    before = healthy_site(CAM_05=offline("CAM-05"))
    with_baseline(dirs, before)
    fake = FakeQuery(script(before, release("all clear")))
    report = await run("postcheck", fake, dirs)
    assert fake.executed == ["release_technician"]
    assert report["decision"] == "release"
    assert report["agent_decision"]["released"] is True
    assert report["baseline_check_id"] == "pre-1"


@pytest.mark.anyio
async def test_release_attempt_with_new_offline_is_denied_by_hook(dirs):
    with_baseline(dirs)
    fake = FakeQuery(script(unplugged_site(), release("looks fine"), escalate(["CAM-03"])))
    report = await run("postcheck", fake, dirs)
    assert fake.executed == ["hold_and_escalate"]
    assert report["decision"] == "hold"
    assert len(report["agent_decision"]["release_denials"]) == 1
    assert "CAM-03 new_offline (SW-01 port 3 down)" in report["agent_decision"]["release_denials"][0]
    assert report["agent_decision"]["escalated_devices"] == ["CAM-03"]


@pytest.mark.anyio
async def test_insisting_on_release_still_holds(dirs):
    """The fake model ignores the denial and tries again: still blocked every time."""
    with_baseline(dirs)
    fake = FakeQuery(script(unplugged_site(), release(), release(), release(),
                            summary="Released the tech."))
    report = await run("postcheck", fake, dirs)
    assert fake.executed == []
    assert report["decision"] == "hold"
    assert len(report["agent_decision"]["release_denials"]) == 3


@pytest.mark.anyio
async def test_release_before_all_devices_checked_is_denied(dirs):
    with_baseline(dirs)
    steps = [Check("CAM-01", online("CAM-01")), release(), result_message()]
    report = await run("postcheck", FakeQuery(steps), dirs)
    assert report["decision"] == "hold"
    assert "POS-04 unknown" in report["agent_decision"]["release_denials"][0]
    assert report["agent_decision"]["released"] is False


@pytest.mark.anyio
async def test_no_decision_call_means_hold(dirs):
    with_baseline(dirs)
    report = await run("postcheck", FakeQuery(script(healthy_site())), dirs)
    assert report["decision"] == "hold"
    assert report["agent_decision"]["released"] is False


@pytest.mark.anyio
async def test_postcheck_unplugged_port_diff_has_cause(dirs):
    with_baseline(dirs)
    report = await run("postcheck", FakeQuery(script(unplugged_site(), escalate(["CAM-03"]))), dirs)
    assert report["diff"]["blocking"] == ["CAM-03"]
    cam = next(d for d in report["diff"]["devices"] if d["device_id"] == "CAM-03")
    assert cam["likely_cause"] == "SW-01 port 3 down"


@pytest.mark.anyio
async def test_model_summary_cannot_override_tool_evidence(dirs):
    """Agent claims all online, but a tool result said offline: release is denied."""
    with_baseline(dirs)
    steps = script(healthy_site(CAM_02=offline("CAM-02")), release(),
                   summary="All 14 devices online.")
    report = await run("postcheck", FakeQuery(steps), dirs)
    assert report["decision"] == "hold"
    assert report["diff"]["blocking"] == ["CAM-02"]
