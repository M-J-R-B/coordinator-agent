"""The panel writes the file the agent's tool reads, and shows what that tool returns."""
from mcp_server.checks import check_device
from mcp_server.server import _state_path
from mock_site.devices import INVENTORY
from site_ui import actions, view


def no_sleep(_seconds):
    pass


def test_panel_and_mcp_server_use_the_same_state_file(tmp_path, monkeypatch):
    monkeypatch.setenv(view.STATE_ENV, str(tmp_path / "site_state.json"))
    assert view.state_path() == _state_path(None)
    monkeypatch.delenv(view.STATE_ENV)
    assert view.state_path() == _state_path(None)


def test_panel_shows_what_the_tool_returns(tmp_path):
    path = tmp_path / "site_state.json"
    for result in (actions.inject(path, "port_down", "SW-01", port=3),
                   actions.inject(path, "slow", "CAM-06", ms=5000),
                   actions.inject(path, "slow", "SW-02", ms=300),
                   actions.inject(path, "timeout", "POS-04"),
                   actions.inject(path, "offline", "CAM-08")):
        assert result.ok, result.message
    model = view.site_model(path)
    # view polls via check_state; comparing with check_device pins view to the tool's
    # default deadline and the file format actions writes.
    for device_id in INVENTORY:
        tool = check_device(device_id, path, sleep=no_sleep)
        shown = model.devices[device_id]
        assert shown.status == tool.status, device_id
        assert shown.latency_ms == getattr(tool, "latency_ms", None), device_id
    statuses = {d: model.devices[d].display for d in ("CAM-03", "CAM-06", "POS-01", "POS-04", "CAM-08")}
    assert statuses == {"CAM-03": "offline", "CAM-06": "unknown", "POS-01": "slow",
                        "POS-04": "unknown", "CAM-08": "offline"}
