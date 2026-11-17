from agent.prompts import task_prompt

BASELINE = {
    "CAM-01": {"status": "online"},
    "CAM-07": {"status": "offline"},
    "POS-02": {"status": "unknown"},
    "SW-01": {"status": "online"},
}


def test_precheck_prompt_has_no_baseline_section():
    assert "before the work" not in task_prompt("precheck", "STORE-001")


def test_postcheck_prompt_names_devices_that_were_already_offline_or_unknown():
    prompt = task_prompt("postcheck", "STORE-001", BASELINE)
    assert "Offline before the work: CAM-07." in prompt
    assert "Unknown before the work: POS-02." in prompt
    assert "CAM-01" not in prompt and "SW-01" not in prompt


def test_postcheck_prompt_says_none_when_everything_was_online():
    prompt = task_prompt("postcheck", "STORE-001", {"CAM-01": {"status": "online"}})
    assert "Offline before the work: none." in prompt
    assert "Unknown before the work: none." in prompt


def test_postcheck_prompt_still_requires_fresh_checks():
    prompt = task_prompt("postcheck", "STORE-001", BASELINE)
    assert "check every device again" in prompt.lower()


def test_postcheck_prompt_without_a_baseline_is_unchanged():
    assert task_prompt("postcheck", "STORE-001") == task_prompt("postcheck", "STORE-001", None)
    assert "before the work" not in task_prompt("postcheck", "STORE-001")
