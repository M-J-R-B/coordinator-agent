"""A scripted stand-in for the Agent SDK CLI, so agent tests never call a model.

Like the real CLI (verified by a live probe), it fires PreToolUse before a
tool, PostToolUse after a success, PostToolUseFailure after an isError
result (with our JSON payload as the `error` string), and passes agent_id only
for subagent calls. A PreToolUse deny or a tool missing from allowed_tools
stops the call.
"""
import itertools
import json
import re
from pathlib import Path
from dataclasses import dataclass, field

from claude_agent_sdk import AssistantMessage, ResultMessage
from mcp import types as mcp_types

from mock_site.devices import INVENTORY, PORT_COUNT, port_label

CHECK_TOOL = "mcp__devices__check_device"
TYPES = {d.device_id: d.type for d in INVENTORY.values()}
AGENT_FOR_TYPE = {"camera": "cctv-checker", "switch": "network-checker", "pos": "pos-checker"}
SUBAGENTS = list(AGENT_FOR_TYPE.values())
_ids = itertools.count()


# --- device payloads, exactly as the MCP server returns them ---

def ports(*down: int, switch: str = "SW-01") -> list[dict]:
    return [{"port": p, "state": "down" if p in down else "up", "label": port_label(switch, p)}
            for p in range(1, PORT_COUNT + 1)]


def online(device_id: str, ports_down: tuple[int, ...] = ()) -> dict:
    payload = {"device_id": device_id, "type": TYPES[device_id], "status": "online",
               "latency_ms": 5, "ports": None}
    if TYPES[device_id] == "switch":
        payload["ports"] = ports(*ports_down, switch=device_id)
    return payload


def offline(device_id: str) -> dict:
    return {"device_id": device_id, "type": TYPES[device_id], "status": "offline",
            "latency_ms": None, "ports": None}


def failure(device_id: str, category: str = "timeout", retryable: bool = True) -> dict:
    return {"device_id": device_id, "status": "unknown", "error_category": category,
            "is_retryable": retryable, "message": f"{category} on {device_id}"}


def healthy_site(**overrides: dict) -> dict[str, dict]:
    """Payload per device; pass e.g. CAM_03=offline("CAM-03") to override."""
    site = {d: online(d) for d in INVENTORY}
    for key, payload in overrides.items():
        site[key.replace("_", "-")] = payload
    return site


def result_message(text: str = "All checked.", is_error: bool = False,
                   subtype: str = "success", model_usage: dict | None = None,
                   structured_output: dict | None = None,
                   total_cost_usd: float = 0.01) -> ResultMessage:
    return ResultMessage(subtype=subtype, duration_ms=10, duration_api_ms=8,
                         is_error=is_error, num_turns=6, session_id="test",
                         total_cost_usd=total_cost_usd, result=text, model_usage=model_usage,
                         structured_output=structured_output)


def findings_for(site: dict[str, dict], summary: str = "All checked.") -> dict:
    """Findings that exactly match the payloads in `site` (what a correct model returns)."""
    offline_ids = [d for d, p in site.items() if p["status"] == "offline"]
    unknown_ids = [d for d, p in site.items() if p["status"] == "unknown"]
    ports_down = [{"switch_id": d, "port": port["port"], "label": port["label"]}
                  for d, p in site.items() if p["status"] == "online" and p.get("ports")
                  for port in p["ports"] if port["state"] == "down"]
    return {"devices_checked": len(site),
            "offline": [{"device_id": d, "reason": "no response"} for d in offline_ids],
            "unknown": [{"device_id": d, "reason": "check failed"} for d in unknown_ids],
            "ports_down": ports_down,
            "likely_causes": [{"device_id": p["label"], "cause": f"{p['switch_id']} port {p['port']} down"}
                              for p in ports_down if p["label"] in offline_ids],
            "summary": summary, "recommended_action": "See findings."}


# --- scripted steps ---

@dataclass
class Turn:
    """One API turn, written to the transcript the way the CLI does (agent=None: coordinator)."""
    agent: str | None = None
    tokens: tuple[int, int] = (100, 20)

    async def run(self, options, fake) -> None:
        path = fake.transcript_for(self.agent)
        if path is None:
            return
        entry = {"type": "assistant", "isSidechain": self.agent is not None,
                 "timestamp": "2026-11-16T10:00:00Z",
                 "message": {"id": f"msg_{next(_ids)}", "model": "claude-haiku-5-5",
                             "stop_reason": "tool_use",
                             "usage": {"input_tokens": self.tokens[0], "output_tokens": self.tokens[1],
                                       "cache_read_input_tokens": 0,
                                       "cache_creation_input_tokens": 0}}}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


async def fire(options, event: str, target: str, data: dict) -> list[dict]:
    """Call the hooks registered for `event` whose matcher fits `target`."""
    outputs = []
    for matcher in (options.hooks or {}).get(event, []):
        if matcher.matcher is None or re.fullmatch(matcher.matcher, target):
            for callback in matcher.hooks:
                outputs.append(await callback(data, data.get("tool_use_id"), None))
    return outputs


def denial(outputs: list[dict]) -> str | None:
    for out in outputs:
        spec = (out or {}).get("hookSpecificOutput", {})
        if spec.get("permissionDecision") == "deny":
            return spec.get("permissionDecisionReason", "denied")
    return None


