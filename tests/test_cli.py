import subprocess
import sys

from mock_site.__main__ import main
from mock_site.state import load_state


def run(tmp_path, *args):
    return main(["--state", str(tmp_path / "state.json"), *args])


def test_inject_port_down_then_status(tmp_path, capsys):
    assert run(tmp_path, "inject", "port-down", "SW-01", "3") == 0
    capsys.readouterr()
    assert run(tmp_path, "status") == 0
    out = capsys.readouterr().out
    assert "CAM-03" in out and "UNREACHABLE" in out
    assert "down: 3 (CAM-03)" in out


def test_each_inject_command_writes_state(tmp_path):
    run(tmp_path, "inject", "offline", "CAM-03")
    run(tmp_path, "inject", "slow", "POS-02", "--ms", "3000")
    run(tmp_path, "inject", "timeout", "CAM-01")
    types = [f["type"] for f in load_state(tmp_path / "state.json")["faults"]]
    assert types == ["offline", "slow", "timeout"]


def test_status_shows_timeout(tmp_path, capsys):
    run(tmp_path, "inject", "timeout", "CAM-01")
    run(tmp_path, "status")
    assert "TIMEOUT" in capsys.readouterr().out


def test_clear_and_reset(tmp_path):
    run(tmp_path, "inject", "offline", "CAM-03")
    run(tmp_path, "inject", "offline", "CAM-04")
    run(tmp_path, "clear", "CAM-03")
    assert len(load_state(tmp_path / "state.json")["faults"]) == 1
    run(tmp_path, "reset")
    assert load_state(tmp_path / "state.json")["faults"] == []


def test_invalid_fault_exits_2(tmp_path, capsys):
    assert run(tmp_path, "inject", "port-down", "CAM-01", "3") == 2
    assert "error" in capsys.readouterr().err.lower()


def test_python_dash_m_entry_point(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "mock_site", "--state", str(tmp_path / "s.json"), "status"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "SW-01" in result.stdout
