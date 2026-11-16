"""Hooks: where code, not the prompt, enforces the rules.

- record hooks (PostToolUse / PostToolUseFailure on check_device) feed the Recorder
- coordinator guard (PreToolUse on device tools) makes the coordinator delegate
- release gate (PreToolUse on release_technician) blocks an unsafe release
Every allow/deny made by the guard and the gate is written to the event log.
"""
from agent.diff import diff
from agent.events import EventLog, agent_name
from agent.options_base import STRUCTURED_OUTPUT_TOOL
from agent.recorder import Recorder


def _deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def _log_decision(log: EventLog, hook: str, data: dict, decision: str,
                  reason: str | None = None, **extra) -> None:
    log.emit("hook_decision", hook=hook, agent=agent_name(data), tool=data.get("tool_name"),
             tool_use_id=data.get("tool_use_id"), input=data.get("tool_input"),
             decision=decision, reason=reason, **extra)


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


def make_coordinator_guard(log: EventLog):
    """Only subagent calls carry agent_id (verified live); the coordinator must delegate."""
    async def coordinator_guard(data, tool_use_id, context):
        if data.get("agent_id"):
            _log_decision(log, "coordinator_guard", data, "allow")
            return {}
        reason = ("The coordinator does not poll devices. Delegate device checks to the "
                  "cctv-checker, network-checker and pos-checker subagents.")
        _log_decision(log, "coordinator_guard", data, "deny", reason)
        return _deny(reason)

    return coordinator_guard


def make_retry_guard(phase, log: EventLog):
    """While findings are being corrected, only StructuredOutput may run.

    A correction must not re-poll devices, launch subagents or try to release:
    the evidence and the decision are already fixed.
    """
    async def retry_guard(data, tool_use_id, context):
        if not phase.correcting or data.get("tool_name") == STRUCTURED_OUTPUT_TOOL:
            return {}
        reason = ("Findings correction only: do not call tools. Return corrected findings "
                  "from the results you already have.")
        _log_decision(log, "findings_retry_guard", data, "deny", reason)
        return _deny(reason)

    return retry_guard


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


def make_release_gate(gate: Gate, log: EventLog):
    async def release_gate(data, tool_use_id, context):
        result = gate.evaluate()
        if result["release_allowed"]:
            _log_decision(log, "release_gate", data, "allow", blocking=[])
            return {}
        reason = (f"Release blocked by site policy: {_blocking_text(result)}. "
                  f"The technician cannot be released. Call hold_and_escalate with "
                  f"these device_ids: {', '.join(result['blocking'])}.")
        gate.denials.append(reason)
        _log_decision(log, "release_gate", data, "deny", reason, blocking=result["blocking"])
        return _deny(reason)

    return release_gate
