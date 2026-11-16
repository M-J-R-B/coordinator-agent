import pytest

from mock_site import faults
from mock_site.state import empty_state


def test_inject_offline():
    state = faults.inject_offline(empty_state(), "CAM-03")
    assert state["faults"] == [{"type": "offline", "device": "CAM-03"}]


def test_inject_is_idempotent():
    state = faults.inject_offline(empty_state(), "CAM-03")
    state = faults.inject_offline(state, "CAM-03")
    assert len(state["faults"]) == 1


def test_inject_port_down():
    state = faults.inject_port_down(empty_state(), "SW-01", 3)
    assert state["faults"] == [{"type": "port_down", "device": "SW-01", "port": 3}]


def test_port_down_rejects_non_switch():
    with pytest.raises(ValueError):
        faults.inject_port_down(empty_state(), "CAM-01", 3)


@pytest.mark.parametrize("port", [0, 25])
def test_port_down_rejects_bad_port(port):
    with pytest.raises(ValueError):
        faults.inject_port_down(empty_state(), "SW-01", port)


def test_inject_slow_replaces_previous_delay():
    state = faults.inject_slow(empty_state(), "POS-02", 1000)
    state = faults.inject_slow(state, "POS-02", 3000)
    assert state["faults"] == [{"type": "slow", "device": "POS-02", "ms": 3000}]


def test_slow_rejects_non_positive_ms():
    with pytest.raises(ValueError):
        faults.inject_slow(empty_state(), "POS-02", 0)


def test_inject_timeout():
    state = faults.inject_timeout(empty_state(), "CAM-01")
    assert state["faults"] == [{"type": "timeout", "device": "CAM-01"}]


def test_timeout_replaces_offline():
    state = faults.inject_offline(empty_state(), "CAM-01")
    state = faults.inject_timeout(state, "CAM-01")
    assert state["faults"] == [{"type": "timeout", "device": "CAM-01"}]


def test_offline_replaces_slow():
    state = faults.inject_slow(empty_state(), "POS-02", 3000)
    state = faults.inject_offline(state, "POS-02")
    assert state["faults"] == [{"type": "offline", "device": "POS-02"}]


def test_condition_replace_leaves_other_devices_alone():
    state = faults.inject_offline(empty_state(), "CAM-01")
    state = faults.inject_timeout(state, "CAM-02")
    assert len(state["faults"]) == 2


def test_port_down_kept_when_switch_goes_offline():
    state = faults.inject_port_down(empty_state(), "SW-01", 3)
    state = faults.inject_offline(state, "SW-01")
    assert {"type": "port_down", "device": "SW-01", "port": 3} in state["faults"]
    assert {"type": "offline", "device": "SW-01"} in state["faults"]


def test_several_ports_down_coexist():
    state = faults.inject_port_down(empty_state(), "SW-01", 3)
    state = faults.inject_port_down(state, "SW-01", 4)
    assert len(state["faults"]) == 2


def test_unknown_device_rejected():
    with pytest.raises(ValueError):
        faults.inject_offline(empty_state(), "CAM-99")


def test_inject_does_not_mutate_input():
    original = empty_state()
    faults.inject_offline(original, "CAM-01")
    assert original["faults"] == []


def test_clear_device_removes_all_its_faults():
    state = faults.inject_port_down(empty_state(), "SW-01", 3)
    state = faults.inject_port_down(state, "SW-01", 4)
    state = faults.inject_offline(state, "CAM-05")
    state = faults.clear_device(state, "SW-01")
    assert state["faults"] == [{"type": "offline", "device": "CAM-05"}]


def test_reset_removes_everything():
    state = faults.inject_offline(empty_state(), "CAM-05")
    assert faults.reset(state)["faults"] == []
