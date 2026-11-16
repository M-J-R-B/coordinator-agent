"""Run one pre-check or post-check.

The coordinator delegates to subagents; hooks record every device result,
gate the release and write the event log; code saves the baseline, diffs and
makes the final call. The model's structured findings are validated against
the schema and the evidence, with up to MAX_RETRIES corrections; they never
influence the decision.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import HookMatcher, ResultMessage, query

from agent import report as reports
from agent.baseline import DEFAULT_BASELINE_DIR, load_baseline, save_baseline
from agent.decision import Decisions, create_decision_server
from agent.diff import diff
from agent.events import (DEFAULT_EVENTS_DIR, EventLog, Transcripts, log_turn_usage,
                          make_lifecycle_hooks, make_tool_log_hooks, untracked_tokens)
from agent.findings import MAX_RETRIES, check_findings, retry_prompt
from agent.hooks import (Gate, make_coordinator_guard, make_record_hooks, make_release_gate,
                         make_retry_guard)
from agent.options import (CHECK_TOOL, DEFAULT_MODEL, LIST_TOOL, RELEASE_TOOL,
                           build_options)
from agent.prompts import task_prompt
from agent.recorder import Recorder
from mock_site.devices import SITE_ID


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Phase:
    """correcting=True while the model is only allowed to fix its findings."""
    correcting: bool = False


@dataclass
class FindingsOutcome:
    findings: dict | None = None
    error: dict | None = None
    attempts: int = 0
    retry_results: list = field(default_factory=list)


def build_hooks(recorder: Recorder, gate: Gate | None, log: EventLog,
                transcripts: Transcripts, phase: Phase) -> dict:
    record_ok, record_fail = make_record_hooks(recorder)
    log_ok, log_fail = make_tool_log_hooks(log, transcripts)
    started, finished = make_lifecycle_hooks(log, transcripts)
    pre = [HookMatcher(matcher=None, hooks=[make_retry_guard(phase, log)]),   # first
           HookMatcher(matcher=f"{LIST_TOOL}|{CHECK_TOOL}", hooks=[make_coordinator_guard(log)])]
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


async def _correction(options, session_id: str, errors: list[str], query_fn):
    """Resume the same session and ask only for corrected findings."""
    result = None
    try:
        async for message in query_fn(prompt=retry_prompt(errors),
                                      options=replace(options, resume=session_id)):
            if isinstance(message, ResultMessage):
                result = message
    except Exception:  # a failed correction just counts as no findings
        return None
    return result


async def _findings(options, recorder: Recorder, phase: Phase, log: EventLog,
                    query_fn) -> FindingsOutcome:
    """Validate the findings; on mismatch resume with the exact errors (max MAX_RETRIES)."""
    final, outcome = recorder.final, FindingsOutcome()
    if final is None or final.is_error:
        return outcome                      # the run failed: nothing to validate or retry
    candidate = final.structured_output
    while True:
        outcome.attempts += 1
        errors = check_findings(candidate, recorder.complete())
        log.emit("findings_validation", attempt=outcome.attempts, valid=not errors,
                 errors=errors)
        if not errors:
            outcome.findings = candidate
            return outcome
        if outcome.attempts > MAX_RETRIES:
            outcome.error = {"attempts": outcome.attempts, "errors": errors}
            return outcome
        phase.correcting = True
        result = await _correction(options, final.session_id, errors, query_fn)
        phase.correcting = False
        if result is not None:
            outcome.retry_results.append(result)
        candidate = getattr(result, "structured_output", None)


def _session_totals(results: list) -> tuple[float | None, dict | None]:
    """Cost and model_usage of the whole session = the LAST result's values.

    Verified live: a resumed session's ResultMessage reports running totals for
    the session (matching the CLI's cost-state), not just that call. Summing
    the results would count the first run twice.
    """
    latest = [r for r in results if r is not None]
    if not latest:
        return None, None
    return latest[-1].total_cost_usd, latest[-1].model_usage


def _apply_findings(report: dict, outcome: FindingsOutcome) -> None:
    report.update(findings=outcome.findings, findings_error=outcome.error,
                  findings_attempts=outcome.attempts)
    agent = report.get("agent")
    if agent is None:
        return
    if outcome.retry_results:
        agent["total_cost_usd"] = outcome.retry_results[-1].total_cost_usd
    if outcome.findings:
        agent["summary"] = outcome.findings["summary"]


def _finish(report: dict, log: EventLog, transcripts: Transcripts | None, results: list,
            reports_dir: Path) -> dict:
    """Log per-turn usage, write check_finished, validate and save the report."""
    report.setdefault("findings", None)
    report.setdefault("findings_error", None)
    report.setdefault("findings_attempts", 0)
    tokens, source = log_turn_usage(log, transcripts) if transcripts else ({}, "unavailable")
    _, model_usage = _session_totals(results)
    untracked = untracked_tokens(tokens, model_usage)
    usage = {"source": source, "tokens_by_agent": tokens, "untracked_tokens": untracked,
             "consistent": None if untracked is None else all(v >= 0 for v in untracked.values())}
    agent = report.get("agent")
    if agent is not None:
        agent["usage"] = usage
    report["event_log"] = str(log.path) if log.path else None
    log.emit("check_finished", kind=report["kind"],
             decision=report.get("decision"), baseline_saved=report.get("baseline_saved"),
             total_cost_usd=(agent or {}).get("total_cost_usd"),
             num_turns=(agent or {}).get("num_turns"),
             model_usage=model_usage, usage_source=source, tokens_by_agent=tokens,
             untracked_tokens=untracked, usage_consistent=usage["consistent"],
             findings_valid=report["findings"] is not None,
             findings_attempts=report["findings_attempts"],
             error=report.get("error") or (agent or {}).get("error"))
    return reports.finalize(report, reports_dir, log)


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
    recorder, transcripts, phase = Recorder(), Transcripts(), Phase()

    if kind == "precheck":
        options = build_options(hooks=build_hooks(recorder, None, log, transcripts, phase),
                                model=model, state_path=state_path)
        error = await _drive(options, kind, recorder, query_fn)
        agent = reports.agent_section(recorder.final, error, recorder.check_calls, model)
        devices = recorder.complete()
        ok = not agent["is_error"]
        if ok:
            save_baseline(SITE_ID, devices, check_id, created_at, baseline_dir)
        report = reports.precheck_report(check_id, SITE_ID, created_at, agent, devices, ok)
        outcome = await _findings(options, recorder, phase, log, query_fn)
        _apply_findings(report, outcome)
        return _finish(report, log, transcripts, [recorder.final, *outcome.retry_results],
                       reports_dir)

    baseline = load_baseline(SITE_ID, baseline_dir)   # from disk, never from history
    if baseline is None:
        report = reports.postcheck_report(check_id, SITE_ID, created_at, None, None, None,
                                          error="no saved baseline: run the precheck first")
        return _finish(report, log, None, [], reports_dir)

    gate = Gate(baseline["devices"], recorder)
    decisions = Decisions()
    options = build_options(hooks=build_hooks(recorder, gate, log, transcripts, phase),
                            model=model, state_path=state_path,
                            decision_server=create_decision_server(decisions))
    error = await _drive(options, kind, recorder, query_fn)
    agent = reports.agent_section(recorder.final, error, recorder.check_calls, model)
    report = reports.postcheck_report(
        check_id, SITE_ID, created_at, agent, baseline,
        diff(baseline["devices"], recorder.complete()), decisions, gate.denials)
    outcome = await _findings(options, recorder, phase, log, query_fn)
    _apply_findings(report, outcome)
    return _finish(report, log, transcripts, [recorder.final, *outcome.retry_results],
                   reports_dir)
