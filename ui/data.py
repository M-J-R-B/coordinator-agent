"""Everything the UI shows, as plain Python. No Streamlit import, so it is tested on
every supported Python. Read-only by design (tests/test_ui_readonly.py)."""
import json
import os
from dataclasses import dataclass
from pathlib import Path

from agent.schemas import report_errors
from agent.storage import DATA_DIR

DATA_ENV = "PRECHECK_DATA_DIR"
ICONS = {"release": "🟢", "hold": "🔴", "precheck": "🔵"}


def data_dir() -> Path:
    return Path(os.environ.get(DATA_ENV) or DATA_DIR)


@dataclass(frozen=True)
class ReportFile:
    path: Path
    check_id: str
    kind: str
    invalid: bool
    mtime: float


def _report_file(path: Path, invalid: bool) -> ReportFile:
    return ReportFile(path=path, check_id=path.stem, kind=path.stem.split("-")[0],
                      invalid=invalid, mtime=path.stat().st_mtime)


def list_reports(root: Path) -> list[ReportFile]:
    """All reports, newest first (check ids end in a UTC timestamp)."""
    reports = Path(root) / "reports"
    if not reports.is_dir():
        return []
    files = [_report_file(p, False) for p in reports.glob("*.json")]
    files += [_report_file(p, True) for p in (reports / "invalid").glob("*.json")]
    return sorted(files, key=lambda f: f.check_id.split("-", 1)[-1], reverse=True)


def load_report(path: Path) -> tuple[dict | None, list[str]]:
    """(report, problems). Problems: unreadable file, errors saved by finalize(),
    or schema errors found now. Nothing here raises for a bad file."""
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, [f"unreadable: {exc}"]
    if not isinstance(report, dict):
        return None, ["unreadable: not a JSON object"]
    saved = list(report.get("schema_errors") or [])
    current = report_errors({k: v for k, v in report.items() if k != "schema_errors"})
    return report, saved + [e for e in current if e not in saved]


def headline(report: dict) -> dict:
    agent = report.get("agent") or {}
    findings = report.get("findings")
    if report["kind"] == "postcheck":
        decision = report["decision"].upper()
        blocking = (report.get("diff") or {}).get("blocking", [])
    else:
        decision = "BASELINE SAVED" if report.get("baseline_saved") else "BASELINE NOT SAVED"
        blocking = []
    return {"decision": decision, "blocking": blocking,
            "devices_checked": findings["devices_checked"] if findings
            else agent.get("check_calls", 0),
            "cost_usd": agent.get("total_cost_usd"),
            "findings_valid": findings is not None,
            "findings_attempts": report.get("findings_attempts", 0)}


def device_rows(report: dict) -> list[dict]:
    if report["kind"] == "precheck":
        keys = ("device_id", "type", "status", "latency_ms", "error_category", "message")
        return [{k: d.get(k) for k in keys} for d in report.get("devices", [])]
    keys = ("device_id", "type", "baseline_status", "status", "classification", "likely_cause")
    return [{k: d.get(k) for k in keys} for d in (report.get("diff") or {}).get("devices", [])]


def load_events(path) -> list[dict]:
    """The check's event log; bad lines are skipped, a missing file is empty."""
    if not path or not Path(path).exists():
        return []
    events = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _detail(event: dict) -> str:
    """One short line per event type for the timeline."""
    kind = event.get("type")
    if kind == "tool_call":
        value = event.get("input")
    elif kind == "hook_decision":
        value = event.get("reason") or event.get("input")
    elif kind == "turn_usage":
        value = {k: (event.get("usage") or {}).get(k) for k in ("input_tokens", "output_tokens")}
    elif kind == "findings_validation":
        value = event.get("errors") or "valid"
    elif kind == "check_finished":
        value = {"cost_usd": event.get("total_cost_usd"), "error": event.get("error")}
    else:
        value = event.get("last_message") or event.get("kind") or ""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text[:160]


def event_rows(events: list[dict], types=None, agents=None) -> list[dict]:
    rows = []
    for e in events:
        if types and e.get("type") not in types:
            continue
        if agents and e.get("agent") not in agents:
            continue
        rows.append({"seq": e.get("seq"), "ts": e.get("ts"), "type": e.get("type"),
                     "agent": e.get("agent") or "", "tool": e.get("tool") or "",
                     "decision": e.get("decision") or "", "detail": _detail(e)})
    return rows


def event_filter_options(events: list[dict]) -> tuple[list[str], list[str]]:
    types = sorted({e["type"] for e in events if e.get("type")})
    agents = sorted({e["agent"] for e in events if e.get("agent")})
    return types, agents


def usage_rows(report: dict) -> list[dict]:
    tokens = (((report.get("agent") or {}).get("usage") or {}).get("tokens_by_agent")) or {}
    return [{"agent": agent, **counts} for agent, counts in tokens.items()]


def label(rf: ReportFile, report: dict | None) -> str:
    if report is None:
        return f"⚠ unreadable · {rf.check_id}"
    if report["kind"] == "postcheck":
        decision = report["decision"]
        head = f"{ICONS.get(decision, '')} {decision.upper()}"
    else:
        head = f"{ICONS['precheck']} BASELINE"
    when = str(report.get("created_at", ""))[:16].replace("T", " ")
    flag = " · ⚠ invalid" if rf.invalid else ""
    return f"{head} · {report['kind']} · {when}{flag}"
