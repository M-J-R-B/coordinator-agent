"""Fixed inventory and cabling for STORE-001."""
from dataclasses import dataclass

SITE_ID = "STORE-001"
PORT_COUNT = 24


@dataclass(frozen=True)
class Device:
    device_id: str
    type: str  # "camera" | "switch" | "pos"


def _build_inventory() -> dict[str, Device]:
    devices = [Device(f"CAM-{i:02d}", "camera") for i in range(1, 9)]
    devices += [Device(f"SW-{i:02d}", "switch") for i in range(1, 3)]
    devices += [Device(f"POS-{i:02d}", "pos") for i in range(1, 5)]
    return {d.device_id: d for d in devices}


INVENTORY: dict[str, Device] = _build_inventory()

# device_id -> (switch_id, port). Cameras on SW-01 1-8, POS on SW-02 1-4.
PORT_MAP: dict[str, tuple[str, int]] = {
    **{f"CAM-{i:02d}": ("SW-01", i) for i in range(1, 9)},
    **{f"POS-{i:02d}": ("SW-02", i) for i in range(1, 5)},
}


def get_device(device_id: str) -> Device:
    """Return the device, or raise KeyError if it is not at this site."""
    return INVENTORY[device_id]


def port_label(switch_id: str, port: int) -> str | None:
    """Name of the device cabled to this switch port, like a port description."""
    for device_id, location in PORT_MAP.items():
        if location == (switch_id, port):
            return device_id
    return None
