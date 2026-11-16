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
from dataclasses import dataclass, field

from claude_agent_sdk import ResultMessage
from mcp import types as mcp_types

from mock_site.devices import INVENTORY, PORT_COUNT, port_label

CHECK_TOOL = "mcp__devices__check_device"
TYPES = {d.device_id: d.type for d in INVENTORY.values()}
AGENT_FOR_TYPE = {"camera": "cctv-checker", "switch": "network-checker", "pos": "pos-checker"}
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
                   subtype: str = "success") -> ResultMessage:
    return ResultMessage(subtype=subtype, duration_ms=10, duration_api_ms=8,
                         is_error=is_error, num_turns=6, session_id="test",
                         total_cost_usd=0.01, result=text)


# --- scripted steps ---

async def fire(options, event: str, tool_name: str, data: dict) -> list[dict]:
    outputs = []
    for matcher in (options.hooks or {}).get(event, []):
        if matcher.matcher is None or re.fullmatch(matcher.matcher, tool_name):
            for callback in matcher.hooks:
                outputs.append(await callback(data, data["tool_use_id"], None))
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
            "tool_input": tool_input, "tool_use_id": f"toolu_{next(_ids)}"}
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
class Decide:
    """The coordinator calls a decision tool (release_technician / hold_and_escalate)."""
    tool: str
    args: dict

    async def run(self, options, fake) -> None:
        name = f"mcp__decision__{self.tool}"
        if await pre_tool(options, fake, name, self.args, agent_id=None) is None:
            return
        server = options.mcp_servers["decision"]["instance"]
        request = mcp_types.CallToolRequest(
            method="tools/call",
            params=mcp_types.CallToolRequestParams(name=self.tool, arguments=self.args))
        await server.request_handlers[mcp_types.CallToolRequest](request)
        fake.executed.append(self.tool)


def script(site: dict[str, dict], *extra, summary: str = "All checked.") -> list:
    """Each device checked by its domain subagent, then extra steps, then the result."""
    return [Check(d, p) for d, p in site.items()] + list(extra) + [result_message(summary)]


def release(reason: str = "all clear") -> Decide:
    return Decide("release_technician", {"reason": reason})


def escalate(device_ids: list[str], reason: str = "faults found") -> Decide:
    return Decide("hold_and_escalate", {"reason": reason, "device_ids": device_ids})


class FakeQuery:
    """Stands in for claude_agent_sdk.query; records calls, denials and executed tools."""

    def __init__(self, steps: list | None = None, raises: Exception | None = None):
        self.steps = steps or []
        self.raises = raises
        self.calls: list[dict] = []
        self.denials: list[tuple[str, str]] = []
        self.executed: list[str] = []

    async def __call__(self, *, prompt, options=None):
        self.calls.append({"prompt": prompt, "options": options})
        if self.raises:
            raise self.raises
        for step in self.steps:
            if isinstance(step, ResultMessage):
                yield step
            else:
                await step.run(options, self)
