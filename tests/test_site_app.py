"""The site control panel, run headless with AppTest. Skipped without Streamlit."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from mock_site.state import empty_state, load_state  # noqa: E402
from site_ui import actions, view  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "site_ui" / "app.py")


@pytest.fixture
def state(tmp_path, monkeypatch):
    path = tmp_path / "site_state.json"
    monkeypatch.setenv(view.STATE_ENV, str(path))
    return path


def run_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception, at.exception
    return at


def click(at, key) -> AppTest:
    at.button(key=key).click().run()
    assert not at.exception, at.exception
    return at


def test_draws_the_topology(state):
    at = run_app()
    keys = {b.key for b in at.button}
    assert {"dev-SW-01", "dev-SW-02", "dev-CAM-08", "dev-POS-04",
            "port-SW-01-1", "port-SW-02-24"} <= keys
    assert at.button(key="dev-CAM-01").label == "🟢 CAM-01"


def test_take_port_down_turns_its_camera_red(state):
    at = click(run_app(), "port-SW-01-3")
    click(at, "act-port-down")
    assert at.button(key="dev-CAM-03").label == "🔴 CAM-03"
    assert at.button(key="port-SW-01-3").label == "🔴3"
    assert load_state(state)["faults"] == [{"type": "port_down", "device": "SW-01", "port": 3}]


def test_bring_port_up(state):
    actions.inject(state, "port_down", "SW-01", port=3)
    at = click(run_app(), "port-SW-01-3")
    click(at, "act-port-up")
    assert load_state(state)["faults"] == []
    assert at.button(key="dev-CAM-03").label == "🟢 CAM-03"


def test_set_slow_uses_the_ms_input(state):
    at = click(run_app(), "dev-CAM-06")
    at.number_input(key="slow-ms").set_value(5000).run()
    click(at, "act-slow")
    assert load_state(state)["faults"] == [{"type": "slow", "device": "CAM-06", "ms": 5000}]
    assert at.button(key="dev-CAM-06").label == "⚪ CAM-06 unknown"   # past the 2000ms deadline


def test_offline_then_clear(state):
    at = click(run_app(), "dev-POS-02")
    click(at, "act-offline")
    assert at.button(key="dev-POS-02").label == "🔴 POS-02"
    click(at, "act-clear")
    assert load_state(state)["faults"] == []


def test_reset_needs_confirmation(state):
    actions.inject(state, "offline", "CAM-01")
    at = run_app()
    assert at.button(key="reset").disabled
    at.checkbox(key="reset-confirm").check().run()
    click(at, "reset")
    assert load_state(state)["faults"] == []
    assert at.checkbox(key="reset-confirm").value is False


def test_unreadable_file_hides_fault_controls_and_offers_overwrite(state):
    state.write_text("{not json", encoding="utf-8")
    at = run_app()
    assert at.error
    assert len(at.error) == 1
    keys = {b.key for b in at.button}
    assert not [k for k in keys if k.startswith(("act-", "port-", "dev-"))]
    assert at.button(key="reset").label == "Overwrite unreadable file with a healthy site"
    at.checkbox(key="reset-confirm").check().run()
    click(at, "reset")
    assert load_state(state) == empty_state()
    assert at.button(key="dev-CAM-01").label == "🟢 CAM-01"


def test_cli_change_appears_on_next_run(state):
    at = run_app()
    actions.inject(state, "offline", "CAM-05")   # as the CLI would
    at.run()
    assert at.button(key="dev-CAM-05").label == "🔴 CAM-05"


def test_selection_survives_a_rerun(state):
    at = click(run_app(), "dev-CAM-02")
    at.run()
    assert at.button(key="act-offline")


def test_timeout_button(state):
    at = click(run_app(), "dev-POS-01")
    click(at, "act-timeout")
    assert load_state(state)["faults"] == [{"type": "timeout", "device": "POS-01"}]
    assert at.button(key="dev-POS-01").label == "⚪ POS-01 unknown"


def test_failed_action_leaves_the_file_unchanged(state):
    at = click(run_app(), "dev-CAM-01")
    state.write_text("{not json", encoding="utf-8")
    click(at, "act-offline")
    assert at.error
    assert len(at.error) == 1
    assert state.read_text(encoding="utf-8") == "{not json"


def test_switch_clear_label_mentions_ports(state):
    at = click(run_app(), "dev-SW-01")
    assert at.button(key="act-clear").label == "Clear SW-01 (also brings its ports up)"


def test_selecting_clears_the_last_message_and_disarms_reset(state):
    at = click(run_app(), "dev-CAM-01")
    click(at, "act-offline")
    assert any("CAM-01 set offline" in s.value for s in at.success)
    at.checkbox(key="reset-confirm").check().run()
    click(at, "dev-CAM-02")
    assert not at.success
    assert at.checkbox(key="reset-confirm").value is False


def test_selected_button_is_primary(state):
    at = click(run_app(), "port-SW-01-3")
    assert at.button(key="port-SW-01-3").proto.type == "primary"
    assert at.button(key="port-SW-01-4").proto.type != "primary"
