"""Coordinator configuration: delegates to subagents, decides only in the post-check."""
import sys
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions

from agent.options_base import (CHECK_TOOL, DEFAULT_MODEL, DEVICES_SERVER, ESCALATE_TOOL,
                                LIST_TOOL, MAX_BUDGET_USD, MAX_TURNS, RELEASE_TOOL)
from agent.prompts import coordinator_prompt
from agent.storage import REPO_ROOT
from agent.subagents import build_subagents

__all__ = ["build_options", "DEFAULT_MODEL", "LIST_TOOL", "CHECK_TOOL",
           "RELEASE_TOOL", "ESCALATE_TOOL"]


def _devices_server(state_path: Path | None) -> dict:
    env = {"PYTHONPATH": str(REPO_ROOT)}
    if state_path is not None:
        env["PRECHECK_STATE_PATH"] = str(state_path)
    return {"type": "stdio", "command": sys.executable,
            "args": ["-m", "mcp_server"], "env": env}


def build_options(*, hooks: dict, model: str = DEFAULT_MODEL,
                  state_path: Path | None = None,
                  decision_server: dict | None = None) -> ClaudeAgentOptions:
    """decision_server given = post-check (coordinator may release or escalate)."""
    servers = {DEVICES_SERVER: _devices_server(state_path)}
    allowed = ["Agent", LIST_TOOL, CHECK_TOOL]   # device tools: used by subagents only
    if decision_server is not None:
        servers["decision"] = decision_server
        allowed += [RELEASE_TOOL, ESCALATE_TOOL]
    return ClaudeAgentOptions(
        system_prompt=coordinator_prompt(decides=decision_server is not None),
        model=model,
        agents=build_subagents(),
        mcp_servers=servers,
        strict_mcp_config=True,      # ignore any other MCP servers on this machine
        tools=["Agent"],             # the only built-in tool: launching subagents
        allowed_tools=allowed,
        permission_mode="dontAsk",   # anything not allowed is denied, never prompted
        setting_sources=[],          # don't load user/project settings or CLAUDE.md
        hooks=hooks,
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
        cwd=str(REPO_ROOT),
    )
