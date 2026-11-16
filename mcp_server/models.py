"""Result shapes returned by the device tools."""
from typing import Literal

from pydantic import BaseModel, Field

DeviceType = Literal["camera", "switch", "pos"]
ErrorCategory = Literal["timeout", "invalid_input", "internal"]


class DeviceInfo(BaseModel):
    device_id: str
    type: DeviceType
    switch_id: str | None = Field(description="Switch this device is cabled to")
    port: int | None = Field(description="Switch port this device is cabled to")


class DeviceList(BaseModel):
    site: str
    devices: list[DeviceInfo]


class PortState(BaseModel):
    port: int
    state: Literal["up", "down"]
    label: str | None = Field(description="Device cabled to this port, if any")


class DeviceCheck(BaseModel):
    """The device was polled and gave a definite answer."""
    device_id: str
    type: DeviceType
    status: Literal["online", "offline"]
    latency_ms: int | None
    ports: list[PortState] | None = None


class ToolFailure(BaseModel):
    """The check itself failed, so the device's real state is not known."""
    device_id: str
    status: Literal["unknown"] = "unknown"
    error_category: ErrorCategory
    is_retryable: bool
    message: str
