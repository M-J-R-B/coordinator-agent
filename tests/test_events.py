import json

import pytest

from agent.events import (EventLog, Transcripts, agent_name, log_turn_usage,
                          make_lifecycle_hooks, make_tool_log_hooks, untracked_tokens)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def fixed_clock():
    return "2026-11-16T10:00:00+00:00"


@pytest.fixture
def log(tmp_path):
    return EventLog(tmp_path / "events" / "c1.jsonl", "c1", clock=fixed_clock)


def lines(log):
    return [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]


# --- EventLog ---

def test_emit_appends_jsonl_with_seq_ts_and_check_id(log):
    log.emit("check_started", kind="precheck")
    log.emit("check_finished", total_cost_usd=0.01)
    events = lines(log)
    assert [e["seq"] for e in events] == [1, 2]
    assert events[0] == {"seq": 1, "ts": fixed_clock(), "check_id": "c1",
                         "type": "check_started", "kind": "precheck"}
    assert log.events == events


def test_log_without_path_keeps_events_in_memory():
    log = EventLog(None, "c1", clock=fixed_clock)
    log.emit("check_started")
    assert log.events[0]["type"] == "check_started"


def test_agent_name_from_hook_input():
    assert agent_name({"agent_type": "pos-checker"}) == "pos-checker"
    assert agent_name({}) == "coordinator"


# --- tool calls ---

@pytest.mark.anyio
async def test_tool_call_logged_with_agent_input_raw_result(log):
    on_post, _ = make_tool_log_hooks(log, Transcripts())
    data = {"tool_name": "mcp__devices__check_device", "tool_input": {"device_id": "CAM-01"},
            "tool_use_id": "t1", "tool_response": '{"status":"online"}', "duration_ms": 10,
            "agent_type": "cctv-checker", "agent_id": "a1"}
    assert await on_post(data, "t1", None) == {}
    event = log.events[0]
    assert event["type"] == "tool_call"
    assert event["agent"] == "cctv-checker"
    assert event["input"] == {"device_id": "CAM-01"}
    assert event["result"] == '{"status":"online"}'
    assert event["is_error"] is False
    assert event["duration_ms"] == 10


@pytest.mark.anyio
async def test_failed_tool_call_logged_as_error(log):
    _, on_failure = make_tool_log_hooks(log, Transcripts())
    await on_failure({"tool_name": "mcp__devices__check_device", "tool_input": {"device_id": "CAM-02"},
                      "tool_use_id": "t2", "error": '{"status":"unknown"}'}, "t2", None)
    event = log.events[0]
    assert event["is_error"] is True
    assert event["result"] == '{"status":"unknown"}'
    assert event["agent"] == "coordinator"


# --- subagent lifecycle ---

@pytest.mark.anyio
async def test_subagent_start_and_finish(log):
    on_start, on_stop = make_lifecycle_hooks(log, Transcripts())
    await on_start({"agent_id": "a1", "agent_type": "pos-checker"}, None, None)
    await on_stop({"agent_id": "a1", "agent_type": "pos-checker",
                   "last_assistant_message": "POS-01 online"}, None, None)
    assert [e["type"] for e in log.events] == ["subagent_started", "subagent_finished"]
    assert log.events[1]["agent"] == "pos-checker"
    assert log.events[1]["last_message"] == "POS-01 online"


# --- transcript paths are collected from hook inputs ---

@pytest.mark.anyio
async def test_hooks_collect_transcript_paths(log):
    transcripts = Transcripts()
    on_post, _ = make_tool_log_hooks(log, transcripts)
    _, on_stop = make_lifecycle_hooks(log, transcripts)
    await on_post({"tool_name": "Agent", "transcript_path": "main.jsonl"}, "t", None)
    await on_stop({"agent_type": "cctv-checker", "transcript_path": "main.jsonl",
                   "agent_transcript_path": "sub-1.jsonl"}, None, None)
    assert transcripts.main == "main.jsonl"
    assert transcripts.subagents == {"sub-1.jsonl": "cctv-checker"}


# --- token usage per turn, from the CLI transcripts ---

