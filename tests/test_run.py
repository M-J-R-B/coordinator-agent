"""End-to-end check flow with a scripted fake query (no model calls)."""
import json

import pytest

from agent.baseline import load_baseline, save_baseline
from agent.run import run_check
from tests.fakes import (FakeQuery, healthy_site, offline, online, result_message,
                         script, tool_result, tool_use)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def dirs(tmp_path):
    return {"baseline_dir": tmp_path / "baselines", "reports_dir": tmp_path / "reports"}


async def run(kind, fake, dirs, **kw):
    return await run_check(kind, query_fn=fake, **dirs, **kw)


@pytest.mark.anyio
async def test_precheck_saves_baseline_and_report(dirs):
    fake = FakeQuery(script(healthy_site(CAM_05=offline("CAM-05"))))
    report = await run("precheck", fake, dirs)
    baseline = load_baseline("STORE-001", dirs["baseline_dir"])
    assert baseline["devices"]["CAM-05"]["status"] == "offline"
    assert report["kind"] == "precheck"
    assert report["baseline_saved"] is True
    assert report["agent"]["summary"] == "All checked."
    saved = json.loads((dirs["reports_dir"] / f"{report['check_id']}.json").read_text())
    assert saved == report


@pytest.mark.anyio
async def test_prompt_and_options_passed_to_agent(dirs):
    fake = FakeQuery(script(healthy_site()))
    await run("precheck", fake, dirs, model="claude-sonnet-5-5")
    call = fake.calls[0]
    assert "STORE-001" in call["prompt"]
    assert call["options"].model == "claude-sonnet-5-5"


@pytest.mark.anyio
async def test_precheck_agent_error_does_not_overwrite_baseline(dirs):
    save_baseline("STORE-001", healthy_site(), "old", "t0", dirs["baseline_dir"])
    fake = FakeQuery([result_message("boom", is_error=True, subtype="error_during_execution")])
    report = await run("precheck", fake, dirs)
    assert report["baseline_saved"] is False
    assert load_baseline("STORE-001", dirs["baseline_dir"])["check_id"] == "old"


@pytest.mark.anyio
async def test_precheck_sdk_exception_is_reported_not_raised(dirs):
    report = await run("precheck", FakeQuery(raises=RuntimeError("CLI not found")), dirs)
    assert report["baseline_saved"] is False
    assert "CLI not found" in report["agent"]["error"]


@pytest.mark.anyio
async def test_postcheck_without_baseline_holds_and_skips_agent(dirs):
    fake = FakeQuery(script(healthy_site()))
    report = await run("postcheck", fake, dirs)
    assert report["decision"] == "hold"
    assert "baseline" in report["error"]
    assert fake.calls == []


@pytest.mark.anyio
async def test_postcheck_release_when_nothing_new(dirs):
    before = healthy_site(CAM_05=offline("CAM-05"))
    save_baseline("STORE-001", before, "pre-1", "t0", dirs["baseline_dir"])
    report = await run("postcheck", FakeQuery(script(before)), dirs)
    assert report["decision"] == "release"
    assert report["baseline_check_id"] == "pre-1"


@pytest.mark.anyio
async def test_postcheck_unplugged_port_holds_with_cause(dirs):
    save_baseline("STORE-001", healthy_site(), "pre-1", "t0", dirs["baseline_dir"])
    after = healthy_site(SW_01=online("SW-01", ports_down=(3,)), CAM_03=offline("CAM-03"))
    report = await run("postcheck", FakeQuery(script(after)), dirs)
    assert report["decision"] == "hold"
    assert report["diff"]["blocking"] == ["CAM-03"]
    cam = next(d for d in report["diff"]["devices"] if d["device_id"] == "CAM-03")
    assert cam["likely_cause"] == "SW-01 port 3 down"


@pytest.mark.anyio
async def test_postcheck_device_agent_skipped_blocks_release(dirs):
    save_baseline("STORE-001", healthy_site(), "pre-1", "t0", dirs["baseline_dir"])
    site = healthy_site()
    del site["POS-04"]
    report = await run("postcheck", FakeQuery(script(site)), dirs)
    assert report["decision"] == "hold"
    assert "POS-04" in report["diff"]["blocking"]


@pytest.mark.anyio
async def test_model_summary_cannot_override_tool_evidence(dirs):
    """Agent claims all online, but a tool result said offline: evidence wins."""
    save_baseline("STORE-001", healthy_site(), "pre-1", "t0", dirs["baseline_dir"])
    msgs = script(healthy_site(CAM_02=offline("CAM-02")), summary="All 14 devices online.")
    report = await run("postcheck", FakeQuery(msgs), dirs)
    assert report["decision"] == "hold"
    assert report["diff"]["blocking"] == ["CAM-02"]
