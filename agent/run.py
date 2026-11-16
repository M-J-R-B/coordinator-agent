"""Run one pre-check or post-check.

The coordinator delegates to subagents; hooks record every device result and
gate the release; code saves the baseline, diffs and makes the final call.
"""
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import HookMatcher, query

from agent import report as reports
from agent.baseline import DEFAULT_BASELINE_DIR, load_baseline, save_baseline
from agent.decision import Decisions, create_decision_server
from agent.diff import diff
from agent.hooks import Gate, coordinator_guard, make_record_hooks, make_release_gate
from agent.options import (CHECK_TOOL, DEFAULT_MODEL, LIST_TOOL, RELEASE_TOOL,
                           build_options)
from agent.prompts import task_prompt
from agent.recorder import Recorder
from mock_site.devices import SITE_ID


def _now() -> datetime:
    return datetime.now(timezone.utc)


def build_hooks(recorder: Recorder, gate: Gate | None) -> dict:
    on_success, on_failure = make_record_hooks(recorder)
    pre = [HookMatcher(matcher=f"{LIST_TOOL}|{CHECK_TOOL}", hooks=[coordinator_guard])]
    if gate is not None:
        pre.append(HookMatcher(matcher=RELEASE_TOOL, hooks=[make_release_gate(gate)]))
    return {
        "PreToolUse": pre,
        "PostToolUse": [HookMatcher(matcher=CHECK_TOOL, hooks=[on_success])],
        "PostToolUseFailure": [HookMatcher(matcher=CHECK_TOOL, hooks=[on_failure])],
    }


async def _drive(options, kind: str, recorder: Recorder, query_fn) -> str | None:
    """Stream the run. SDK failures are returned as text, not raised."""
    try:
        async for message in query_fn(prompt=task_prompt(kind, SITE_ID), options=options):
            recorder.feed(message)
    except Exception as exc:  # CLI missing, auth, process crash...
        return f"{type(exc).__name__}: {exc}"
    return None if recorder.final is not None else "agent ended without a result message"


async def run_check(kind: str, *, model: str = DEFAULT_MODEL, state_path: Path | None = None,
                    baseline_dir: Path = DEFAULT_BASELINE_DIR,
                    reports_dir: Path = reports.DEFAULT_REPORTS_DIR,
                    query_fn=query) -> dict:
    if kind not in ("precheck", "postcheck"):
        raise ValueError(f"unknown check kind: {kind}")
    now = _now()
    check_id = f"{kind}-{now.strftime('%Y%m%dT%H%M%S%fZ')}"
    created_at = now.isoformat()
    recorder = Recorder()

    if kind == "precheck":
        options = build_options(hooks=build_hooks(recorder, None), model=model,
                                state_path=state_path)
        error = await _drive(options, kind, recorder, query_fn)
        agent = reports.agent_section(recorder.final, error, recorder.check_calls, model)
        devices = recorder.complete()
        ok = not agent["is_error"]
        if ok:
            save_baseline(SITE_ID, devices, check_id, created_at, baseline_dir)
        report = reports.precheck_report(check_id, SITE_ID, created_at, agent, devices, ok)
        reports.save_report(report, reports_dir)
        return report

    baseline = load_baseline(SITE_ID, baseline_dir)   # from disk, never from history
    if baseline is None:
        report = reports.postcheck_report(check_id, SITE_ID, created_at, None, None, None,
                                          error="no saved baseline: run the precheck first")
        reports.save_report(report, reports_dir)
        return report

    gate = Gate(baseline["devices"], recorder)
    decisions = Decisions()
    options = build_options(hooks=build_hooks(recorder, gate), model=model,
                            state_path=state_path,
                            decision_server=create_decision_server(decisions))
    error = await _drive(options, kind, recorder, query_fn)
    agent = reports.agent_section(recorder.final, error, recorder.check_calls, model)
    report = reports.postcheck_report(
        check_id, SITE_ID, created_at, agent, baseline,
        diff(baseline["devices"], recorder.complete()), decisions, gate.denials)
    reports.save_report(report, reports_dir)
    return report