def entry(message_id, output, sidechain=False, inp=2, cache_read=100, ts="2026-11-16T10:00:01Z"):
    return {"type": "assistant", "isSidechain": sidechain, "timestamp": ts,
            "message": {"id": message_id, "model": "claude-haiku-5-5", "stop_reason": "tool_use",
                        "usage": {"input_tokens": inp, "cache_read_input_tokens": cache_read,
                                  "cache_creation_input_tokens": 0, "output_tokens": output}}}


def write(path, *entries):
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return str(path)


def test_turn_usage_per_agent_from_transcripts(log, tmp_path):
    transcripts = Transcripts()
    transcripts.main = write(tmp_path / "main.jsonl", entry("m1", 585),
                             {"type": "user", "message": {"content": "x"}}, entry("m2", 33))
    transcripts.subagents[write(tmp_path / "sub.jsonl", entry("s1", 306, sidechain=True))] = \
        "network-checker"
    tokens, source = log_turn_usage(log, transcripts)
    turns = [e for e in log.events if e["type"] == "turn_usage"]
    assert [(t["agent"], t["message_id"]) for t in turns] == [
        ("coordinator", "m1"), ("coordinator", "m2"), ("network-checker", "s1")]
    assert turns[0]["usage"]["output_tokens"] == 585
    assert turns[0]["turn_ts"] == "2026-11-16T10:00:01Z"
    assert turns[0]["model"] == "claude-haiku-5-5"
    assert source == "transcripts"
    assert tokens["coordinator"]["output_tokens"] == 618
    assert tokens["network-checker"]["output_tokens"] == 306


def test_turn_split_over_entries_counted_once_using_last(log, tmp_path):
    """The CLI writes one API turn as several entries (one per content block)."""
    transcripts = Transcripts()
    transcripts.main = write(tmp_path / "main.jsonl", entry("m1", 2), entry("m1", 585))
    tokens, _ = log_turn_usage(log, transcripts)
    assert len([e for e in log.events if e["type"] == "turn_usage"]) == 1
    assert tokens["coordinator"]["output_tokens"] == 585


def test_sidechain_entries_in_main_transcript_skipped(log, tmp_path):
    """Subagent turns are counted from their own file, never twice."""
    transcripts = Transcripts()
    transcripts.main = write(tmp_path / "main.jsonl", entry("m1", 10), entry("s1", 99, sidechain=True))
    tokens, _ = log_turn_usage(log, transcripts)
    assert tokens == {"coordinator": {"input_tokens": 2, "cache_read_input_tokens": 100,
                                      "cache_creation_input_tokens": 0, "output_tokens": 10}}


def test_missing_transcripts_mean_usage_unavailable(log, tmp_path):
    transcripts = Transcripts()
    transcripts.main = str(tmp_path / "gone.jsonl")
    assert log_turn_usage(log, transcripts) == ({}, "unavailable")
    assert log.events == []


TOKENS = {"coordinator": {"input_tokens": 4, "cache_read_input_tokens": 10,
                          "cache_creation_input_tokens": 5, "output_tokens": 50},
          "pos-checker": {"input_tokens": 6, "cache_read_input_tokens": 0,
                          "cache_creation_input_tokens": 1, "output_tokens": 7}}


def sdk_usage(inp=10, read=10, create=6, out=57):
    return {"claude-haiku-5-5": {"inputTokens": inp, "cacheReadInputTokens": read,
                                 "cacheCreationInputTokens": create, "outputTokens": out}}


def test_untracked_tokens_zero_when_turns_add_up_to_sdk():
    assert untracked_tokens(TOKENS, sdk_usage()) == {
        "input_tokens": 0, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0, "output_tokens": 0}


def test_untracked_tokens_show_cli_calls_outside_the_conversation():
    """E.g. the CLI's session-title call: in model_usage, but no transcript turn (seen live)."""
    gap = untracked_tokens(TOKENS, sdk_usage(inp=1198, out=77))
    assert gap["input_tokens"] == 1188 and gap["output_tokens"] == 20


def test_untracked_tokens_negative_means_double_counting():
    assert untracked_tokens(TOKENS, sdk_usage(out=40))["output_tokens"] == -17


def test_untracked_tokens_unknown_without_sdk_usage():
    assert untracked_tokens(TOKENS, None) is None
