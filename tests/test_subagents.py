from agent.options import CHECK_TOOL, LIST_TOOL
from agent.subagents import build_subagents


def test_three_domain_subagents():
    agents = build_subagents()
    assert set(agents) == {"cctv-checker", "network-checker", "pos-checker"}


def test_subagents_only_get_device_tools_and_inherit_model():
    for agent in build_subagents().values():
        assert agent.tools == [LIST_TOOL, CHECK_TOOL]
        assert agent.model == "inherit"
        assert agent.maxTurns == 20
        assert agent.description


def test_each_prompt_names_its_device_type():
    agents = build_subagents()
    assert "device_type \"camera\"" in agents["cctv-checker"].prompt
    assert "device_type \"switch\"" in agents["network-checker"].prompt
    assert "device_type \"pos\"" in agents["pos-checker"].prompt
    assert "port" in agents["network-checker"].prompt
