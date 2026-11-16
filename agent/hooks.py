"""Hooks: where code, not the prompt, enforces the rules.

- record hooks (PostToolUse / PostToolUseFailure on check_device) feed the Recorder
- coordinator_guard (PreToolUse on device tools) makes the coordinator delegate
- release gate (PreToolUse on release_technician) blocks an unsafe release
"""
from agent.diff import diff
from agent.recorder import Recorder


def _deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def _device_id(data: dict) -> str:
    return str((data.get("tool_input") or {}).get("device_id", ""))


def make_record_hooks(recorder: Recorder):
    async def on_success(data, tool_use_id, context):
        recorder.record(_device_id(data), data.get("tool_response"), is_error=False)
        return {}

    async def on_failure(data, tool_use_id, context):
        recorder.record(_device_id(data), data.get("error"), is_error=True)
        return {}

    return on_success, on_failure


async def coordinator_guard(data, tool_use_id, context):
    """Only subagent calls carry agent_id (verified live); the coordinator must delegate."""
    if data.get("agent_id"):
        return {}
    return _deny("The coordinator does not poll devices. Delegate device checks to the "
                 "cctv-checker, network-checker and pos-checker subagents.")


class Gate:
    """Decides a release from the on-disk baseline and the recorded tool results."""

    def __init__(self, baseline_devices: dict, recorder: Recorder) -> None:
        self.baseline_devices = baseline_devices
        self.recorder = recorder
        self.denials: list[str] = []

    def evaluate(self) -> dict:
        return diff(self.baseline_devices, self.recorder.complete())


def _blocking_text(result: dict) -> str:
    parts = []
    for d in result["devices"]:
        if d["device_id"] in result["blocking"]:
            cause = f" ({d['likely_cause']})" if d.get("likely_cause") else ""
            parts.append(f"{d['device_id']} {d['classification']}{cause}")
    return "; ".join(parts)


def make_release_gate(gate: Gate):
    async def release_gate(data, tool_use_id, context):
        result = gate.evaluate()
        if result["release_allowed"]:
            return {}
        reason = (f"Release blocked by site policy: {_blocking_text(result)}. "
                  f"The technician cannot be released. Call hold_and_escalate with "
                  f"these device_ids: {', '.join(result['blocking'])}.")
        gate.denials.append(reason)
        return _deny(reason)

    return release_gate
