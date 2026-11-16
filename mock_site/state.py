"""Load and save the site state (the list of active faults) as JSON."""
import json
import os
from pathlib import Path

from mock_site.devices import SITE_ID

# Anchored to the repo, not the current directory, so the CLI and the MCP
# server always share one file no matter where each is launched from.
DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "site_state.json"


def empty_state() -> dict:
    return {"site": SITE_ID, "faults": []}


def load_state(path: Path) -> dict:
    """A missing file means a healthy site with no faults."""
    path = Path(path)
    if not path.exists():
        return empty_state()
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    """Write to a temp file, then atomically replace, so readers never see half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)
