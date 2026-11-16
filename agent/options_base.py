"""Tool names and limits shared by options, subagents and hooks (no imports, no cycles)."""

DEFAULT_MODEL = "claude-haiku-5-5"
DEVICES_SERVER = "devices"
LIST_TOOL = f"mcp__{DEVICES_SERVER}__list_devices"
CHECK_TOOL = f"mcp__{DEVICES_SERVER}__check_device"
RELEASE_TOOL = "mcp__decision__release_technician"
ESCALATE_TOOL = "mcp__decision__hold_and_escalate"
MAX_TURNS = 40
MAX_BUDGET_USD = 1.0
