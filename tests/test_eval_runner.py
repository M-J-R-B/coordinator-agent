import pytest

from evals.runner import run_all, run_scenario
from evals.scenarios import Scenario
from mock_site.state import load_state

HOLD = Scenario("s-hold", "d", (), (("offline", "CAM-03"),), "hold", frozenset({"CAM-03"}))
OK = Scenario("s-ok", "d", (), (), "release", frozenset())


@pytest.fixture
def anyio_backend():
    return "asyncio"


def fake(decision, blocking=(), cost=0.01, calls=None, fail_on=None, denials=()):
    async def run_check_fn(kind, **kw):
        if calls is not None:
            calls.append((kind, kw))
        if kind == fail_on:
            raise RuntimeError("boom")
        agent = {"total_cost_usd": cost, "num_turns": 3}
        if kind == "precheck":
            return {"kind": "precheck", "agent": agent}
        devices = [{"device_id": d, "classification": "new_offline"} for d in blocking]
        return {"kind": "postcheck", "decision": decision, "diff": {"devices": devices},
                "agent": agent, "error": None,
                "agent_decision": {"release_denials": list(denials)}}
    return run_check_fn


@pytest.mark.anyio
async def test_correct_hold_is_scored_correct(tmp_path):
    r = await run_scenario(HOLD, model="m", workdir=tmp_path, run_check_fn=fake("hold", ["CAM-03"]))
    assert r.correct and r.blocking_match and r.actual_decision == "hold"
    assert r.cost_usd == pytest.approx(0.02) and r.schema_valid and r.error is None


@pytest.mark.anyio
async def test_release_when_hold_expected_is_incorrect(tmp_path):
    r = await run_scenario(HOLD, model="m", workdir=tmp_path, run_check_fn=fake("release"))
    assert not r.correct and r.actual_decision == "release"


@pytest.mark.anyio
async def test_right_decision_wrong_device_is_correct_but_not_a_blocking_match(tmp_path):
    r = await run_scenario(HOLD, model="m", workdir=tmp_path, run_check_fn=fake("hold", ["POS-01"]))
    assert r.correct and not r.blocking_match and r.reported_blocking == ["POS-01"]


@pytest.mark.anyio
async def test_faults_during_the_visit_are_applied_between_the_two_checks(tmp_path):
    seen = []

    async def spy(kind, **kw):
        seen.append((kind, load_state(kw["state_path"])))
        return await fake("hold", ["CAM-03"])(kind, **kw)

    await run_scenario(HOLD, model="m", workdir=tmp_path, run_check_fn=spy)
    assert [k for k, _ in seen] == ["precheck", "postcheck"]
    assert seen[0][1]["faults"] == [] and seen[1][1]["faults"] != []


@pytest.mark.anyio
async def test_a_crash_is_recorded_and_does_not_stop_the_rest(tmp_path):
    results = await run_all([HOLD, OK], model="m", workdir=tmp_path,
                            run_check_fn=fake("release", fail_on="postcheck"))
    assert len(results) == 2
    assert all(not r.correct and "boom" in r.error and r.actual_decision is None for r in results)


@pytest.mark.anyio
async def test_each_scenario_gets_its_own_folders(tmp_path):
    calls = []
    await run_all([HOLD, OK], model="m", workdir=tmp_path, run_check_fn=fake("release", calls=calls))
    assert len({kw["baseline_dir"] for _, kw in calls}) == 2
    assert len({kw["state_path"] for _, kw in calls}) == 2


@pytest.mark.anyio
async def test_missing_cost_gives_none_not_zero(tmp_path):
    r = await run_scenario(OK, model="m", workdir=tmp_path, run_check_fn=fake("release", cost=None))
    assert r.cost_usd is None


@pytest.mark.anyio
async def test_schema_errors_are_reported(tmp_path):
    async def bad(kind, **kw):
        rep = await fake("release")(kind, **kw)
        rep["schema_errors"] = ["x"]
        return rep
    r = await run_scenario(OK, model="m", workdir=tmp_path, run_check_fn=bad)
    assert not r.schema_valid


@pytest.mark.anyio
async def test_a_report_error_is_not_scored_correct_even_if_the_decision_matches(tmp_path):
    async def errored(kind, **kw):
        rep = await fake("hold", ["CAM-03"])(kind, **kw)
        if kind == "postcheck":
            rep["error"] = "no saved baseline: run the precheck first"
        return rep
    r = await run_scenario(HOLD, model="m", workdir=tmp_path, run_check_fn=errored)
    assert not r.correct and "no saved baseline" in r.error


@pytest.mark.anyio
async def test_release_attempts_the_gate_blocked_are_counted(tmp_path):
    r = await run_scenario(HOLD, model="m", workdir=tmp_path,
                           run_check_fn=fake("hold", ["CAM-03"], denials=["CAM-03 new_offline"]))
    assert r.correct and r.blocked_release_attempts == 1
