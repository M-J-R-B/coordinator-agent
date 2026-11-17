"""Read-only dashboard for pre/post-check reports.

Run:  python -m streamlit run ui/app.py --server.address localhost
Data: $PRECHECK_DATA_DIR, default <repo>/data. Nothing here changes any file.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # `streamlit run` puts ui/ first

import streamlit as st  # noqa: E402

from ui import data  # noqa: E402


@st.cache_data(show_spinner=False)
def _report(path: str, mtime: float):
    """Cached per file version: a changed file (new mtime) is read again."""
    return data.load_report(Path(path))


@st.cache_data(show_spinner=False)
def _events(path: str, mtime: float):
    return data.load_events(path)


def _mtime(path) -> float:
    p = Path(path) if path else None
    return p.stat().st_mtime if p and p.exists() else 0.0


def sidebar(files) -> data.ReportFile:
    st.sidebar.title("Checks")
    labels = {f.check_id: data.label(f, _report(str(f.path), f.mtime)[0]) for f in files}
    choice = st.sidebar.selectbox("Check", list(labels), format_func=labels.get, key="check")
    st.sidebar.button("Reload")   # just reruns the script; caches pick up changed files
    st.sidebar.caption(f"Data: {data.data_dir()}")
    return next(f for f in files if f.check_id == choice)


def header(report: dict, problems: list[str]) -> None:
    st.title(f"{report['kind'].capitalize()} · {report['site']}")
    st.caption(f"{report['check_id']} · {report.get('created_at', '')}")
    if problems:
        st.error("This report does not validate against the schema:\n\n"
                 + "\n".join(f"- {p}" for p in problems))
    h = data.headline(report)
    cols = st.columns(5)
    cols[0].metric("Decision", h["decision"])
    cols[1].metric("Blocking", str(len(h["blocking"])))
    cols[2].metric("Devices checked", str(h["devices_checked"]))
    cols[3].metric("Cost (USD)", f"{h['cost_usd']:.4f}" if h["cost_usd"] is not None else "—")
    cols[4].metric("Findings", f"valid ({h['findings_attempts']} try)" if h["findings_valid"]
                   else "rejected" if report.get("findings_error") else "none")
    if h["blocking"]:
        st.warning("Release blocked by: " + ", ".join(h["blocking"]))
    if report.get("error"):
        st.error(report["error"])


def findings_tab(report: dict) -> None:
    if report.get("findings"):
        f = report["findings"]
        st.markdown(f"**Summary:** {f['summary']}")
        st.markdown(f"**Recommended action:** {f['recommended_action']}")
        st.json(f, expanded=False)
    elif report.get("findings_error"):
        err = report["findings_error"]
        st.error(f"Findings rejected after {err['attempts']} attempts:\n\n"
                 + "\n".join(f"- {e}" for e in err["errors"]))
    else:
        st.info("No findings for this check.")


def events_tab(report: dict) -> None:
    path = report.get("event_log")
    events = _events(path, _mtime(path)) if path else []
    if not events:
        st.info("No event log for this check.")
        return
    types, agents = data.event_filter_options(events)
    left, right = st.columns(2)
    chosen_types = left.multiselect("Event types", types, key="event_types")
    chosen_agents = right.multiselect("Agents", agents, key="event_agents")
    rows = data.event_rows(events, chosen_types, chosen_agents)
    st.dataframe(rows, hide_index=True, width="stretch")
    with st.expander("Raw events"):
        st.json(events, expanded=False)


def usage_tab(report: dict) -> None:
    usage = (report.get("agent") or {}).get("usage") or {}
    st.dataframe(data.usage_rows(report), hide_index=True, width="stretch")
    st.caption(f"Source: {usage.get('source', '—')} · untracked tokens "
               f"(CLI calls outside the conversation, e.g. the session title): "
               f"{usage.get('untracked_tokens')} · consistent: {usage.get('consistent')}")


def main() -> None:
    st.set_page_config(page_title="Pre/Post-Check", layout="wide")
    root = data.data_dir()
    files = data.list_reports(root)
    if not files:
        st.info(f"No reports yet in {root / 'reports'}. Run `python -m agent precheck`.")
        st.stop()
    selected = sidebar(files)
    report, problems = _report(str(selected.path), selected.mtime)
    if report is None:
        st.error(f"Cannot read {selected.path.name}: {problems[0]}")
        st.stop()
    header(report, problems)
    devices, findings, events, usage, raw = st.tabs(
        ["Devices", "Findings", "Event log", "Usage", "Raw report"])
    with devices:
        st.dataframe(data.device_rows(report), hide_index=True, width="stretch")
    with findings:
        findings_tab(report)
    with events:
        events_tab(report)
    with usage:
        usage_tab(report)
    with raw:
        st.json(report, expanded=False)


main()
