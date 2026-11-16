import copy
import json

import pytest

from agent.schemas import findings_errors, findings_schema, report_errors, report_schema
from tests.fakes import findings_for, healthy_site, offline


def test_findings_schema_is_draft_07_for_the_sdk():
    assert findings_schema()["$schema"] == "http://json-schema.org/draft-07/schema#"


def test_report_schema_embeds_findings_schema():
    embedded = report_schema()["$defs"]["findings"]
    assert embedded["required"] == findings_schema()["required"]
    assert "$schema" not in embedded


def test_valid_findings():
    assert findings_errors(findings_for(healthy_site(CAM_05=offline("CAM-05")))) == []


@pytest.mark.parametrize("change, expected", [
    ({"devices_checked": -1}, "devices_checked"),
    ({"summary": ""}, "summary"),
    ({"offline": [{"device_id": "CAM-01"}]}, "offline/0"),
    ({"surprise": 1}, "surprise"),
])
def test_invalid_findings_name_the_field(change, expected):
    errors = findings_errors({**findings_for(healthy_site()), **change})
    assert errors and expected in " ".join(errors)


def test_schema_files_are_valid_json_on_disk():
    from agent.schemas import SCHEMA_DIR
    for path in SCHEMA_DIR.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))


# Whole reports: real ones come from the run tests (tests/test_run.py validates every
# report it produces); here, check that the schema rejects what it should.

def minimal_postcheck():
    return {"kind": "postcheck", "check_id": "c", "site": "STORE-001", "created_at": "t",
            "agent": None, "baseline_check_id": None, "diff": None, "agent_decision": None,
            "decision": "hold", "error": "no saved baseline", "event_log": None,
            "findings": None, "findings_error": None, "findings_attempts": 0}


def test_minimal_postcheck_is_valid():
    assert report_errors(minimal_postcheck()) == []


@pytest.mark.parametrize("change", [
    {"decision": "maybe"},
    {"kind": "midcheck"},
    {"unexpected": True},
    {"findings": {"devices_checked": 1}},
])
def test_invalid_reports_rejected(change):
    report = {**copy.deepcopy(minimal_postcheck()), **change}
    assert report_errors(report) != []


def test_missing_required_field_rejected():
    report = minimal_postcheck()
    del report["decision"]
    assert report_errors(report) != []
