"""UI data layer: pure Python, no Streamlit, so it runs on every supported Python."""
import json

import pytest

from tests.ui_site import build_data_dir
from ui import data


@pytest.fixture
def site(tmp_path):
    return tmp_path, build_data_dir(tmp_path)


def by_id(files):
    return {f.check_id: f for f in files}


def test_data_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv(data.DATA_ENV, str(tmp_path))
    assert data.data_dir() == tmp_path
    monkeypatch.delenv(data.DATA_ENV)
    assert data.data_dir().name == "data"


def test_list_reports_newest_first_with_invalid_flagged(site):
    root, made = site
    files = data.list_reports(root)
    ids = [f.check_id for f in files]
    assert ids[0] == made["invalid"]["check_id"]          # year 2999: newest
    assert ids.index(made["release"]["check_id"]) < ids.index(made["hold"]["check_id"])
    assert by_id(files)[made["invalid"]["check_id"]].invalid is True
    assert by_id(files)[made["hold"]["check_id"]].invalid is False


def test_list_reports_empty_or_missing_dir(tmp_path):
    assert data.list_reports(tmp_path / "nope") == []


def test_load_valid_report_has_no_errors(site):
    root, made = site
    report, errors = data.load_report(by_id(data.list_reports(root))[made["hold"]["check_id"]].path)
    assert report["decision"] == "hold"
    assert errors == []


def test_load_invalid_report_shows_schema_and_saved_errors(site):
    root, made = site
    path = by_id(data.list_reports(root))[made["invalid"]["check_id"]].path
    report, errors = data.load_report(path)
    assert report["decision"] == "hold"
    assert any("release-ish" in e for e in errors)


def test_unreadable_report_is_reported_not_raised(site):
    root, _ = site
    path = by_id(data.list_reports(root))["precheck-00000000T000000000000Z"].path
    report, errors = data.load_report(path)
    assert report is None
    assert errors[0].startswith("unreadable")


def test_headline_for_hold_postcheck(site):
    _, made = site
    h = data.headline(made["hold"])
    assert h["decision"] == "HOLD"
    assert h["blocking"] == ["CAM-03"]
    assert h["devices_checked"] == 14
    assert h["findings_valid"] is True
    assert h["cost_usd"] == pytest.approx(0.01)


def test_headline_for_precheck(site):
    _, made = site
    assert data.headline(made["precheck"])["decision"] == "BASELINE SAVED"


def test_device_rows_postcheck_show_classification_and_cause(site):
    _, made = site
    rows = {r["device_id"]: r for r in data.device_rows(made["hold"])}
    assert rows["CAM-03"]["classification"] == "new_offline"
    assert rows["CAM-03"]["likely_cause"] == "SW-01 port 3 down"
    assert rows["CAM-01"]["classification"] == "ok"


def test_device_rows_precheck(site):
    _, made = site
    rows = data.device_rows(made["precheck"])
    assert len(rows) == 14 and {r["status"] for r in rows} == {"online"}


def test_events_load_and_filter(site):
    _, made = site
    events = data.load_events(made["hold"]["event_log"])
    rows = data.event_rows(events)
    assert rows[0]["type"] == "check_started" and rows[-1]["type"] == "check_finished"
    gate = data.event_rows(events, types=["hook_decision"], agents=["coordinator"])
    assert gate and all(r["type"] == "hook_decision" and r["agent"] == "coordinator" for r in gate)
    assert any(r["decision"] == "deny" for r in gate)
    checks = data.event_rows(events, types=["tool_call"], agents=["cctv-checker"])
    assert len(checks) == 8


def test_event_filter_options(site):
    _, made = site
    types, agents = data.event_filter_options(data.load_events(made["hold"]["event_log"]))
    assert "turn_usage" in types and "tool_call" in types
    assert {"coordinator", "cctv-checker", "network-checker", "pos-checker"} <= set(agents)


def test_bad_event_lines_skipped(tmp_path):
    path = tmp_path / "e.jsonl"
    path.write_text('{"seq": 1, "type": "check_started"}\nnot json\n', encoding="utf-8")
    assert [e["type"] for e in data.load_events(path)] == ["check_started"]
    assert data.load_events(tmp_path / "missing.jsonl") == []


def test_usage_rows(site):
    _, made = site
    rows = {r["agent"]: r for r in data.usage_rows(made["hold"])}
    assert rows["coordinator"]["output_tokens"] == 40
    assert rows["pos-checker"]["output_tokens"] == 10


def test_label(site):
    root, made = site
    rf = by_id(data.list_reports(root))[made["hold"]["check_id"]]
    assert data.label(rf, made["hold"]).startswith("🔴 HOLD · postcheck")
    rf_inv = by_id(data.list_reports(root))[made["invalid"]["check_id"]]
    assert "⚠ invalid" in data.label(rf_inv, made["invalid"])
    assert "unreadable" in data.label(rf, None)


def test_rows_are_json_serialisable(site):
    _, made = site
    json.dumps(data.device_rows(made["hold"]) + data.event_rows(
        data.load_events(made["hold"]["event_log"])))
