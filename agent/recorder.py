"""Collect device results from the agent's tool calls, not from its prose.

Each check_device call (ToolUseBlock) is matched to its result
(ToolResultBlock) by tool_use_id. The latest result per device wins, so a
successful retry replaces an earlier timeout.
"""
import json

from claude_agent_sdk import ResultMessage, ToolResultBlock, ToolUseBlock

from agent.options import CHECK_TOOL
from mock_site.devices import INVENTORY

VALID_STATUSES = {"online", "offline", "unknown"}


def _unknown(device_id: str, category: str, message: str) -> dict:
    return {"device_id": device_id, "status": "unknown", "error_category": category,
            "is_retryable": category != "invalid_input", "message": message}


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def _parse(device_id: str, block: ToolResultBlock) -> dict:
    """Turn one tool result into a device record. Anything odd becomes unknown."""
    text = _text(block.content)
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return _unknown(device_id, "internal", f"unreadable tool result: {text[:200]}")
    if not isinstance(payload, dict) or payload.get("status") not in VALID_STATUSES:
        return _unknown(device_id, "internal", f"unexpected tool result: {text[:200]}")
    if block.is_error and payload["status"] != "unknown":
        return _unknown(device_id, "internal", "tool reported an error")
    return {**payload, "device_id": device_id}


class Recorder:
    def __init__(self) -> None:
        self._pending: dict[str, str] = {}   # tool_use_id -> device_id
        self.results: dict[str, dict] = {}
        self.check_calls = 0
        self.final: ResultMessage | None = None

    def feed(self, message) -> None:
        if isinstance(message, ResultMessage):
            self.final = message
            return
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            return
        for block in content:
            if isinstance(block, ToolUseBlock) and block.name == CHECK_TOOL:
                self._pending[block.id] = str(block.input.get("device_id", ""))
                self.check_calls += 1
            elif isinstance(block, ToolResultBlock) and block.tool_use_id in self._pending:
                device_id = self._pending.pop(block.tool_use_id)
                self.results[device_id] = _parse(device_id, block)

    def complete(self) -> dict[str, dict]:
        """One record per site device; any device the agent skipped is unknown."""
        devices = {}
        for device_id, device in INVENTORY.items():
            record = self.results.get(device_id) or _unknown(
                device_id, "not_checked", "the agent did not check this device")
            devices[device_id] = {**record, "type": device.type}
        return devices
