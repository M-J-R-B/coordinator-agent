import pytest

from mock_site import faults
from mock_site.poll import DEFAULT_LATENCY_MS, DeviceTimeout, poll_device
from mock_site.state import empty_state


def no_sleep(_seconds):
    pass


def poll(device_id, state):
    return poll_device(device_id, state, sleep=no_sleep)


def test_healthy_camera():
    reading = poll("CAM-01", empty_state())
    assert reading == {
        "device_id": "CAM-01",
        "type": "camera",
        "reachable": True,
        "latency_ms": DEFAULT_LATENCY_MS,
    }


def test_healthy_switch_reports_24_ports_with_labels():
    reading = poll("SW-01", empty_state())
    assert len(reading["ports"]) == 24
    assert reading["ports"][2] == {"port": 3, "state": "up", "label": "CAM-03"}
    assert reading["ports"][20] == {"port": 21, "state": "up", "label": None}


def test_offline_device_unreachable():
    state = faults.inject_offline(empty_state(), "POS-02")
    reading = poll("POS-02", state)
    assert reading["reachable"] is False
    assert reading["latency_ms"] is None


def test_unknown_device_raises_key_error():
    with pytest.raises(KeyError):
        poll("CAM-99", empty_state())


# --- cascade ---

def test_port_down_makes_attached_camera_unreachable():
    state = faults.inject_port_down(empty_state(), "SW-01", 3)
    assert poll("CAM-03", state)["reachable"] is False
    assert poll("CAM-02", state)["reachable"] is True


def test_port_down_shows_on_switch_but_switch_still_reachable():
    state = faults.inject_port_down(empty_state(), "SW-01", 3)
    reading = poll("SW-01", state)
    assert reading["reachable"] is True
    assert reading["ports"][2] == {"port": 3, "state": "down", "label": "CAM-03"}


def test_unreachable_camera_reading_does_not_reveal_cause():
    state = faults.inject_port_down(empty_state(), "SW-01", 3)
    assert set(poll("CAM-03", state)) == {"device_id", "type", "reachable", "latency_ms"}


def test_switch_offline_takes_down_all_attached_devices():
    state = faults.inject_offline(empty_state(), "SW-02")
    for pos in ["POS-01", "POS-02", "POS-03", "POS-04"]:
        assert poll(pos, state)["reachable"] is False
    assert poll("CAM-01", state)["reachable"] is True


def test_offline_switch_reports_no_ports():
    state = faults.inject_offline(empty_state(), "SW-01")
    assert "ports" not in poll("SW-01", state)


def test_switch_timeout_does_not_cascade():
    state = faults.inject_timeout(empty_state(), "SW-01")
    with pytest.raises(DeviceTimeout):
        poll("SW-01", state)
    assert poll("CAM-01", state)["reachable"] is True


def test_slow_switch_slows_attached_devices():
    calls = []
    state = faults.inject_slow(empty_state(), "SW-01", 800)
    reading = poll_device("CAM-03", state, sleep=calls.append)
    assert reading["latency_ms"] == 800 + DEFAULT_LATENCY_MS
    assert calls == [(800 + DEFAULT_LATENCY_MS) / 1000]


def test_slow_switch_and_slow_camera_add_up():
    state = faults.inject_slow(empty_state(), "SW-01", 800)
    state = faults.inject_slow(state, "CAM-03", 3000)
    assert poll("CAM-03", state)["latency_ms"] == 3800


def test_slow_switch_does_not_affect_other_switch_devices():
    state = faults.inject_slow(empty_state(), "SW-01", 800)
    assert poll("POS-01", state)["latency_ms"] == DEFAULT_LATENCY_MS


def test_unreachable_device_behind_slow_switch_has_no_latency():
    state = faults.inject_slow(empty_state(), "SW-01", 800)
    state = faults.inject_port_down(state, "SW-01", 3)
    assert poll("CAM-03", state)["latency_ms"] is None


def test_clearing_port_recovers_camera():
    state = faults.inject_port_down(empty_state(), "SW-01", 3)
    state = faults.clear_device(state, "SW-01")
    assert poll("CAM-03", state)["reachable"] is True


# --- slow / timeout ---

def test_slow_device_sleeps_and_reports_latency():
    calls = []
    state = faults.inject_slow(empty_state(), "POS-02", 3000)
    reading = poll_device("POS-02", state, sleep=calls.append)
    assert calls == [3.0]
    assert reading["latency_ms"] == 3000
    assert reading["reachable"] is True


def test_healthy_device_does_not_sleep():
    calls = []
    poll_device("POS-02", empty_state(), sleep=calls.append)
    assert calls == []


def test_timeout_raises():
    state = faults.inject_timeout(empty_state(), "CAM-01")
    with pytest.raises(DeviceTimeout):
        poll("CAM-01", state)


def test_latest_condition_is_what_poll_sees():
    """Fault list and poll agree: only the latest condition exists."""
    state = faults.inject_timeout(empty_state(), "CAM-01")
    state = faults.inject_offline(state, "CAM-01")
    assert state["faults"] == [{"type": "offline", "device": "CAM-01"}]
    assert poll("CAM-01", state)["reachable"] is False
