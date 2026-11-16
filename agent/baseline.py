"""The pre-check baseline lives on disk, never in conversation history."""
from pathlib import Path

from agent.storage import DATA_DIR, read_json, write_json_atomic

DEFAULT_BASELINE_DIR = DATA_DIR / "baselines"


def _path(site: str, baseline_dir: Path) -> Path:
    return Path(baseline_dir) / f"{site}.json"


def save_baseline(site: str, devices: dict, check_id: str, taken_at: str,
                  baseline_dir: Path = DEFAULT_BASELINE_DIR) -> Path:
    data = {"site": site, "check_id": check_id, "taken_at": taken_at, "devices": devices}
    return write_json_atomic(_path(site, baseline_dir), data)


def load_baseline(site: str, baseline_dir: Path = DEFAULT_BASELINE_DIR) -> dict | None:
    return read_json(_path(site, baseline_dir))
