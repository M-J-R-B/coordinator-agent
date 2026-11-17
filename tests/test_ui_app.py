"""The Streamlit app, run headless with AppTest. Skipped where Streamlit isn't installed
(the [ui] extra installs it only on Python 3.11+)."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.ui_site import build_data_dir  # noqa: E402
from ui import data  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "ui" / "app.py")


@pytest.fixture
def made(tmp_path, monkeypatch):
    monkeypatch.setenv(data.DATA_ENV, str(tmp_path))
    return build_data_dir(tmp_path)


def run_app(check_id=None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30).run()
    if check_id:
        at.selectbox(key="check").select(check_id).run()
    assert not at.exception, at.exception
    return at


def metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


def text(at) -> str:
    return " ".join(str(e.value) for e in [*at.markdown, *at.title, *at.header,
                                           *at.subheader, *at.caption, *at.error,
                                           *at.warning, *at.success, *at.info])


def test_app_starts_without_errors_and_lists_checks(made):
    at = run_app()
    options = at.selectbox(key="check").options
    assert len(options) == 5   # precheck, 2 postchecks, invalid, unreadable


def test_hold_postcheck_shows_decision_blocking_and_cause(made):
    at = run_app(made["hold"]["check_id"])
    assert metric(at, "Decision") == "HOLD"
    assert metric(at, "Blocking") == "1"
    assert "CAM-03" in text(at)
    devices = at.dataframe[0].value
    cam3 = devices[devices["device_id"] == "CAM-03"].iloc[0]
    assert cam3["likely_cause"] == "SW-01 port 3 down"


def test_release_postcheck(made):
    at = run_app(made["release"]["check_id"])
    assert metric(at, "Decision") == "RELEASE"


def test_invalid_report_is_flagged(made):
    at = run_app(made["invalid"]["check_id"])
    assert "release-ish" in text(at)
    assert at.error, "an invalid report must be shown as an error"


def test_unreadable_report_does_not_crash(made):
    at = run_app("precheck-00000000T000000000000Z")
    assert at.error


def test_event_log_filter(made):
    at = run_app(made["hold"]["check_id"])
    at.multiselect(key="event_types").set_value(["hook_decision"]).run()
    events = at.dataframe[1].value   # tables in order: devices, events, usage
    assert set(events["type"]) == {"hook_decision"}


def test_empty_data_dir_shows_hint(tmp_path, monkeypatch):
    monkeypatch.setenv(data.DATA_ENV, str(tmp_path))
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert "No reports" in text(at)
