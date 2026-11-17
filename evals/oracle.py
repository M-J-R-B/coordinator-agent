"""What the rules say a scenario's outcome must be. No model, no disk.

Polls the simulator directly (the same check the MCP tools use) before and
after the `during` faults, then applies agent.diff, which is the rule the
release hook enforces. Design note: this reuses the production diff instead of
restating the rules here, so the oracle cannot drift from the real gate.
"""
from agent.diff import diff
from evals.scenarios import Scenario, apply_faults
from mcp_server.checks import check_state
from mock_site.devices import INVENTORY
from mock_site.state import empty_state


def _no_sleep(_seconds: float) -> None:
    """Skip real waiting; the poll deadline is still enforced by check_state."""


def _snapshot(state: dict) -> dict:
    return {device_id: check_state(device_id, state, sleep=_no_sleep).model_dump()
            for device_id in INVENTORY}


def expected(scenario: Scenario) -> tuple[str, frozenset[str]]:
    """Return (decision, blocking device ids) for the scenario under the rules."""
    before = apply_faults(empty_state(), scenario.before)
    after = apply_faults(before, scenario.during)
    result = diff(_snapshot(before), _snapshot(after))
    decision = "release" if result["release_allowed"] else "hold"
    return decision, frozenset(result["blocking"])
