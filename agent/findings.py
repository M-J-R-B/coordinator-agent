"""Validate the model's structured findings: first the schema, then the evidence.

A schema-valid answer can still be wrong (live, Haiku once wrote "13 devices
checked" after checking 14), so every claim is compared with the recorded tool
results. Errors are written as plain sentences, because they are sent back to
the model verbatim in the retry prompt.
"""
from agent.schemas import findings_errors

MAX_RETRIES = 2


def _ids(items: list[dict]) -> set[str]:
    return {item["device_id"] for item in items}


def _ports_down(devices: dict) -> set[tuple[str, int]]:
    return {(d["device_id"], p["port"]) for d in devices.values()
            if d["status"] == "online" and d.get("ports")
            for p in d["ports"] if p["state"] == "down"}


def _compare_ids(field: str, claimed: set[str], actual: set[str], why: str) -> list[str]:
    errors = [f"{field} is missing {d} ({why})" for d in sorted(actual - claimed)]
    errors += [f"{field} lists {d}, but check_device did not return {field} for it"
               if field == "offline" else f"{field} lists {d}, but its status is not unknown"
               for d in sorted(claimed - actual)]
    return errors


def check_findings(findings, devices: dict) -> list[str]:
    """[] if the findings are valid and match the evidence; else what is wrong."""
    if findings is None:
        return ["no structured findings were returned"]
    schema = findings_errors(findings)
    if schema:
        return [f"schema: {e}" for e in schema]

    by_status = {s: {d for d, r in devices.items() if r["status"] == s}
                 for s in ("offline", "unknown")}
    checked = sum(1 for r in devices.values() if r.get("error_category") != "not_checked")
    errors = []
    if findings["devices_checked"] != checked:
        errors.append(f"devices_checked is {findings['devices_checked']}, "
                      f"but {checked} devices have a check_device result")
    errors += _compare_ids("offline", _ids(findings["offline"]), by_status["offline"],
                           "check_device returned offline")
    errors += _compare_ids("unknown", _ids(findings["unknown"]), by_status["unknown"],
                           "its status is unknown")
    claimed_ports = {(p["switch_id"], p["port"]) for p in findings["ports_down"]}
    actual_ports = _ports_down(devices)
    errors += [f"ports_down is missing {s} port {n} (reported down)"
               for s, n in sorted(actual_ports - claimed_ports)]
    errors += [f"ports_down lists {s} port {n}, but it was not reported down"
               for s, n in sorted(claimed_ports - actual_ports)]
    faulty = by_status["offline"] | by_status["unknown"]
    errors += [f"likely_causes names {d}, which is neither offline nor unknown"
               for d in sorted(_ids(findings["likely_causes"]) - faulty)]
    return errors


def retry_prompt(errors: list[str]) -> str:
    listed = "\n".join(f"- {e}" for e in errors)
    return ("Your structured findings do not match the recorded check results:\n"
            f"{listed}\n\n"
            "Return corrected findings in the required format. Do not call any tools: "
            "use only the results you already received.")
