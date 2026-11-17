import pytest

from evals import oracle
from evals.scenarios import SCENARIOS, apply_faults
from mock_site.state import empty_state


def test_there_are_ten_scenarios_with_unique_ids():
    assert len(SCENARIOS) == 10
    assert len({s.id for s in SCENARIOS}) == 10


def test_scenarios_cover_both_decisions():
    decisions = [s.expected_decision for s in SCENARIOS]
    assert set(decisions) == {"release", "hold"}
    assert decisions.count("hold") >= 4 and decisions.count("release") >= 4


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_expected_answer_follows_from_the_rules(scenario):
    decision, blocking = oracle.expected(scenario)
    assert decision == scenario.expected_decision
    assert blocking == scenario.expected_blocking


def test_hold_scenarios_name_what_blocks_and_release_scenarios_name_nothing():
    for s in SCENARIOS:
        assert bool(s.expected_blocking) == (s.expected_decision == "hold"), s.id


def test_apply_faults_rejects_unknown_operation():
    with pytest.raises(ValueError):
        apply_faults(empty_state(), (("explode", "CAM-01"),))


def test_apply_faults_does_not_change_its_input():
    state = empty_state()
    apply_faults(state, (("offline", "CAM-01"),))
    assert state == empty_state()
