import pytest
from mcp import types

from agent.decision import Decisions, create_decision_server


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def call(server, name, args):
    request = types.CallToolRequest(method="tools/call",
                                    params=types.CallToolRequestParams(name=name, arguments=args))
    return await server["instance"].request_handlers[types.CallToolRequest](request)


@pytest.mark.anyio
async def test_release_tool_records_release():
    decisions = Decisions()
    await call(create_decision_server(decisions), "release_technician", {"reason": "all clear"})
    assert decisions.released is True
    assert decisions.release_reason == "all clear"


@pytest.mark.anyio
async def test_escalate_tool_records_devices():
    decisions = Decisions()
    await call(create_decision_server(decisions), "hold_and_escalate",
               {"reason": "CAM-03 down", "device_ids": ["CAM-03"]})
    assert decisions.escalated is True
    assert decisions.escalated_devices == ["CAM-03"]
    assert decisions.released is False


def test_server_name():
    assert create_decision_server(Decisions())["name"] == "decision"
