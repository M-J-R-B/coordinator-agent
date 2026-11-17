"""site_ui.view: the topology model, as the agent's check_device tool sees it."""
from mock_site import faults
from mock_site.state import empty_state, save_state
from site_ui import view


def model_for(tmp_path, *changes):
    state = empty_state()
    for change in changes:
        state = change(state)
    path = tmp_path / "site_state.json"
    save_state(path, state)
    return view.site_model(path)


def test_healthy_site_is_all_online(tmp_path):
    m = model_for(tmp_path)
    assert m.error is None
    assert {d.status for d in m.devices.values()} == {"online"}
    assert m.counts == {"online": 14, "slow": 0, "offline": 0, "unknown": 0}


def test_missing_file_is_a_healthy_site(tmp_path):
    m = view.site_model(tmp_path / "missing.json")
    assert m.error is None
    assert m.counts["online"] == 14


def test_port_down_takes_its_camera_offline_with_cause(tmp_path):
    m = model_for(tmp_path, lambda s: faults.inject_port_down(s, "SW-01", 3))
    cam = m.devices["CAM-03"]
    assert cam.status == "offline"
    assert cam.cause == "via SW-01 port 3 down"
    assert m.ports["SW-01"][2] == view.PortView(port=3, cabled_to="CAM-03", down=True)
    assert m.devices["SW-01"].status == "online"
    assert m.devices["SW-01"].cause == "ports down: 3"


def test_slow_past_the_poll_deadline_is_unknown(tmp_path):
    m = model_for(tmp_path, lambda s: faults.inject_slow(s, "CAM-06", 5000))
    cam = m.devices["CAM-06"]
    assert cam.status == "unknown"
    assert cam.latency_ms is None
    assert "timed out" in cam.cause


def test_slow_within_the_deadline_is_online_and_slow(tmp_path):
    m = model_for(tmp_path, lambda s: faults.inject_slow(s, "CAM-06", 800))
    cam = m.devices["CAM-06"]
    assert (cam.status, cam.slow, cam.latency_ms, cam.cause) == ("online", True, 800, "slow 800ms")
    assert m.counts == {"online": 13, "slow": 1, "offline": 0, "unknown": 0}


def test_slow_switch_slows_its_devices_only(tmp_path):
    m = model_for(tmp_path, lambda s: faults.inject_slow(s, "SW-01", 800))
    cam = m.devices["CAM-01"]
    assert (cam.latency_ms, cam.slow, cam.cause) == (805, True, "switch SW-01 slow 800ms")
    pos = m.devices["POS-01"]
    assert (pos.latency_ms, pos.slow) == (5, False)


def test_offline_switch_takes_its_devices_offline(tmp_path):
    m = model_for(tmp_path, lambda s: faults.inject_offline(s, "SW-01"))
    assert m.devices["CAM-01"].status == "offline"
    assert m.devices["CAM-01"].cause == "switch SW-01 offline"


def test_timeout_is_unknown(tmp_path):
    m = model_for(tmp_path, lambda s: faults.inject_timeout(s, "POS-02"))
    assert m.devices["POS-02"].status == "unknown"


def test_ports_show_cabling(tmp_path):
    m = model_for(tmp_path)
    assert [p.cabled_to for p in m.ports["SW-01"][:9]] == [f"CAM-0{i}" for i in range(1, 9)] + [None]
    assert m.ports["SW-02"][3].cabled_to == "POS-04"
    assert m.ports["SW-02"][4].cabled_to is None
    assert len(m.ports["SW-01"]) == 24


def test_unreadable_file_sets_error(tmp_path):
    path = tmp_path / "site_state.json"
    path.write_text("{not json", encoding="utf-8")
    m = view.site_model(path)
    assert m.error and "site_state.json" in m.error
    assert m.devices == {}
    assert m.counts == {"online": 0, "slow": 0, "offline": 0, "unknown": 0}


def test_wrong_shape_sets_error(tmp_path):
    path = tmp_path / "site_state.json"
    path.write_text('{"site": "STORE-001"}', encoding="utf-8")
    assert view.site_model(path).error


def test_state_path_follows_env(tmp_path, monkeypatch):
    monkeypatch.setenv(view.STATE_ENV, str(tmp_path / "x.json"))
    assert view.state_path() == tmp_path / "x.json"


def faulty(tmp_path):
    return model_for(
        tmp_path,
        lambda s: faults.inject_port_down(s, "SW-01", 3),
        lambda s: faults.inject_slow(s, "CAM-06", 800),
        lambda s: faults.inject_timeout(s, "POS-02"),
    )


def test_device_labels(tmp_path):
    m = faulty(tmp_path)
    assert view.device_label(m.devices["CAM-01"]) == "🟢 CAM-01"
    assert view.device_label(m.devices["CAM-03"]) == "🔴 CAM-03"
    assert view.device_label(m.devices["CAM-06"]) == "🟡 CAM-06 800ms"
    assert view.device_label(m.devices["POS-02"]) == "⚪ POS-02 unknown"


def test_port_text(tmp_path):
    ports = faulty(tmp_path).ports["SW-01"]
    assert [view.port_text(ports[i]) for i in (0, 2, 8)] == ["🟢1", "🔴3", "▫️9"]


def test_fault_text():
    assert view.fault_text({"type": "port_down", "device": "SW-01", "port": 3}) == "port_down SW-01 port 3"
    assert view.fault_text({"type": "slow", "device": "CAM-06", "ms": 800}) == "slow CAM-06 800ms"
    assert view.fault_text({"type": "offline", "device": "CAM-03"}) == "offline CAM-03"
