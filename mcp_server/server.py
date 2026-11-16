"""FastMCP wiring for the device tools (mcp 1.x API)."""
import json
import os
import time
from functools import partial
from pathlib import Path
from typing import Literal

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel

from mcp_server import checks
from mcp_server.models import ToolFailure
from mock_site.state import DEFAULT_STATE_PATH

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def _to_result(model: BaseModel) -> CallToolResult:
    """Same JSON in structuredContent (for code) and text (for the model).

    We return CallToolResult ourselves instead of a typed return value because
    FastMCP 1.x validates a declared output schema even on error results, which
    would reject our structured ToolFailure payloads.
    """
    data = model.model_dump()
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data))],
        structuredContent=data,
        isError=isinstance(model, ToolFailure),
    )


def _state_path(explicit: Path | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    return Path(os.environ.get("PRECHECK_STATE_PATH", DEFAULT_STATE_PATH))


def create_server(
    state_path: Path | None = None,
    poll_timeout_ms: int = checks.DEFAULT_POLL_TIMEOUT_MS,
    sleep=time.sleep,
) -> FastMCP:
    path = _state_path(state_path)
    server = FastMCP("store-devices")

    @server.tool(annotations=READ_ONLY)
    async def list_devices(
        device_type: Literal["camera", "switch", "pos"] | None = None,
    ) -> CallToolResult:
        """List the devices at site STORE-001, optionally only one type.

        Each entry gives device_id, type, and the switch_id/port it is cabled to
        (cameras are on SW-01, POS terminals on SW-02; switches have none).
        Use this first to know which device_ids exist.
        """
        return _to_result(checks.list_devices(device_type))

    @server.tool(annotations=READ_ONLY)
    async def check_device(device_id: str) -> CallToolResult:
        """Poll one device and report its status right now.

        Success (isError false): status is "online" (answered; latency_ms given)
        or "offline" (did not answer - a real finding about the device).
        For a switch, "ports" lists every port as up/down with the device cabled
        to it, so an offline camera can be traced to a port that is down.

        Failure (isError true): the CHECK failed, not necessarily the device.
        status is "unknown", with error_category "timeout" (retry may help,
        is_retryable true), "invalid_input" (bad device_id), or "internal".
        Never treat "unknown" as online.
        """
        call = partial(checks.check_device, device_id, path,
                       timeout_ms=poll_timeout_ms, sleep=sleep)
        return _to_result(await anyio.to_thread.run_sync(call))

    return server
