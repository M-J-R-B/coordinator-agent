"""Compare a post-check against the baseline. Pure rules, no model involved."""

BLOCKING = {"new_offline", "unknown"}


def classify(before: str, after: str) -> str:
    if after == "unknown":
        return "unknown"
    if after == "online":
        return "recovered" if before == "offline" else "ok"
    # after == "offline": only provably pre-existing if the baseline saw it offline
    return "pre-existing" if before == "offline" else "new_offline"


def _ports(record: dict | None) -> dict[int, dict]:
    if not record or record.get("status") != "online" or not record.get("ports"):
        return {}
    return {p["port"]: p for p in record["ports"]}


def new_ports_down(baseline: dict, post: dict) -> list[dict]:
    """Ports up in the baseline and down now, on switches readable both times."""
    found = []
    for switch_id, record in post.items():
        if record.get("type") != "switch":
            continue
        before, after = _ports(baseline.get(switch_id)), _ports(record)
        for port, state in sorted(after.items()):
            if state["state"] == "down" and before.get(port, {}).get("state") == "up":
                found.append({"switch_id": switch_id, "port": port, "label": state["label"]})
    return found


def diff(baseline: dict, post: dict) -> dict:
    ports_down = new_ports_down(baseline, post)
    causes = {p["label"]: f"{p['switch_id']} port {p['port']} down"
              for p in ports_down if p["label"]}
    devices = []
    for device_id, record in post.items():
        before = baseline.get(device_id, {}).get("status", "unknown")
        entry = {"device_id": device_id, "type": record.get("type"),
                 "baseline_status": before, "status": record["status"],
                 "classification": classify(before, record["status"])}
        if entry["classification"] == "new_offline" and device_id in causes:
            entry["likely_cause"] = causes[device_id]
        devices.append(entry)
    blocking = [d["device_id"] for d in devices if d["classification"] in BLOCKING]
    return {"devices": devices, "new_ports_down": ports_down,
            "blocking": blocking, "release_allowed": not blocking}
