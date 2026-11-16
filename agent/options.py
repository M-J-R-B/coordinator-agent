"""Agent SDK configuration: the agent can call the two device tools and nothing else."""
import sys
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions

from agent.prompts import SYSTEM_PROMPT
from agent.storage import REPO_ROOT

DEFAULT_MODEL = "claude-haiku-5-5"
SERVER_NAME = "devices"
LIST_TOOL = f"mcp__{SERVER_NAME}__list_devices"
CHECK_TOOL = f"mcp__{SERVER_NAME}__check_device"
ALLOWED_TOOLS = [LIST_TOOL, CHECK_TOOL]
MAX_TURNS = 40
MAX_BUDGET_USD = 1.0


def _server_config(state_path: Path | None) -> dict:
    env = {"PYTHONPATH": str(REPO_ROOT)}
    if state_path is not None:
        env["PRECHECK_STATE_PATH"] = str(state_path)
    return {"type": "stdio", "command": sys.executable,
            "args": ["-m", "mcp_server"], "env": env}


def build_options(model: str = DEFAULT_MODEL,
                  state_path: Path | None = None) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=model,
        mcp_servers={SERVER_NAME: _server_config(state_path)},
        strict_mcp_config=True,      # ignore any other MCP servers on this machine
        tools=[],                    # remove built-in tools (Bash, Read, Write, ...)
        allowed_tools=ALLOWED_TOOLS,
        permission_mode="dontAsk",   # anything not allowed is denied, never prompted
        setting_sources=[],          # don't load user/project settings or CLAUDE.md
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
        cwd=str(REPO_ROOT),
    )
