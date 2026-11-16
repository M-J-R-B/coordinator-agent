import pytest

from agent.diff import classify, diff
from tests.fakes import failure, healthy_site, offline, online


@pytest.mark.parametrize("before,after,expected", [
    ("online", "online", "ok"),
    ("offline", "offline", "pre-existing"),
    ("offline", "online", "recovered"),
    ("online", "offline", "new_offline"),
    ("online", "unknown", "unknown"),
    ("offline", "unknown", "unknown"),
    ("unknown", "unknown", "unknown"),
    ("unknown", "offline", "new_offline"),
    ("unknown", "online", "ok"),
])
def test_classify(before, after, expected):
    assert classify(before, after) == expected


def by_id(result):
    return {d["device_id"]: d for d in result["devices"]}


def test_all_ok_allows_release():
    result = diff(healthy_site(), healthy_site())
    assert result["release_allowed"] is True
    assert result["blocking"] == []


def test_pre_existing_offline_does_not_block():
    before = healthy_site(CAM_05=offline("CAM-05"))
    result = diff(before, before)
    assert by_id(result)["CAM-05"]["classification"] == "pre-existing"
    assert result["release_allowed"] is True


def test_new_offline_blocks():
    result = diff(healthy_site(), healthy_site(POS_02=offline("POS-02")))
    assert result["release_allowed"] is False
    assert result["blocking"] == ["POS-02"]


def test_unknown_blocks():
    result = diff(healthy_site(), healthy_site(CAM_01=failure("CAM-01")))
    assert result["release_allowed"] is False
    assert by_id(result)["CAM-01"]["classification"] == "unknown"


def test_device_missing_from_baseline_treated_as_unknown_before():
    before = healthy_site()
    del before["CAM-02"]
    result = diff(before, healthy_site(CAM_02=offline("CAM-02")))
    assert by_id(result)["CAM-02"]["baseline_status"] == "unknown"
    assert by_id(result)["CAM-02"]["classification"] == "new_offline"


def test_new_port_down_reported_with_likely_cause():
    after = healthy_site(SW_01=online("SW-01", ports_down=(3,)), CAM_03=offline("CAM-03"))
    result = diff(healthy_site(), after)
    assert result["new_ports_down"] == [{"switch_id": "SW-01", "port": 3, "label": "CAM-03"}]
    assert by_id(result)["CAM-03"]["likely_cause"] == "SW-01 port 3 down"
    assert result["blocking"] == ["CAM-03"]


def test_port_already_down_in_baseline_is_not_new():
    sw = online("SW-01", ports_down=(3,))
    before = healthy_site(SW_01=sw, CAM_03=offline("CAM-03"))
    result = diff(before, before)
    assert result["new_ports_down"] == []
    assert by_id(result)["CAM-03"]["classification"] == "pre-existing"


def test_port_diff_skipped_when_switch_not_readable():
    after = healthy_site(SW_01=failure("SW-01"))
    result = diff(healthy_site(), after)
    assert result["new_ports_down"] == []
    assert result["blocking"] == ["SW-01"]
