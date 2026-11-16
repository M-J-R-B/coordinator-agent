"""Per-check event log (CLAUDE.md "Event log"), one JSON object per line.

Each event is appended to data/events/<check_id>.jsonl the moment it happens,
so a crashed run still leaves a log up to the crash. Event types:
  check_started / check_finished   kind, model, decision, total cost, usage
  subagent_started / subagent_finished
  tool_call                        agent, tool, input, raw result, is_error
  turn_usage                       final token usage of one API turn, per agent
  hook_decision                    which hook allowed or denied which call, and why

Token usage comes from the CLI's own transcripts, read when the run ends. A
live probe showed the usage on streamed messages is a snapshot taken when the
turn starts (output_tokens 2 vs a final 585), and some subagent turns never
appear in the stream at all; the transcripts matched the SDK's model_usage
exactly.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from agent.storage import DATA_DIR

DEFAULT_EVENTS_DIR = DATA_DIR / "events"
COORDINATOR = "coordinator"
TOKEN_KEYS = {"input_tokens": "inputTokens", "cache_read_input_tokens": "cacheReadInputTokens",
              "cache_creation_input_tokens": "cacheCreationInputTokens",
              "output_tokens": "outputTokens"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def agent_name(hook_input: dict) -> str:
    """Subagent calls carry agent_type (verified live); the coordinator's don't."""
    return hook_input.get("agent_type") or COORDINATOR


class EventLog:
    def __init__(self, path: Path | None, check_id: str, clock=utc_now) -> None:
        self.path = Path(path) if path is not None else None
        self.check_id = check_id
        self.clock = clock
        self.events: list[dict] = []

    def emit(self, type_: str, **fields) -> dict:
        event = {"seq": len(self.events) + 1, "ts": self.clock(),
                 "check_id": self.check_id, "type": type_, **fields}
        self.events.append(event)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, default=str) + "\n")
        return event


class Transcripts:
    """Where the CLI writes this run's transcripts, as reported by hook inputs."""

    def __init__(self) -> None:
        self.main: str | None = None
        self.subagents: dict[str, str] = {}   # transcript path -> subagent name

    def note(self, data: dict) -> None:
        if data.get("transcript_path") and self.main is None:
            self.main = data["transcript_path"]
        if data.get("agent_transcript_path"):
            self.subagents[data["agent_transcript_path"]] = data.get("agent_type") or "unknown"


def make_tool_log_hooks(log: EventLog, transcripts: Transcripts):
    """PostToolUse / PostToolUseFailure for every tool: what was called, by whom, result."""
    def _emit(data: dict, result, is_error: bool) -> None:
        transcripts.note(data)
        log.emit("tool_call", agent=agent_name(data), tool=data.get("tool_name"),
                 tool_use_id=data.get("tool_use_id"), input=data.get("tool_input"),
                 result=result, is_error=is_error, duration_ms=data.get("duration_ms"))

    async def on_post(data, tool_use_id, context):
        _emit(data, data.get("tool_response"), is_error=False)
        return {}

    async def on_failure(data, tool_use_id, context):
        _emit(data, data.get("error"), is_error=True)
        return {}

    return on_post, on_failure


def make_lifecycle_hooks(log: EventLog, transcripts: Transcripts):
    async def on_start(data, tool_use_id, context):
        transcripts.note(data)
        log.emit("subagent_started", agent=data.get("agent_type"), agent_id=data.get("agent_id"))
        return {}

    async def on_stop(data, tool_use_id, context):
        transcripts.note(data)
        log.emit("subagent_finished", agent=data.get("agent_type"), agent_id=data.get("agent_id"),
                 last_message=data.get("last_assistant_message"))
        return {}

    return on_start, on_stop


def _read_turns(path: str, skip_sidechain: bool) -> list[dict] | None:
    """Assistant turns with usage, one per message id (the last entry wins)."""
    file = Path(path)
    if not file.exists():
        return None
    turns: dict[str, dict] = {}
    for line in file.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = entry.get("message") or {}
        if entry.get("type") != "assistant" or not message.get("usage"):
            continue
        if skip_sidechain and entry.get("isSidechain"):
            continue
        turns[message.get("id")] = {"message_id": message.get("id"), "model": message.get("model"),
                                    "stop_reason": message.get("stop_reason"),
                                    "turn_ts": entry.get("timestamp"), "usage": message["usage"]}
    return list(turns.values())


def log_turn_usage(log: EventLog, transcripts: Transcripts) -> tuple[dict, str]:
    """Emit turn_usage per API turn; return (token totals per agent, source)."""
    files = [(transcripts.main, COORDINATOR, True)] if transcripts.main else []
    files += [(path, agent, False) for path, agent in transcripts.subagents.items()]
    totals: dict[str, dict[str, int]] = {}
    read_any = False
    for path, agent, skip_sidechain in files:
        turns = _read_turns(path, skip_sidechain)
        if turns is None:
            continue
        read_any = True
        agent_totals = totals.setdefault(agent, {})
        for turn in turns:
            log.emit("turn_usage", agent=agent, **turn)
            for key in TOKEN_KEYS:
                agent_totals[key] = agent_totals.get(key, 0) + int(turn["usage"].get(key) or 0)
    return totals, ("transcripts" if read_any else "unavailable")


def untracked_tokens(tokens_by_agent: dict, model_usage: dict | None) -> dict | None:
    """SDK total minus the per-turn sum, per token kind.

    Positive: API calls the CLI makes outside the conversation, so they have no
    transcript turn. Seen live: the session-title call (~1,190 input, ~20 output).
    Negative would mean a turn was counted twice, which must never happen.
    """
    if not model_usage:
        return None
    return {ours: sum(int(m.get(sdk) or 0) for m in model_usage.values())
            - sum(t.get(ours, 0) for t in tokens_by_agent.values())
            for ours, sdk in TOKEN_KEYS.items()}
