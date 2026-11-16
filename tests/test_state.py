import json

from mock_site.state import empty_state, load_state, save_state


def test_missing_file_means_no_faults(tmp_path):
    assert load_state(tmp_path / "nope.json") == empty_state()


def test_save_then_load_round_trip(tmp_path):
    path = tmp_path / "sub" / "state.json"
    state = {"site": "STORE-001", "faults": [{"type": "offline", "device": "CAM-01"}]}
    save_state(path, state)
    assert load_state(path) == state
    assert json.loads(path.read_text()) == state


def test_save_leaves_no_temp_file(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, empty_state())
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
