"""In-process MCP tools for the coordinator's decision (post-check only).

The tools only record what was decided. Whether a release may happen at all
is enforced before the tool runs, by the PreToolUse gate in agent/hooks.py.
"""
from dataclasses import dataclass, field

from claude_agent_sdk import create_sdk_mcp_server, tool

SERVER_NAME = "decision"


@dataclass
class Decisions:
    released: bool = False
    release_reason: str | None = None
    escalated: bool = False
    escalate_reason: str | None = None
    escalated_devices: list[str] = field(default_factory=list)


ESCALATE_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "device_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["reason", "device_ids"],
}


def _text(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}]}


def create_decision_server(decisions: Decisions):
    @tool("release_technician",
          "Release the field technician from site. Only allowed when the post-check "
          "found no new offline and no unknown devices; otherwise it is blocked.",
          {"reason": str})
    async def release_technician(args):
        decisions.released = True
        decisions.release_reason = args.get("reason")
        return _text("Technician released.")

    @tool("hold_and_escalate",
          "Keep the technician on site and escalate the listed devices for follow-up.",
          ESCALATE_SCHEMA)
    async def hold_and_escalate(args):
        decisions.escalated = True
        decisions.escalate_reason = args.get("reason")
        decisions.escalated_devices = list(args.get("device_ids", []))
        return _text("Technician held; escalation recorded.")

    return create_sdk_mcp_server(SERVER_NAME, tools=[release_technician, hold_and_escalate])
