"""Collect device results from tool results, not from the model's prose.

Fed by hooks (agent/hooks.py): the CLI waits for each PostToolUse /
PostToolUseFailure hook before the model sees the result, so by the time any
agent asks to release, every result it has seen is already recorded here.
The latest result per device wins, so a successful retry replaces a timeout.
"""
import json

from claude_agent_sdk import ResultMessage

from mock_site.devices import INVENTORY

VALID_STATUSES = {"online", "offline", "unknown"}


def _unknown(device_id: str, category: str, message: str) -> dict:
    return {"device_id": device_id, "status": "unknown", "error_category": category,
            "is_retryable": category != "invalid_input", "message": message}


def _as_payload(response):
    """Tool responses arrive as a JSON string (verified live); accept dicts and blocks too."""
    if isinstance(response, dict):
        return response
    if isinstance(response, list):
        response = "".join(c.get("text", "") for c in response if isinstance(c, dict))
    if isinstance(response, str):
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return None
    return None


def _parse(device_id: str, response, is_error: bool) -> dict:
    payload = _as_payload(response)
    snippet = str(response)[:200]
    if not isinstance(payload, dict) or payload.get("status") not in VALID_STATUSES:
        return _unknown(device_id, "internal", f"unreadable tool result: {snippet}")
    if is_error and payload["status"] != "unknown":
        return _unknown(device_id, "internal", "tool reported an error")
    return {**payload, "device_id": device_id}


class Recorder:
    def __init__(self) -> None:
        self.results: dict[str, dict] = {}
        self.check_calls = 0
        self.final: ResultMessage | None = None

    def record(self, device_id: str, response, is_error: bool) -> None:
        self.check_calls += 1
        self.results[device_id] = _parse(device_id, response, is_error)

    def feed(self, message) -> None:
        """The message stream is only used for the final result (summary, cost)."""
        if isinstance(message, ResultMessage):
            self.final = message

    def complete(self) -> dict[str, dict]:
        """One record per site device; any device not checked is unknown."""
        devices = {}
        for device_id, device in INVENTORY.items():
            record = self.results.get(device_id) or _unknown(
                device_id, "not_checked", "no subagent checked this device")
            devices[device_id] = {**record, "type": device.type}
        return devices
