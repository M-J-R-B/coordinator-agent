"""Run one pre-check or post-check.

The coordinator delegates to subagents; hooks record every device result,
gate the release and write the event log; code saves the baseline, diffs and
makes the final call.
"""
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import HookMatcher, query

from agent import report as reports
from agent.baseline import DEFAULT_BASELINE_DIR, load_baseline, save_baseline
from agent.decision import Decisions, create_decision_server
from agent.diff import diff
from agent.events import (DEFAULT_EVENTS_DIR, EventLog, Transcripts, log_turn_usage,
                          make_lifecycle_hooks, make_tool_log_hooks, untracked_tokens)
from agent.hooks import Gate, make_coordinator_guard, make_record_hooks, make_release_gate
from agent.options import (CHECK_TOOL, DEFAULT_MODEL, LIST_TOOL, RELEASE_TOOL,
                           build_options)
from agent.prompts import task_prompt
from agent.recorder import Recorder
from mock_site.devices import SITE_ID


def _now() -> datetime:
    return datetime.now(timezone.utc)


def build_hooks(recorder: Recorder, gate: Gate | None, log: EventLog,
                transcripts: Transcripts) -> dict:
    record_ok, record_fail = make_record_hooks(recorder)
    log_ok, log_fail = make_tool_log_hooks(log, transcripts)
    started, finished = make_lifecycle_hooks(log, transcripts)
    pre = [HookMatcher(matcher=f"{LIST_TOOL}|{CHECK_TOOL}", hooks=[make_coordinator_guard(log)])]
    if gate is not None:
        pre.append(HookMatcher(matcher=RELEASE_TOOL, hooks=[make_release_gate(gate, log)]))
    return {
        "PreToolUse": pre,
        "PostToolUse": [HookMatcher(matcher=CHECK_TOOL, hooks=[record_ok]),
                        HookMatcher(matcher=None, hooks=[log_ok])],
        "PostToolUseFailure": [HookMatcher(matcher=CHECK_TOOL, hooks=[record_fail]),
                               HookMatcher(matcher=None, hooks=[log_fail])],
        "SubagentStart": [HookMatcher(matcher=None, hooks=[started])],
        "SubagentStop": [HookMatcher(matcher=None, hooks=[finished])],
    }


async def _drive(options, kind: str, recorder: Recorder, query_fn) -> str | None:
    """Stream the run. SDK failures are returned as text, not raised."""
    try:
        async for message in query_fn(prompt=task_prompt(kind, SITE_ID), options=options):
            recorder.feed(message)
    except Exception as exc:  # CLI missing, auth, process crash...
        return f"{type(exc).__name__}: {exc}"
    return None if recorder.final is not None else "agent ended without a result message"


def _finish(report: dict, log: EventLog, transcripts: Transcripts | None, final,
            reports_dir: Path) -> dict:
    """Log per-turn usage, write check_finished, save the report."""
    tokens, source = log_turn_usage(log, transcripts) if transcripts else ({}, "unavailable")
    model_usage = getattr(final, "model_usage", None)
    untracked = untracked_tokens(tokens, model_usage)
    usage = {"source": source, "tokens_by_agent": tokens, "untracked_tokens": untracked,
             "consistent": None if untracked is None else all(v >= 0 for v in untracked.values())}
    if report.get("agent") is not None:
        report["agent"]["usage"] = usage
    report["event_log"] = str(log.path) if log.path else None
    log.emit("check_finished", kind=report["kind"],
             decision=report.get("decision"), baseline_saved=report.get("baseline_saved"),
             total_cost_usd=getattr(final, "total_cost_usd", None),
             num_turns=getattr(final, "num_turns", None),
             model_usage=model_usage, usage_source=source, tokens_by_agent=tokens,
             untracked_tokens=untracked, usage_consistent=usage["consistent"],
             error=report.get("error") or (report.get("agent") or {}).get("error"))
    reports.save_report(report, reports_dir)
    return report


async def run_check(kind: str, *, model: str = DEFAULT_MODEL, state_path: Path | None = None,
                    baseline_dir: Path = DEFAULT_BASELINE_DIR,
                    reports_dir: Path = reports.DEFAULT_REPORTS_DIR,
                    events_dir: Path = DEFAULT_EVENTS_DIR,
                    query_fn=query) -> dict:
    if kind not in ("precheck", "postcheck"):
        raise ValueError(f"unknown check kind: {kind}")
    now = _now()
    check_id = f"{kind}-{now.strftime('%Y%m%dT%H%M%S%fZ')}"
    created_at = now.isoformat()
    log = EventLog(Path(events_dir) / f"{check_id}.jsonl", check_id)
    log.emit("check_started", kind=kind, model=model, site=SITE_ID)
    recorder, transcripts = Recorder(), Transcripts()

    if kind == "precheck":
        options = build_options(hooks=build_hooks(recorder, None, log, transcripts), model=model,
                                state_path=state_path)
        error = await _drive(options, kind, recorder, query_fn)
        agent = reports.agent_section(recorder.final, error, recorder.check_calls, model)
        devices = recorder.complete()
        ok = not agent["is_error"]
        if ok:
            save_baseline(SITE_ID, devices, check_id, created_at, baseline_dir)
        report = reports.precheck_report(check_id, SITE_ID, created_at, agent, devices, ok)
        return _finish(report, log, transcripts, recorder.final, reports_dir)

    baseline = load_baseline(SITE_ID, baseline_dir)   # from disk, never from history
    if baseline is None:
        report = reports.postcheck_report(check_id, SITE_ID, created_at, None, None, None,
                                          error="no saved baseline: run the precheck first")
        return _finish(report, log, None, None, reports_dir)

    gate = Gate(baseline["devices"], recorder)
    decisions = Decisions()
    options = build_options(hooks=build_hooks(recorder, gate, log, transcripts), model=model,
                            state_path=state_path,
                            decision_server=create_decision_server(decisions))
    error = await _drive(options, kind, recorder, query_fn)
    agent = reports.agent_section(recorder.final, error, recorder.check_calls, model)
    report = reports.postcheck_report(
        check_id, SITE_ID, created_at, agent, baseline,
        diff(baseline["devices"], recorder.complete()), decisions, gate.denials)
    return _finish(report, log, transcripts, recorder.final, reports_dir)
