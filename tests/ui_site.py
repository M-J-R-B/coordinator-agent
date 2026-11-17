"""Build a realistic data/ folder for UI tests: real run_check output via the fake CLI."""
import json
from pathlib import Path

import anyio

from agent.run import run_check
from tests.fakes import FakeQuery, escalate, healthy_site, offline, online, release, script


def unplugged_site():
    return healthy_site(SW_01=online("SW-01", ports_down=(3,)), CAM_03=offline("CAM-03"))


def build_data_dir(root: Path) -> dict:
    """precheck -> postcheck HOLD (SW-01 port 3) -> postcheck RELEASE, plus bad files."""
    dirs = {"baseline_dir": root / "baselines", "reports_dir": root / "reports",
            "events_dir": root / "events"}

    async def make():
        pre = await run_check("precheck", query_fn=FakeQuery(script(healthy_site()),
                                                             transcript_dir=root / "t1"), **dirs)
        hold = await run_check("postcheck", query_fn=FakeQuery(
            script(unplugged_site(), release(), escalate(["CAM-03"])),
            transcript_dir=root / "t2"), **dirs)
        ok = await run_check("postcheck", query_fn=FakeQuery(
            script(healthy_site(), release()), transcript_dir=root / "t3"), **dirs)
        return pre, hold, ok

    pre, hold, ok = anyio.run(make)
    # An invalid report (as finalize() would set it aside) and an unreadable file.
    invalid = {**ok, "check_id": "postcheck-29990101T000000000000Z", "decision": "hold",
               "schema_errors": ["decision: 'release-ish' is not one of ['release', 'hold']"]}
    (root / "reports" / "invalid").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "invalid" / f"{invalid['check_id']}.json").write_text(
        json.dumps(invalid), encoding="utf-8")
    (root / "reports" / "precheck-00000000T000000000000Z.json").write_text(
        "{not json", encoding="utf-8")
    return {"precheck": pre, "hold": hold, "release": ok, "invalid": invalid}
