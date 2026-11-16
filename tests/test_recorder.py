from agent.recorder import Recorder
from tests.fakes import (failure, offline, online, result_message, tool_result,
                         tool_use)


def feed(recorder, *messages):
    for m in messages:
        recorder.feed(m)


def test_records_tool_results_by_device():
    r = Recorder()
    feed(r, tool_use("a", "CAM-01"), tool_result("a", online("CAM-01")))
    assert r.results["CAM-01"]["status"] == "online"


def test_offline_result_is_kept_as_offline():
    r = Recorder()
    feed(r, tool_use("a", "POS-02"), tool_result("a", offline("POS-02")))
    assert r.results["POS-02"]["status"] == "offline"


def test_latest_result_wins_after_retry():
    r = Recorder()
    feed(r, tool_use("a", "CAM-01"), tool_result("a", failure("CAM-01"), is_error=True),
         tool_use("b", "CAM-01"), tool_result("b", online("CAM-01")))
    assert r.results["CAM-01"]["status"] == "online"
    assert r.check_calls == 2


def test_parallel_calls_matched_by_tool_use_id():
    r = Recorder()
    feed(r, tool_use("a", "CAM-01"), tool_use("b", "CAM-02"),
         tool_result("b", offline("CAM-02")), tool_result("a", online("CAM-01")))
    assert r.results["CAM-01"]["status"] == "online"
    assert r.results["CAM-02"]["status"] == "offline"


def test_unparseable_error_result_is_unknown():
    """E.g. the SDK reports a denied call or a dead MCP server as plain text."""
    r = Recorder()
    feed(r, tool_use("a", "CAM-01"), tool_result("a", "MCP server disconnected", is_error=True))
    assert r.results["CAM-01"]["status"] == "unknown"
    assert r.results["CAM-01"]["error_category"] == "internal"


def test_is_error_overrides_claimed_status():
    """A failed call can never count as online, whatever its text says."""
    r = Recorder()
    feed(r, tool_use("a", "CAM-01"), tool_result("a", online("CAM-01"), is_error=True))
    assert r.results["CAM-01"]["status"] == "unknown"


def test_result_for_other_tools_ignored():
    r = Recorder()
    feed(r, tool_use("a", "CAM-01", name="mcp__devices__list_devices"),
         tool_result("a", {"site": "STORE-001", "devices": []}))
    assert r.results == {}


def test_result_message_captured():
    r = Recorder()
    feed(r, result_message("Done, CAM-03 offline."))
    assert r.final.result == "Done, CAM-03 offline."


def test_complete_fills_unchecked_devices_as_unknown():
    r = Recorder()
    feed(r, tool_use("a", "CAM-01"), tool_result("a", online("CAM-01")))
    devices = r.complete()
    assert len(devices) == 14
    assert devices["CAM-01"]["status"] == "online"
    assert devices["POS-04"]["status"] == "unknown"
    assert devices["POS-04"]["error_category"] == "not_checked"
    assert devices["POS-04"]["type"] == "pos"


def test_complete_ignores_devices_not_at_site():
    r = Recorder()
    feed(r, tool_use("a", "CAM-99"), tool_result("a", failure("CAM-99", "invalid_input", False),
                                                  is_error=True))
    assert "CAM-99" not in r.complete()
