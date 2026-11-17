"""site_ui.actions: every change goes load -> one faults.* call -> atomic save."""
import pytest

from mock_site.state import empty_state, load_state
from site_ui import actions


@pytest.fixture
def path(tmp_path):
    return tmp_path / "site_state.json"


def faults_in(path):
    return load_state(path)["faults"]


def test_inject_offline_writes_the_file(path):
    result = actions.inject(path, "offline", "CAM-01")
    assert result.ok and "CAM-01" in result.message
    assert faults_in(path) == [{"type": "offline", "device": "CAM-01"}]


def test_inject_timeout(path):
    assert actions.inject(path, "timeout", "POS-02").ok
    assert faults_in(path) == [{"type": "timeout", "device": "POS-02"}]


def test_inject_slow(path):
    assert actions.inject(path, "slow", "CAM-06", ms=800).ok
    assert faults_in(path) == [{"type": "slow", "device": "CAM-06", "ms": 800}]


def test_port_down_then_up(path):
    result = actions.inject(path, "port_down", "SW-01", port=3)
    assert result.ok and "SW-01 port 3" in result.message
    assert faults_in(path) == [{"type": "port_down", "device": "SW-01", "port": 3}]
    assert actions.bring_port_up(path, "SW-01", 3).ok
    assert faults_in(path) == []


def test_bring_port_up_keeps_the_switch_condition(path):
    actions.inject(path, "slow", "SW-01", ms=800)
    actions.inject(path, "port_down", "SW-01", port=3)
    actions.inject(path, "port_down", "SW-01", port=4)
    actions.bring_port_up(path, "SW-01", 3)
    assert faults_in(path) == [{"type": "slow", "device": "SW-01", "ms": 800},
                               {"type": "port_down", "device": "SW-01", "port": 4}]


def test_clear_device(path):
    actions.inject(path, "offline", "CAM-01")
    actions.inject(path, "offline", "CAM-02")
    assert actions.clear_device(path, "CAM-01").ok
    assert faults_in(path) == [{"type": "offline", "device": "CAM-02"}]


@pytest.mark.parametrize("kind, device, kw", [
    ("offline", "CAM-99", {}),
    ("port_down", "CAM-01", {"port": 3}),
    ("port_down", "SW-01", {"port": 25}),
    ("port_down", "SW-01", {}),
    ("slow", "CAM-01", {"ms": 0}),
    ("slow", "CAM-01", {}),
    ("melt", "CAM-01", {}),
    ("port_down", "SW-01", {"port": "3"}),
    ("slow", "CAM-01", {"ms": 0.5}),
    ("slow", "CAM-01", {"ms": True}),
])
def test_bad_input_changes_nothing(path, kind, device, kw):
    actions.inject(path, "offline", "CAM-02")
    before = path.read_bytes()
    result = actions.inject(path, kind, device, **kw)
    assert not result.ok and result.message
    assert path.read_bytes() == before


def test_bad_input_on_missing_file_creates_nothing(path):
    assert not actions.inject(path, "offline", "CAM-99").ok
    assert not path.exists()


def test_bad_port_up_changes_nothing(path):
    assert not actions.bring_port_up(path, "CAM-01", 3).ok
    assert not path.exists()


def test_unreadable_file_blocks_actions(path):
    path.write_text("{not json", encoding="utf-8")
    result = actions.inject(path, "offline", "CAM-01")
    assert not result.ok and "Reset" in result.message
    assert path.read_text(encoding="utf-8") == "{not json"


def test_reset_overwrites_an_unreadable_file(path):
    path.write_text("{not json", encoding="utf-8")
    assert actions.reset(path).ok
    assert load_state(path) == empty_state()


def test_bring_port_up_rejects_a_non_int_port(path):
    actions.inject(path, "offline", "CAM-02")
    before = path.read_bytes()
    assert not actions.bring_port_up(path, "SW-01", "3").ok
    assert path.read_bytes() == before


@pytest.mark.parametrize("content", [
    "{}", "[]", "null",
    '{"site": "STORE-001", "faults": [{"type": "offline"}]}',
])
def test_wrong_shape_file_blocks_actions(path, content):
    path.write_text(content, encoding="utf-8")
    result = actions.inject(path, "offline", "CAM-01")
    assert not result.ok and "Reset" in result.message
    assert path.read_text(encoding="utf-8") == content


def test_failed_save_is_reported_not_raised(path, monkeypatch):
    def boom(*args, **kwargs):
        raise PermissionError("file in use")
    monkeypatch.setattr("site_ui.actions.save_state", boom)
    result = actions.inject(path, "offline", "CAM-01")
    assert not result.ok and "could not save" in result.message
    assert not actions.reset(path).ok


def test_reset_on_a_missing_file_creates_a_healthy_one(path):
    assert actions.reset(path).ok
    assert load_state(path) == empty_state()


def test_clear_device_on_a_switch_clears_its_ports(path):
    actions.inject(path, "port_down", "SW-01", port=3)
    actions.inject(path, "port_down", "SW-01", port=4)
    actions.inject(path, "slow", "SW-01", ms=800)
    assert actions.clear_device(path, "SW-01").ok
    assert faults_in(path) == []
