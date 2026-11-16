"""Assemble and save check reports. Step 5 adds a JSON schema for these."""
from pathlib import Path

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
                     baseline: dict | None, diff: dict | None,
                     error: str | None = None) -> dict:
    released = diff is not None and error is None and diff["release_allowed"]
    return {"kind": "postcheck", "check_id": check_id, "site": site,
            "created_at": created_at, "agent": agent,
            "baseline_check_id": baseline["check_id"] if baseline else None,
            "diff": diff, "decision": "release" if released else "hold",
            "error": error}


def save_report(report: dict, reports_dir: Path = DEFAULT_REPORTS_DIR) -> Path:
    return write_json_atomic(Path(reports_dir) / f"{report['check_id']}.json", report)
