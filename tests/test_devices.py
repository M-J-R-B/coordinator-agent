import pytest

from mock_site.devices import INVENTORY, PORT_COUNT, PORT_MAP, get_device, port_label


def test_inventory_has_expected_devices():
    cams = [d for d in INVENTORY.values() if d.type == "camera"]
    switches = [d for d in INVENTORY.values() if d.type == "switch"]
    pos = [d for d in INVENTORY.values() if d.type == "pos"]
    assert len(cams) == 8
    assert len(switches) == 2
    assert len(pos) == 4
    assert PORT_COUNT == 24


def test_cameras_on_sw01_and_pos_on_sw02():
    assert PORT_MAP["CAM-01"] == ("SW-01", 1)
    assert PORT_MAP["CAM-08"] == ("SW-01", 8)
    assert PORT_MAP["POS-01"] == ("SW-02", 1)
    assert PORT_MAP["POS-04"] == ("SW-02", 4)
    assert "SW-01" not in PORT_MAP


def test_port_label_names_connected_device():
    assert port_label("SW-01", 3) == "CAM-03"
    assert port_label("SW-01", 20) is None


def test_get_device_unknown_raises():
    with pytest.raises(KeyError):
        get_device("CAM-99")
