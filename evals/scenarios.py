"""The fault scenarios the agent is scored on. Data only: no model, no disk.

A scenario is one technician visit. `before` faults exist when the pre-check
runs; `during` faults are applied while the technician works, so the post-check
sees them. The expected answer is written by hand and proven against the rules
by evals/oracle.py (tests/test_eval_scenarios.py), so a wrong expectation is
caught before a live run spends anything.

Design note: faults are plain tuples, not objects. The alternative (a Fault
class per kind) adds code without making the table below easier to read.
"""
from dataclasses import dataclass

from mock_site import faults

Fault = tuple  # (operation, *args), e.g. ("offline", "CAM-03") or ("port_down", "SW-01", 3)

_OPERATIONS = {
    "offline": faults.inject_offline,
    "timeout": faults.inject_timeout,
    "slow": faults.inject_slow,
    "port_down": faults.inject_port_down,
    "clear_device": faults.clear_device,
    "clear_port": faults.clear_port,
}


@dataclass(frozen=True)
class Scenario:
    id: str
    description: str
    before: tuple[Fault, ...]
    during: tuple[Fault, ...]
    expected_decision: str  # "release" | "hold"
    expected_blocking: frozenset[str]  # device ids the post-check should block on


def apply_faults(state: dict, fault_list: tuple[Fault, ...]) -> dict:
    """Return a new state with the faults applied in order. The input is not changed."""
    for operation, *args in fault_list:
        if operation not in _OPERATIONS:
            raise ValueError(f"unknown fault operation: {operation}")
        state = _OPERATIONS[operation](state, *args)
    return state


def _release(id: str, description: str, before=(), during=()) -> Scenario:
    return Scenario(id, description, tuple(before), tuple(during), "release", frozenset())


def _hold(id: str, description: str, blocking: set[str], before=(), during=()) -> Scenario:
    return Scenario(id, description, tuple(before), tuple(during), "hold", frozenset(blocking))


SCENARIOS: tuple[Scenario, ...] = (
    _release("clean-visit", "Nothing is wrong before or after the visit."),
    _hold("camera-goes-offline", "A camera that was online goes offline during the visit.",
          {"CAM-03"}, during=[("offline", "CAM-03")]),
    _hold("pos-goes-offline", "A POS terminal that was online goes offline during the visit.",
          {"POS-02"}, during=[("offline", "POS-02")]),
    _hold("camera-times-out", "A camera stops answering, so its state is unknown, not online.",
          {"CAM-05"}, during=[("timeout", "CAM-05")]),
    _release("slow-but-online", "A POS terminal answers slowly but is still online.",
             during=[("slow", "POS-01", 800)]),
    _release("already-offline-before", "A camera was already offline before the technician started.",
             before=[("offline", "CAM-07")]),
    _hold("pre-existing-plus-new",
          "One camera was already offline, and a POS terminal goes offline during the visit.",
          {"POS-04"}, before=[("offline", "CAM-07")], during=[("offline", "POS-04")]),
    _release("fixed-during-visit", "A camera that was offline before is back online afterwards.",
             before=[("offline", "CAM-02")], during=[("clear_device", "CAM-02")]),
    _hold("two-new-faults", "A camera goes offline and a switch stops answering during the visit.",
          {"CAM-01", "SW-02"}, during=[("offline", "CAM-01"), ("timeout", "SW-02")]),
    _hold("switch-port-down",
          "A switch port goes down during the visit, taking the camera cabled to it offline.",
          {"CAM-03"}, during=[("port_down", "SW-01", 3)]),
)
