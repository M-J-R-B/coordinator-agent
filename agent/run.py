"""Run one pre-check or post-check: agent polls, code records, saves and decides."""
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import query

from agent import report as reports
from agent.baseline import DEFAULT_BASELINE_DIR, load_baseline, save_baseline
from agent.diff import diff
from agent.options import DEFAULT_MODEL, build_options
from agent.prompts import task_prompt
from agent.recorder import Recorder
from mock_site.devices import SITE_ID


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _drive_agent(kind: str, model: str, state_path, query_fn) -> tuple[Recorder, str | None]:
    """Stream the agent run into a Recorder. SDK failures are returned, not raised."""
    recorder = Recorder()
    try:
        async for message in query_fn(prompt=task_prompt(kind, SITE_ID),
                                      options=build_options(model, state_path)):
            recorder.feed(message)
    except Exception as exc:  # CLI missing, auth, process crash...
        return recorder, f"{type(exc).__name__}: {exc}"
    if recorder.final is None:
        return recorder, "agent ended without a result message"
    return recorder, None


async def run_check(kind: str, *, model: str = DEFAULT_MODEL, state_path: Path | None = None,
                    baseline_dir: Path = DEFAULT_BASELINE_DIR,
                    reports_dir: Path = reports.DEFAULT_REPORTS_DIR,
                    query_fn=query) -> dict:
    if kind not in ("precheck", "postcheck"):
        raise ValueError(f"unknown check kind: {kind}")
    now = _now()
    check_id = f"{kind}-{now.strftime('%Y%m%dT%H%M%S%fZ')}"
    created_at = now.isoformat()

    baseline = load_baseline(SITE_ID, baseline_dir) if kind == "postcheck" else None
    if kind == "postcheck" and baseline is None:
        report = reports.postcheck_report(check_id, SITE_ID, created_at, None, None, None,
                                          error="no saved baseline: run the precheck first")
        reports.save_report(report, reports_dir)
        return report

    recorder, error = await _drive_agent(kind, model, state_path, query_fn)
    agent = reports.agent_section(recorder.final, error, recorder.check_calls, model)
    devices = recorder.complete()

    if kind == "precheck":
        ok = not agent["is_error"]
        if ok:
            save_baseline(SITE_ID, devices, check_id, created_at, baseline_dir)
        report = reports.precheck_report(check_id, SITE_ID, created_at, agent, devices, ok)
    else:
        report = reports.postcheck_report(check_id, SITE_ID, created_at, agent, baseline,
                                          diff(baseline["devices"], devices))
    reports.save_report(report, reports_dir)
    return report
