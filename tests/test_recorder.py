import json

from agent.recorder import Recorder
from tests.fakes import failure, offline, online, result_message


def test_success_response_json_string_recorded():
    r = Recorder()
    r.record("CAM-01", json.dumps(online("CAM-01")), is_error=False)
    assert r.results["CAM-01"]["status"] == "online"
    assert r.check_calls == 1


def test_offline_kept_as_offline():
    r = Recorder()
    r.record("POS-02", json.dumps(offline("POS-02")), is_error=False)
    assert r.results["POS-02"]["status"] == "offline"


def test_dict_and_content_list_responses_also_accepted():
    r = Recorder()
    r.record("CAM-01", online("CAM-01"), is_error=False)
    r.record("CAM-02", [{"type": "text", "text": json.dumps(offline("CAM-02"))}], is_error=False)
    assert r.results["CAM-01"]["status"] == "online"
    assert r.results["CAM-02"]["status"] == "offline"


def test_failure_payload_kept_with_category():
    r = Recorder()
    r.record("CAM-01", json.dumps(failure("CAM-01")), is_error=True)
    assert r.results["CAM-01"]["status"] == "unknown"
    assert r.results["CAM-01"]["error_category"] == "timeout"


def test_latest_result_wins_after_retry():
    r = Recorder()
    r.record("CAM-01", json.dumps(failure("CAM-01")), is_error=True)
    r.record("CAM-01", json.dumps(online("CAM-01")), is_error=False)
    assert r.results["CAM-01"]["status"] == "online"
    assert r.check_calls == 2


def test_plain_text_error_is_unknown_internal():
    """E.g. the MCP server died or a call was denied: no JSON at all."""
    r = Recorder()
    r.record("CAM-01", "MCP server disconnected", is_error=True)
    assert r.results["CAM-01"]["status"] == "unknown"
    assert r.results["CAM-01"]["error_category"] == "internal"


def test_error_can_never_count_as_online():
    r = Recorder()
    r.record("CAM-01", json.dumps(online("CAM-01")), is_error=True)
    assert r.results["CAM-01"]["status"] == "unknown"


def test_result_message_captured_from_stream():
    r = Recorder()
    r.feed(result_message("Done, CAM-03 offline."))
    assert r.final.result == "Done, CAM-03 offline."


def test_complete_fills_unchecked_devices_as_unknown():
    r = Recorder()
    r.record("CAM-01", json.dumps(online("CAM-01")), is_error=False)
    devices = r.complete()
    assert len(devices) == 14
    assert devices["POS-04"]["status"] == "unknown"
    assert devices["POS-04"]["error_category"] == "not_checked"
    assert devices["POS-04"]["type"] == "pos"


def test_complete_ignores_devices_not_at_site():
    r = Recorder()
    r.record("CAM-99", json.dumps(failure("CAM-99", "invalid_input", False)), is_error=True)
    assert "CAM-99" not in r.complete()
