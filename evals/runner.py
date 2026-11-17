"""Run scenarios through the real agent and score each one.

Each scenario gets its own folder (state file, baselines, reports, events), so
nothing from one visit can leak into the next. Scenarios run one after another:
simpler logs and no rate-limit surprises; running them in parallel was rejected
because ten visits is a small enough set that speed does not matter.
"""
from dataclasses import dataclass
from pathlib import Path

from agent.diff import BLOCKING
from agent.run import run_check
from evals.scenarios import Scenario, apply_faults
from mock_site.state import empty_state, save_state


@dataclass
class Result:
    scenario_id: str
    expected_decision: str
    actual_decision: str | None
    correct: bool
    expected_blocking: list[str]
    reported_blocking: list[str]
    blocking_match: bool
    cost_usd: float | None  # pre-check plus post-check; None if either is missing
    num_turns: int | None
    schema_valid: bool
    error: str | None
    # Times the agent tried to release and the code-level gate refused.
    blocked_release_attempts: int = 0
    # What the agent itself did at the end of the post-check, and its stated reason.
    agent_action: str | None = None  # "released" | "escalated" | "none"
    agent_reason: str | None = None


def _action(agent_decision: dict) -> tuple[str, str | None]:
    if agent_decision.get("released"):
        return "released", agent_decision.get("release_reason")
    if agent_decision.get("escalated"):
        return "escalated", agent_decision.get("escalate_reason")
    return "none", None


def _dirs(workdir: Path, scenario_id: str) -> dict:
    root = Path(workdir) / scenario_id
    return {"state_path": root / "state.json", "baseline_dir": root / "baselines",
            "reports_dir": root / "reports", "events_dir": root / "events"}


def _sum(values: list) -> float | int | None:
    return None if any(v is None for v in values) else sum(values)


def _failed(scenario: Scenario, error: str) -> Result:
    return Result(scenario.id, scenario.expected_decision, None, False,
                  sorted(scenario.expected_blocking), [], False, None, None, False, error)


def _score(scenario: Scenario, pre: dict, post: dict) -> Result:
    agents = [(report.get("agent") or {}) for report in (pre, post)]
    devices = (post.get("diff") or {}).get("devices", [])
    reported = sorted(d["device_id"] for d in devices if d["classification"] in BLOCKING)
    expected = sorted(scenario.expected_blocking)
    error = post.get("error") or pre.get("error")
    decision = post.get("decision")
    agent_decision = post.get("agent_decision") or {}
    denials = agent_decision.get("release_denials", [])
    action, reason = _action(agent_decision)
    return Result(
        agent_action=action,
        agent_reason=reason,
        scenario_id=scenario.id,
        expected_decision=scenario.expected_decision,
        actual_decision=decision,
        correct=decision == scenario.expected_decision and not error,
        expected_blocking=expected,
        reported_blocking=reported,
        blocking_match=reported == expected,
        cost_usd=_sum([a.get("total_cost_usd") for a in agents]),
        num_turns=_sum([a.get("num_turns") for a in agents]),
        schema_valid=not (pre.get("schema_errors") or post.get("schema_errors")),
        error=error,
        blocked_release_attempts=len(denials),
    )


async def run_scenario(scenario: Scenario, *, model: str, workdir: Path,
                       run_check_fn=run_check) -> Result:
    """One visit: pre-check, apply the `during` faults, post-check, score."""
    dirs = _dirs(workdir, scenario.id)
    try:
        state = apply_faults(empty_state(), scenario.before)
        save_state(dirs["state_path"], state)
        pre = await run_check_fn("precheck", model=model, **dirs)
        save_state(dirs["state_path"], apply_faults(state, scenario.during))
        post = await run_check_fn("postcheck", model=model, **dirs)
    except Exception as exc:  # one broken visit must not stop the scorecard
        return _failed(scenario, f"{type(exc).__name__}: {exc}")
    return _score(scenario, pre, post)


async def run_all(scenarios, *, model: str, workdir: Path, run_check_fn=run_check) -> list[Result]:
    return [await run_scenario(s, model=model, workdir=workdir, run_check_fn=run_check_fn)
            for s in scenarios]