async def pre_tool(options, fake, tool_name: str, tool_input: dict,
                   agent_id: str | None) -> dict | None:
    """Return the hook input if the call may proceed, else record the denial."""
    data = {"hook_event_name": "PreToolUse", "tool_name": tool_name,
            "tool_input": tool_input, "tool_use_id": f"toolu_{next(_ids)}", **fake.paths()}
    if agent_id:
        data.update(agent_id=f"id-{agent_id}", agent_type=agent_id)
    if tool_name not in options.allowed_tools:
        fake.denials.append((tool_name, "not in allowed_tools"))
        return None
    reason = denial(await fire(options, "PreToolUse", tool_name, data))
    if reason:
        fake.denials.append((tool_name, reason))
        return None
    return data


@dataclass
class Check:
    """A check_device call, by a subagent unless agent_id is None (coordinator)."""
    device_id: str
    payload: dict
    agent_id: str | None = field(default=None)

    async def run(self, options, fake) -> None:
        agent = self.agent_id if self.agent_id is not None else \
            AGENT_FOR_TYPE.get(TYPES.get(self.device_id), "cctv-checker")
        agent = None if self.agent_id == "" else agent
        data = await pre_tool(options, fake, CHECK_TOOL, {"device_id": self.device_id}, agent)
        if data is None:
            return
        text = json.dumps(self.payload)
        if self.payload["status"] == "unknown":
            data.update(hook_event_name="PostToolUseFailure", error=text, is_interrupt=False)
            await fire(options, "PostToolUseFailure", CHECK_TOOL, data)
        else:
            data.update(hook_event_name="PostToolUse", tool_response=text)
            await fire(options, "PostToolUse", CHECK_TOOL, data)


@dataclass
class Lifecycle:
    """SubagentStart / SubagentStop for one subagent."""
    agent: str
    event: str

    async def run(self, options, fake) -> None:
        data = {"hook_event_name": self.event, "agent_id": f"id-{self.agent}",
                "agent_type": self.agent, "last_assistant_message": f"{self.agent} done",
                **fake.paths()}
        if self.event == "SubagentStop" and fake.transcript_dir is not None:
            data["agent_transcript_path"] = str(fake.transcript_for(self.agent))
        await fire(options, self.event, self.agent, data)


@dataclass
class Decide:
    """The coordinator calls a decision tool (release_technician / hold_and_escalate)."""
    tool: str
    args: dict

    async def run(self, options, fake) -> None:
        name = f"mcp__decision__{self.tool}"
        data = await pre_tool(options, fake, name, self.args, agent_id=None)
        if data is None:
            return
        server = options.mcp_servers["decision"]["instance"]
        request = mcp_types.CallToolRequest(
            method="tools/call",
            params=mcp_types.CallToolRequestParams(name=self.tool, arguments=self.args))
        await server.request_handlers[mcp_types.CallToolRequest](request)
        fake.executed.append(self.tool)
        data.update(hook_event_name="PostToolUse", tool_response=f"{self.tool} done")
        await fire(options, "PostToolUse", name, data)


_CORRECT = object()


def script(site: dict[str, dict], *extra, summary: str = "All checked.",
           findings=_CORRECT) -> list:
    """Coordinator launches the 3 subagents; each checks its own devices; then extra
    steps (decisions) and the final result."""
    steps = [Turn()]
    for agent in SUBAGENTS:
        steps += [Lifecycle(agent, "SubagentStart"), Turn(agent, tokens=(50, 10))]
        steps += [Check(d, p) for d, p in site.items()
                  if AGENT_FOR_TYPE.get(TYPES.get(d)) == agent]
        steps.append(Lifecycle(agent, "SubagentStop"))
    out = findings_for(site, summary) if findings is _CORRECT else findings
    return steps + list(extra) + [Turn()] + [result_message(summary, structured_output=out)]


def correction(findings: dict | None, *steps, session_total_usd: float = 0.015,
               model_usage: dict | None = None) -> list:
    """A resumed findings-correction call: optional (denied) steps, then new findings.

    Like the real CLI (verified live), the resumed call's ResultMessage reports
    RUNNING TOTALS for the whole session, not just this call.
    """
    return list(steps) + [result_message("corrected", structured_output=findings,
                                         total_cost_usd=session_total_usd,
                                         model_usage=model_usage)]


def release(reason: str = "all clear") -> Decide:
    return Decide("release_technician", {"reason": reason})


def escalate(device_ids: list[str], reason: str = "faults found") -> Decide:
    return Decide("hold_and_escalate", {"reason": reason, "device_ids": device_ids})


class FakeQuery:
    """Stands in for claude_agent_sdk.query; records calls, denials and executed tools."""

    def __init__(self, steps: list | None = None, raises: Exception | None = None,
                 transcript_dir: Path | None = None, retries: list[list] | None = None):
        """retries: scripts for later calls (resumed findings corrections), in order."""
        self.steps = steps or []
        self.retries = list(retries or [])
        self.raises = raises
        self.transcript_dir = Path(transcript_dir) if transcript_dir else None
        self.calls: list[dict] = []
        self.denials: list[tuple[str, str]] = []
        self.executed: list[str] = []

    def transcript_for(self, agent: str | None) -> Path | None:
        if self.transcript_dir is None:
            return None
        if agent is None:
            return self.transcript_dir / "session.jsonl"
        return self.transcript_dir / "subagents" / f"agent-{agent}.jsonl"

    def paths(self) -> dict:
        """transcript_path, as every real hook input carries it."""
        main = self.transcript_for(None)
        return {"transcript_path": str(main)} if main else {}

    async def __call__(self, *, prompt, options=None):
        self.calls.append({"prompt": prompt, "options": options})
        if self.raises:
            raise self.raises
        steps = self.steps if len(self.calls) == 1 else self.retries.pop(0)
        for step in steps:
            if isinstance(step, (ResultMessage, AssistantMessage)):
                yield step
            else:
                await step.run(options, self)
