"""Site control panel for STORE-001: inject and clear faults on the mock site.

Run:   python -m streamlit run site_ui/app.py --server.address localhost --server.port 8502
State: $PRECHECK_STATE_PATH, default <repo>/data/site_state.json (the file the agent polls).
Every write goes through site_ui.actions, inside on_click callbacks.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # `streamlit run` puts site_ui/ first

import streamlit as st  # noqa: E402

from site_ui import actions, view  # noqa: E402

REFRESH_SECONDS = 2


# ---- callbacks (run before the rerun, so the redraw shows the new state) ----

def _select(selection: tuple) -> None:
    st.session_state["sel"] = selection
    st.session_state.pop("last", None)
    st.session_state["reset-confirm"] = False


def _run(action, *args, **kwargs) -> None:
    result = action(view.state_path(), *args, **kwargs)
    st.session_state["last"] = (time.strftime("%H:%M:%S"), result)


def _slow(device_id: str) -> None:
    _run(actions.inject, "slow", device_id, ms=int(st.session_state["slow-ms"]))


def _reset() -> None:
    _run(actions.reset)
    st.session_state["reset-confirm"] = False


# ---- drawing ----

def header(model: view.SiteModel) -> None:
    c = model.counts
    st.title(f"{model.site} site control")
    st.caption(f"🟢 {c['online']}  🟡 {c['slow']}  🔴 {c['offline']}  ⚪ {c['unknown']}"
               f" · {len(model.faults)} active faults · state: {view.state_path()}"
               f" · refresh {REFRESH_SECONDS}s")


def _kind(selection: tuple) -> str:
    return "primary" if st.session_state.get("sel") == selection else "secondary"


def device_button(where, d: view.DeviceView) -> None:
    selection = ("device", d.device_id)
    where.button(view.device_label(d), key=f"dev-{d.device_id}", type=_kind(selection),
                 on_click=_select, args=(selection,))


def switch_block(model: view.SiteModel, switch_id: str) -> None:
    device_button(st, model.devices[switch_id])
    ports = model.ports[switch_id]
    for row in (ports[:12], ports[12:]):
        for col, p in zip(st.columns(12), row):
            selection = ("port", switch_id, p.port)
            col.button(view.port_text(p), key=f"port-{switch_id}-{p.port}",
                       type=_kind(selection), on_click=_select, args=(selection,))
    attached = [d for d in model.devices.values() if d.switch_id == switch_id]
    for col, d in zip(st.columns(len(attached)), attached):
        device_button(col, d)


def port_panel(model: view.SiteModel, switch_id: str, port: int) -> None:
    p = model.ports[switch_id][port - 1]
    st.subheader(f"{switch_id} · port {port}")
    st.write(f"Cabled to: {p.cabled_to or 'nothing'} · state: {'down' if p.down else 'up'}")
    if p.down:
        st.button("Bring port up", key="act-port-up",
                  on_click=_run, args=(actions.bring_port_up, switch_id, port))
    else:
        st.button("Take port down", key="act-port-down", on_click=_run,
                  args=(actions.inject, "port_down", switch_id), kwargs={"port": port})


def device_panel(model: view.SiteModel, device_id: str) -> None:
    d = model.devices[device_id]
    st.subheader(view.device_label(d))
    st.write(f"Status: {d.status}" + (f" · cause: {d.cause}" if d.cause else ""))
    left, right = st.columns(2)
    left.button("Offline", key="act-offline", on_click=_run,
                args=(actions.inject, "offline", device_id))
    right.button("Timeout", key="act-timeout", on_click=_run,
                 args=(actions.inject, "timeout", device_id))
    st.number_input("Slow (ms)", min_value=1, value=800, step=100, key="slow-ms")
    st.button("Set slow", key="act-slow", on_click=_slow, args=(device_id,))
    note = " (also brings its ports up)" if d.type == "switch" else ""
    st.button(f"Clear {device_id}{note}", key="act-clear", on_click=_run,
              args=(actions.clear_device, device_id))


def panel(model: view.SiteModel) -> None:
    selection = st.session_state.get("sel")
    if selection is None:
        st.info("Select a port or a device.")
    elif selection[0] == "port":
        port_panel(model, selection[1], selection[2])
    else:
        device_panel(model, selection[1])


def faults_box(model: view.SiteModel) -> None:
    st.markdown(f"**Active faults ({len(model.faults)})**")
    for f in model.faults:
        st.markdown(f"- {view.fault_text(f)}")


def last_result(errors: bool = True) -> None:
    last = st.session_state.get("last")
    if not last:
        return
    stamp, result = last
    if result.ok:
        st.success(f"{stamp} · {result.message}")
    elif errors:
        st.error(f"{stamp} · {result.message}")


def reset_box(unreadable: bool) -> None:
    label = ("Overwrite unreadable file with a healthy site" if unreadable
             else "Reset all faults")
    confirmed = st.checkbox("Confirm reset", key="reset-confirm")
    st.button(label, key="reset", disabled=not confirmed, on_click=_reset)


@st.fragment(run_every=REFRESH_SECONDS)
def body() -> None:
    model = view.site_model(view.state_path())
    header(model)
    if model.error:
        st.error(model.error)
        last_result(errors=False)
        reset_box(unreadable=True)
        return
    left, right = st.columns([3, 1])
    with left:
        for switch_id in view.SWITCHES:
            with st.container(border=True):
                switch_block(model, switch_id)
    with right:
        panel(model)
        last_result()
        faults_box(model)
        reset_box(unreadable=False)


st.set_page_config(page_title="Site control", layout="wide")
body()
