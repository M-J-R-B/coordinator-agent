"""Load the JSON schemas in schemas/ and validate against them.

findings.schema.json is draft-07 (the Agent SDK's output_format needs it).
report.schema.json is draft 2020-12; the findings schema is embedded into its
$defs at load time, so validation needs no $ref registry (works on jsonschema 4.0+).
"""
import copy
import json
from functools import lru_cache

from jsonschema import Draft7Validator, Draft202012Validator

from agent.storage import REPO_ROOT

SCHEMA_DIR = REPO_ROOT / "schemas"


def _load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _findings_schema() -> dict:
    return _load("findings.schema.json")


@lru_cache(maxsize=None)
def _report_schema() -> dict:
    schema = _load("report.schema.json")
    embedded = {k: v for k, v in _findings_schema().items() if k != "$schema"}
    schema["$defs"]["findings"] = embedded
    return schema


def findings_schema() -> dict:
    return copy.deepcopy(_findings_schema())


def report_schema() -> dict:
    return copy.deepcopy(_report_schema())


def _errors(validator, instance) -> list[str]:
    found = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in found]


def findings_errors(findings) -> list[str]:
    return _errors(Draft7Validator(_findings_schema()), findings)


def report_errors(report: dict) -> list[str]:
    return _errors(Draft202012Validator(_report_schema()), report)
