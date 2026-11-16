from pathlib import Path

from agent.options import ALLOWED_TOOLS, DEFAULT_MODEL, build_options


def test_default_model_is_haiku():
    assert DEFAULT_MODEL == "claude-haiku-5-5"
    assert build_options().model == "claude-haiku-5-5"


def test_model_override():
    assert build_options(model="claude-sonnet-5-5").model == "claude-sonnet-5-5"


def test_only_device_tools_and_nothing_else():
    opts = build_options()
    assert opts.tools == []  # no built-in Bash/Read/Write...
    assert opts.allowed_tools == ALLOWED_TOOLS == [
        "mcp__devices__list_devices", "mcp__devices__check_device"]
    assert opts.permission_mode == "dontAsk"
    assert opts.strict_mcp_config is True
    assert opts.setting_sources == []


def test_mcp_server_launch_config(tmp_path):
    opts = build_options(state_path=tmp_path / "s.json")
    server = opts.mcp_servers["devices"]
    assert server["type"] == "stdio"
    assert server["args"] == ["-m", "mcp_server"]
    assert server["env"]["PRECHECK_STATE_PATH"] == str(tmp_path / "s.json")
    assert Path(server["env"]["PYTHONPATH"], "mcp_server").is_dir()


def test_run_limits():
    opts = build_options()
    assert opts.max_turns == 40
    assert opts.max_budget_usd == 1.0
