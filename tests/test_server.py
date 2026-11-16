"""Real MCP calls through an in-memory client <-> server connection."""
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_server.server import create_server
from mock_site import faults
from mock_site.state import empty_state, load_state, save_state


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def state_path(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, empty_state())
    return path


@pytest.fixture
async def session(state_path):
    server = create_server(state_path=state_path, sleep=lambda _s: None)
    async with create_connected_server_and_client_session(server) as client:
        yield client


@pytest.mark.anyio
async def test_tools_listed_read_only_with_descriptions(session):
    tools = {t.name: t for t in (await session.list_tools()).tools}
    assert set(tools) == {"list_devices", "check_device"}
    for tool in tools.values():
        assert tool.annotations.readOnlyHint is True
        assert tool.description
    assert "unknown" in tools["check_device"].description


@pytest.mark.anyio
async def test_list_devices_filter(session):
    result = await session.call_tool("list_devices", {"device_type": "pos"})
    assert result.isError is False
    ids = [d["device_id"] for d in result.structuredContent["devices"]]
    assert ids == ["POS-01", "POS-02", "POS-03", "POS-04"]


@pytest.mark.anyio
async def test_list_devices_rejects_bad_type(session):
    result = await session.call_tool("list_devices", {"device_type": "printer"})
    assert result.isError is True


@pytest.mark.anyio
async def test_online_device(session):
    result = await session.call_tool("check_device", {"device_id": "CAM-01"})
    assert result.isError is False
    assert result.structuredContent["status"] == "online"


@pytest.mark.anyio
async def test_offline_device_is_not_an_error(session, state_path):
    save_state(state_path, faults.inject_offline(load_state(state_path), "CAM-04"))
    result = await session.call_tool("check_device", {"device_id": "CAM-04"})
    assert result.isError is False
    assert result.structuredContent["status"] == "offline"


@pytest.mark.anyio
async def test_timeout_is_error_with_structured_payload(session, state_path):
    save_state(state_path, faults.inject_timeout(load_state(state_path), "CAM-01"))
    result = await session.call_tool("check_device", {"device_id": "CAM-01"})
    assert result.isError is True
    assert result.structuredContent == {
        "device_id": "CAM-01",
        "status": "unknown",
        "error_category": "timeout",
        "is_retryable": True,
        "message": result.structuredContent["message"],
    }
    assert "timeout" in result.content[0].text


@pytest.mark.anyio
async def test_unknown_device_is_invalid_input(session):
    result = await session.call_tool("check_device", {"device_id": "CAM-99"})
    assert result.isError is True
    assert result.structuredContent["error_category"] == "invalid_input"


@pytest.mark.anyio
async def test_fault_injected_between_calls_is_seen(session, state_path):
    first = await session.call_tool("check_device", {"device_id": "POS-03"})
    save_state(state_path, faults.inject_offline(load_state(state_path), "POS-03"))
    second = await session.call_tool("check_device", {"device_id": "POS-03"})
    assert first.structuredContent["status"] == "online"
    assert second.structuredContent["status"] == "offline"


@pytest.mark.anyio
async def test_stdio_entry_point(state_path):
    """python -m mcp_server starts and answers over stdio."""
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_server"],
        env={"PRECHECK_STATE_PATH": str(state_path)},
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            result = await client.call_tool("check_device", {"device_id": "SW-02"})
    assert result.structuredContent["status"] == "online"
    assert len(result.structuredContent["ports"]) == 24
