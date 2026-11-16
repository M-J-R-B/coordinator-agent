from pathlib import Path

from agent.decision import Decisions, create_decision_server
from agent.options import (CHECK_TOOL, DEFAULT_MODEL, ESCALATE_TOOL, LIST_TOOL,
                           RELEASE_TOOL, build_options)


def opts(**kw):
    return build_options(hooks={}, **kw)


def test_default_model_is_haiku():
    assert DEFAULT_MODEL == "claude-haiku-5-5"
    assert opts().model == "claude-haiku-5-5"


def test_model_override():
    assert opts(model="claude-sonnet-5-5").model == "claude-sonnet-5-5"


def test_coordinator_has_only_agent_builtin_and_locked_down():
    o = opts()
    assert o.tools == ["Agent"]
    assert o.permission_mode == "dontAsk"
    assert o.strict_mcp_config is True
    assert o.setting_sources == []
    assert set(o.agents) == {"cctv-checker", "network-checker", "pos-checker"}


def test_precheck_has_no_decision_tools():
    o = opts()
    assert o.allowed_tools == ["Agent", LIST_TOOL, CHECK_TOOL]
    assert "decision" not in o.mcp_servers


def test_postcheck_adds_decision_server_and_tools():
    server = create_decision_server(Decisions())
    o = opts(decision_server=server)
    assert o.mcp_servers["decision"] is server
    assert RELEASE_TOOL in o.allowed_tools and ESCALATE_TOOL in o.allowed_tools


def test_hooks_passed_through():
    marker = {"PreToolUse": []}
    assert build_options(hooks=marker).hooks is marker


def test_mcp_server_launch_config(tmp_path):
    o = opts(state_path=tmp_path / "s.json")
    server = o.mcp_servers["devices"]
    assert server["args"] == ["-m", "mcp_server"]
    assert server["env"]["PRECHECK_STATE_PATH"] == str(tmp_path / "s.json")
    assert Path(server["env"]["PYTHONPATH"], "mcp_server").is_dir()


def test_run_limits():
    o = opts()
    assert o.max_turns == 40
    assert o.max_budget_usd == 1.0
