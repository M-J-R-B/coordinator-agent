from agent.baseline import load_baseline, save_baseline
from tests.fakes import healthy_site, offline


def test_missing_baseline_is_none(tmp_path):
    assert load_baseline("STORE-001", tmp_path) is None


def test_save_then_reload_from_disk(tmp_path):
    devices = healthy_site(CAM_03=offline("CAM-03"))
    path = save_baseline("STORE-001", devices, "precheck-1", "2026-11-16T10:00:00Z", tmp_path)
    assert path.name == "STORE-001.json"
    loaded = load_baseline("STORE-001", tmp_path)
    assert loaded["check_id"] == "precheck-1"
    assert loaded["taken_at"] == "2026-11-16T10:00:00Z"
    assert loaded["devices"]["CAM-03"]["status"] == "offline"


def test_save_overwrites_previous_and_leaves_no_temp(tmp_path):
    save_baseline("STORE-001", healthy_site(), "precheck-1", "t1", tmp_path)
    save_baseline("STORE-001", healthy_site(), "precheck-2", "t2", tmp_path)
    assert load_baseline("STORE-001", tmp_path)["check_id"] == "precheck-2"
    assert [p.name for p in tmp_path.iterdir()] == ["STORE-001.json"]
