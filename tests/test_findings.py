from agent.findings import MAX_RETRIES, check_findings, retry_prompt
from tests.fakes import failure, findings_for, healthy_site, offline, online


def evidence(site):
    """Recorder.complete()-shaped evidence from fake payloads."""
    return {d: {**p, "type": p.get("type") or ("camera" if d.startswith("CAM") else
                                               "switch" if d.startswith("SW") else "pos")}
            for d, p in site.items()}


def unplugged():
    return healthy_site(SW_01=online("SW-01", ports_down=(3,)), CAM_03=offline("CAM-03"))


def test_correct_findings_pass():
    site = unplugged()
    assert check_findings(findings_for(site), evidence(site)) == []


def test_schema_errors_reported_before_semantic_checks():
    errors = check_findings({"devices_checked": "fourteen"}, evidence(healthy_site()))
    assert errors and all(e.startswith("schema:") for e in errors)


def test_missing_findings():
    assert check_findings(None, evidence(healthy_site())) == [
        "no structured findings were returned"]


def test_miscounted_devices_checked():
    """The miscount Haiku made live: said 13, checked 14."""
    site = unplugged()
    wrong = {**findings_for(site), "devices_checked": 13}
    assert check_findings(wrong, evidence(site)) == [
        "devices_checked is 13, but 14 devices have a check_device result"]


def test_offline_device_left_out():
    site = unplugged()
    wrong = {**findings_for(site), "offline": []}
    assert check_findings(wrong, evidence(site)) == [
        "offline is missing CAM-03 (check_device returned offline)"]


def test_device_claimed_offline_but_was_online():
    site = healthy_site()
    wrong = {**findings_for(site), "offline": [{"device_id": "CAM-02", "reason": "?"}]}
    assert check_findings(wrong, evidence(site)) == [
        "offline lists CAM-02, but check_device did not return offline for it"]


def test_unknown_includes_devices_never_checked():
    site = healthy_site(CAM_01=failure("CAM-01"))
    ev = evidence(site)
    ev["POS-04"] = {"device_id": "POS-04", "type": "pos", "status": "unknown",
                    "error_category": "not_checked", "is_retryable": True, "message": "x"}
    claimed = {**findings_for(site), "devices_checked": 13,
               "unknown": [{"device_id": "CAM-01", "reason": "timeout"}]}
    assert check_findings(claimed, ev) == [
        "unknown is missing POS-04 (its status is unknown)"]


def test_port_down_left_out():
    site = unplugged()
    wrong = {**findings_for(site), "ports_down": []}
    assert check_findings(wrong, evidence(site)) == [
        "ports_down is missing SW-01 port 3 (reported down)"]


def test_likely_cause_for_a_healthy_device():
    site = healthy_site()
    wrong = {**findings_for(site), "likely_causes": [{"device_id": "CAM-01", "cause": "?"}]}
    assert check_findings(wrong, evidence(site)) == [
        "likely_causes names CAM-01, which is neither offline nor unknown"]


def test_retry_prompt_lists_every_error_and_forbids_tools():
    prompt = retry_prompt(["a is wrong", "b is wrong"])
    assert "- a is wrong" in prompt and "- b is wrong" in prompt
    assert "Do not call any tools" in prompt


def test_retry_budget():
    assert MAX_RETRIES == 2
