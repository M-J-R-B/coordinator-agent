"""The three domain subagents. Each sees only the device tools and its own task."""
from claude_agent_sdk import AgentDefinition

from agent.options_base import CHECK_TOOL, LIST_TOOL

SUBAGENT_MAX_TURNS = 20

_COMMON = """\
Procedure:
1. Call list_devices with device_type "{device_type}" to get your device_ids.
2. Call check_device for EVERY one of them. Do not skip any.
3. If a result has isError true and is_retryable true, retry that device once.
   Do not retry when is_retryable is false.
4. Never guess. A failed check means "unknown", which is never online.

Reply with one line per device: device_id, status, and the reason if it is not
online. {extra}"""

_DOMAINS = {
    "cctv-checker": (
        "Checks every CCTV camera at the site (CAM-xx) and reports each one's status.",
        "You check the CCTV cameras at a retail site.", "camera",
        "Cameras are cabled to switch SW-01; you cannot see switch ports, so do not "
        "guess a cause for an offline camera."),
    "network-checker": (
        "Checks the network switches (SW-xx) and every switch port, and reports ports that are down.",
        "You check the network switches at a retail site.", "switch",
        "For each online switch, also list every port whose state is down, with the "
        "label of the device cabled to it (e.g. 'SW-01 port 3 down (CAM-03)')."),
    "pos-checker": (
        "Checks every POS terminal at the site (POS-xx) and reports each one's status.",
        "You check the POS terminals at a retail site.", "pos",
        "POS terminals are cabled to switch SW-02; do not guess a cause for an "
        "offline terminal."),
}


def build_subagents() -> dict[str, AgentDefinition]:
    agents = {}
    for name, (description, role, device_type, extra) in _DOMAINS.items():
        prompt = role + " You can only observe; you cannot fix anything.\n\n" + \
            _COMMON.format(device_type=device_type, extra=extra)
        agents[name] = AgentDefinition(
            description=description, prompt=prompt,
            tools=[LIST_TOOL, CHECK_TOOL],
            model="inherit",            # follows the coordinator's --model
            maxTurns=SUBAGENT_MAX_TURNS)
    return agents
