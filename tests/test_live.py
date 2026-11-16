"""One real agent run. Costs model usage, so it is skipped unless PRECHECK_LIVE=1."""
import os

import pytest

from agent.run import run_check
from mock_site import faults
from mock_site.state import empty_state, save_state

pytestmark = pytest.mark.skipif(os.environ.get("PRECHECK_LIVE") != "1",
                                reason="live model run; set PRECHECK_LIVE=1")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_live_unplugged_port_is_held(tmp_path):
    state = tmp_path / "state.json"
    dirs = {"baseline_dir": tmp_path / "b", "reports_dir": tmp_path / "r", "state_path": state}
    save_state(state, empty_state())
    pre = await run_check("precheck", **dirs)
    assert pre["baseline_saved"] is True, pre["agent"]

    save_state(state, faults.inject_port_down(empty_state(), "SW-01", 3))
    post = await run_check("postcheck", **dirs)
    for report in (pre, post):
        a = report["agent"]
        print(f"\n[{report['kind']}] model={a['model']} turns={a['num_turns']} "
              f"checks={a['check_calls']} cost=${a['total_cost_usd']}\n{a['summary']}")
    print("\ndecision:", post["decision"], "blocking:", post["diff"]["blocking"],
          [d for d in post["diff"]["devices"] if d["classification"] != "ok"])
    assert post["decision"] == "hold"
    assert "CAM-03" in post["diff"]["blocking"]
