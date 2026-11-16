"""Assemble, validate and save check reports (schema: schemas/report.schema.json)."""
from dataclasses import asdict
from pathlib import Path

from agent.schemas import report_errors
from agent.storage import DATA_DIR, write_json_atomic

DEFAULT_REPORTS_DIR = DATA_DIR / "reports"


def agent_section(final, error: str | None, check_calls: int, model: str) -> dict:
    return {
        "model": model,
        "summary": getattr(final, "result", None),
        "is_error": error is not None or final is None or bool(final.is_error),
        "subtype": getattr(final, "subtype", None),
        "num_turns": getattr(final, "num_turns", None),
        "check_calls": check_calls,
        "total_cost_usd": getattr(final, "total_cost_usd", None),
        "error": error,
    }


def precheck_report(check_id: str, site: str, created_at: str, agent: dict,
                    devices: dict, baseline_saved: bool) -> dict:
    return {"kind": "precheck", "check_id": check_id, "site": site,
            "created_at": created_at, "agent": agent,
            "devices": list(devices.values()), "baseline_saved": baseline_saved}


def postcheck_report(check_id: str, site: str, created_at: str, agent: dict | None,
                     baseline: dict | None, diff: dict | None, decisions=None,
                     denials: list[str] | None = None, error: str | None = None) -> dict:
    """decision is "release" only if the release tool actually ran (so the gate
    allowed it) AND the final diff still allows it. Anything else holds."""
    released = bool(decisions and decisions.released)
    allowed = diff is not None and error is None and diff["release_allowed"]
    agent_decision = None
    if decisions is not None:
        agent_decision = {**asdict(decisions), "release_denials": list(denials or [])}
    return {"kind": "postcheck", "check_id": check_id, "site": site,
            "created_at": created_at, "agent": agent,
            "baseline_check_id": baseline["check_id"] if baseline else None,
            "diff": diff, "agent_decision": agent_decision,
            "decision": "release" if released and allowed else "hold",
            "error": error}


def save_report(report: dict, reports_dir: Path = DEFAULT_REPORTS_DIR) -> Path:
    return write_json_atomic(Path(reports_dir) / f"{report['check_id']}.json", report)


def finalize(report: dict, reports_dir: Path, log) -> dict:
    """Every check ends with a report that validates against the schema.

    A report that fails is a bug in our code, not in the model's output. It is
    still saved (to reports/invalid/) so the evidence is not lost, a post-check
    is forced to hold, and the errors are logged.
    """
    errors = report_errors(report)
    if not errors:
        save_report(report, reports_dir)
        return report
    if report.get("kind") == "postcheck":
        report["decision"] = "hold"
    report["schema_errors"] = errors
    log.emit("report_invalid", errors=errors)
    save_report(report, Path(reports_dir) / "invalid")
    return report
