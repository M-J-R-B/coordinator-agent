"""Status mapping rules, tested without MCP."""
import pytest

from mcp_server import checks
from mcp_server.models import DeviceCheck, ToolFailure
from mock_site import faults
from mock_site.devices import INVENTORY
from mock_site.state import empty_state, save_state


@pytest.fixture
def state_path(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, empty_state())
    return path


def inject(path, fn, *args):
    from mock_site.state import load_state
    save_state(path, fn(load_state(path), *args))


def check(device_id, path, sleep_calls=None, timeout_ms=checks.DEFAULT_POLL_TIMEOUT_MS):
    calls = sleep_calls if sleep_calls is not None else []
    return checks.check_device(device_id, path, timeout_ms=timeout_ms, sleep=calls.append)


# --- list_devices ---

def test_list_all_devices():
    result = checks.list_devices()
    assert result.site == "STORE-001"
    assert len(result.devices) == 14


def test_list_devices_filtered_with_cabling():
    cams = checks.list_devices("camera").devices
    assert len(cams) == 8
    assert cams[2].device_id == "CAM-03"
    assert (cams[2].switch_id, cams[2].port) == ("SW-01", 3)


def test_switch_has_no_uplink_location():
    sw = checks.list_devices("switch").devices[0]
    assert sw.switch_id is None and sw.port is None


# --- device answered: not an error ---

def test_healthy_device_is_online(state_path):
    result = check("CAM-01", state_path)
    assert isinstance(result, DeviceCheck)
    assert result.status == "online"
    assert result.ports is None


def test_offline_device_is_a_valid_finding_not_an_error(state_path):
    inject(state_path, faults.inject_offline, "POS-02")
    result = check("POS-02", state_path)
    assert isinstance(result, DeviceCheck)
    assert result.status == "offline"
    assert result.latency_ms is None


def test_port_down_cascade_shows_offline(state_path):
    inject(state_path, faults.inject_port_down, "SW-01", 3)
    assert check("CAM-03", state_path).status == "offline"
    sw = check("SW-01", state_path)
    assert sw.status == "online"
    assert sw.ports[2].state == "down" and sw.ports[2].label == "CAM-03"


# --- tool failed: always unknown ---

def test_timeout_is_unknown_and_retryable(state_path):
    inject(state_path, faults.inject_timeout, "CAM-01")
    result = check("CAM-01", state_path)
    assert isinstance(result, ToolFailure)
    assert result.status == "unknown"
    assert result.error_category == "timeout"
    assert result.is_retryable is True


def test_slow_within_deadline_is_online_with_latency(state_path):
    calls = []
    inject(state_path, faults.inject_slow, "POS-02", 800)
    result = check("POS-02", state_path, calls)
    assert result.status == "online"
    assert result.latency_ms == 800
    assert calls == [0.8]


def test_slow_over_deadline_is_timeout_and_waits_only_the_deadline(state_path):
    calls = []
    inject(state_path, faults.inject_slow, "POS-02", 3000)
    result = check("POS-02", state_path, calls, timeout_ms=2000)
    assert isinstance(result, ToolFailure)
    assert result.error_category == "timeout"
    assert calls == [2.0]


def test_unknown_device_is_invalid_input_not_retryable(state_path):
    result = check("CAM-99", state_path)
    assert isinstance(result, ToolFailure)
    assert result.error_category == "invalid_input"
    assert result.is_retryable is False


def test_corrupt_state_file_is_internal_unknown(state_path):
    state_path.write_text("{not json", encoding="utf-8")
    result = check("CAM-01", state_path)
    assert isinstance(result, ToolFailure)
    assert result.status == "unknown"
    assert result.error_category == "internal"


def test_state_reloaded_on_every_check(state_path):
    assert check("CAM-05", state_path).status == "online"
    inject(state_path, faults.inject_offline, "CAM-05")
    assert check("CAM-05", state_path).status == "offline"


def no_sleep(_seconds):
    pass


def test_check_state_matches_check_device_for_every_device(tmp_path):
    state = empty_state()
    state = faults.inject_port_down(state, "SW-01", 3)
    state = faults.inject_slow(state, "CAM-06", 5000)
    state = faults.inject_timeout(state, "POS-02")
    path = tmp_path / "state.json"
    save_state(path, state)
    for device_id in INVENTORY:
        assert (checks.check_state(device_id, state, sleep=no_sleep)
                == checks.check_device(device_id, path, sleep=no_sleep))
