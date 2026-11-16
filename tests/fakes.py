"""Scripted Agent SDK messages, so agent tests never call a model."""
import json

from claude_agent_sdk import (AssistantMessage, ResultMessage, ToolResultBlock,
                              ToolUseBlock, UserMessage)

from mock_site.devices import INVENTORY, PORT_COUNT, port_label

CHECK_TOOL = "mcp__devices__check_device"
TYPES = {d.device_id: d.type for d in INVENTORY.values()}


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


def tool_use(use_id: str, device_id: str, name: str = CHECK_TOOL) -> AssistantMessage:
    return AssistantMessage(
        content=[ToolUseBlock(id=use_id, name=name, input={"device_id": device_id})],
        model="claude-haiku-5-5")


def tool_result(use_id: str, payload, is_error: bool = False) -> UserMessage:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return UserMessage(content=[ToolResultBlock(
        tool_use_id=use_id, content=[{"type": "text", "text": text}], is_error=is_error)])


def result_message(text: str = "All checked.", is_error: bool = False,
                   subtype: str = "success") -> ResultMessage:
    return ResultMessage(subtype=subtype, duration_ms=10, duration_api_ms=8,
                         is_error=is_error, num_turns=15, session_id="test",
                         total_cost_usd=0.01, result=text)


def script(site: dict[str, dict], summary: str = "All checked.") -> list:
    """One check_device call + result per device, then the final ResultMessage."""
    messages = []
    for i, (device_id, payload) in enumerate(site.items()):
        messages.append(tool_use(f"t{i}", device_id))
        messages.append(tool_result(f"t{i}", payload, is_error=payload["status"] == "unknown"))
    messages.append(result_message(summary))
    return messages


class FakeQuery:
    """Stands in for claude_agent_sdk.query; records how it was called."""

    def __init__(self, messages: list | None = None, raises: Exception | None = None):
        self.messages = messages or []
        self.raises = raises
        self.calls: list[dict] = []

    async def __call__(self, *, prompt, options=None):
        self.calls.append({"prompt": prompt, "options": options})
        if self.raises:
            raise self.raises
        for message in self.messages:
            yield message
