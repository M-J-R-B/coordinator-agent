"""Real agent runs (coordinator + subagents). Cost model usage: skipped unless PRECHECK_LIVE=1."""
import os

import pytest

from agent.run import run_check
from agent.schemas import report_errors
from mock_site import faults
from mock_site.state import empty_state, save_state

pytestmark = pytest.mark.skipif(os.environ.get("PRECHECK_LIVE") != "1",
                                reason="live model run; set PRECHECK_LIVE=1")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def live(tmp_path):
    state = tmp_path / "state.json"
    save_state(state, empty_state())
    return state, {"baseline_dir": tmp_path / "b", "reports_dir": tmp_path / "r",
                   "events_dir": tmp_path / "e", "state_path": state}


def show(report):
    assert report_errors(report) == [], report_errors(report)
    a = report["agent"]
    print(f"\n[{report['kind']}] model={a['model']} turns={a['num_turns']} "
          f"checks={a['check_calls']} cost=${a['total_cost_usd']}")
    if report["kind"] == "postcheck":
        print("decision:", report["decision"], "| agent_decision:", report["agent_decision"])
    print(f"findings: attempts={report['findings_attempts']} "
          f"valid={report['findings'] is not None} error={report['findings_error']}")
    print(a["summary"])


@pytest.mark.anyio
async def test_live_unplugged_port_is_held(live):
    state, dirs = live
    pre = await run_check("precheck", **dirs)
    show(pre)
    assert pre["baseline_saved"] is True, pre["agent"]

    save_state(state, faults.inject_port_down(empty_state(), "SW-01", 3))
    post = await run_check("postcheck", **dirs)
    show(post)
    assert post["decision"] == "hold"
    assert "CAM-03" in post["diff"]["blocking"]
    assert post["agent_decision"]["released"] is False


@pytest.mark.anyio
async def test_live_healthy_site_is_released(live):
    _, dirs = live
    pre = await run_check("precheck", **dirs)
    show(pre)
    assert pre["baseline_saved"] is True, pre["agent"]

    post = await run_check("postcheck", **dirs)
    show(post)
    assert post["decision"] == "release"
    assert post["agent_decision"]["released"] is True
