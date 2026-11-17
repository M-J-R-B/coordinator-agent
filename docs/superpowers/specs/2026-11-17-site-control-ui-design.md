# Site control UI for the mock site — design

Date: 2026-11-17
Status: approved in brainstorming, awaiting spec review

## Goal
A Streamlit control panel for STORE-001 that shows the site as a topology
(switch → port → device) and lets you inject and clear faults with buttons.
It replaces the `python -m mock_site inject …` CLI for workflow step 2
("tech works"). It does **not** run pre-checks or post-checks (no model use).

## Decisions (with rejected alternatives)
| Decision | Rejected | Why |
|---|---|---|
| Separate package `site_ui/`, own command and port | A page inside the read-only dashboard `ui/` | Keeps "ui/ never writes" a simple, test-enforced fact; the thing that changes state is separate from the thing that watches it |
| Topology layout | Status table + form; device cards | Only layout that shows a port going down and taking its camera with it |
| Status computed via `mcp_server.checks.check_device` (no-op sleep) | `mock_site.poll.poll_device` directly | Panel must show what the agent will see; they differ when slow > poll deadline (→ `unknown`) |
| Writes call `mock_site.faults.*` + `save_state` in-process | Subprocess to the CLI | Faster, testable, structured errors instead of parsing text |
| Emoji status dots on `st.button` labels | Custom HTML/JS component | No new dependency, testable with `AppTest`, no extra click channel |
| State path from `$PRECHECK_STATE_PATH`, else `data/site_state.json` | A new UI-specific env var | Same name as the MCP server, so the panel always edits the file the agent polls |
| Accept a millisecond lost-update race with the CLI | File locking | Stdlib locking is OS-specific (`msvcrt` vs `fcntl`); not worth it for a single-user simulator |

## Components
```
site_ui/
  __init__.py
  view.py     pure, no Streamlit: state path -> topology model
  actions.py  the only writes: load_state -> faults.<fn> -> save_state
  app.py      Streamlit: draws the model; buttons call actions
```

### `mock_site/faults.py` — new function
`clear_port(state, switch_id, port) -> dict`: removes only the `port_down`
fault for that switch port; keeps the switch's own condition
(offline/slow/timeout) and its other ports. Raises `ValueError` for a
non-switch device or a port outside 1–24 (same checks as `inject_port_down`).
Needed because `clear_device` on a switch clears its ports *and* its condition.

### `site_ui/view.py`
- `state_path() -> Path`: `$PRECHECK_STATE_PATH` or `DEFAULT_STATE_PATH`.
- `site_model(path) -> SiteModel`, built from one `load_state` plus one
  `check_device(id, path, sleep=no-op)` per device. Contains:
  - per device: id, type, `status` (`online|offline|unknown`), `slow`
    (online with latency above the default 5ms), latency_ms, error text
    (for unknown), `cause` (e.g. "via SW-01 port 3", "switch SW-01 offline",
    "slow 800ms + SW-01 0ms"), and the device's own active faults;
  - per switch: 24 ports, each `{port, cabled_to | None, state up|down}`;
  - counts by status display (online / offline / unknown / slow);
  - active faults list;
  - `error`: set when the state file can't be read (then devices are omitted).
- `dot(status, slow) -> str`: 🟢 online · 🟡 online but slow · 🔴 offline ·
  ⚪ unknown; ▫️ for an empty, up port.

### `site_ui/actions.py`
Each function: `load_state(path)` at click time → one `faults.*` call →
`save_state(path, new)`. On `ValueError`/`KeyError` nothing is written and
the error is returned as a message.
- `inject(path, kind, device, *, port=None, ms=None)` — kind ∈
  offline / timeout / slow / port_down
- `clear_device(path, device)`, `bring_port_up(path, switch, port)`
- `reset(path)` — also the recovery for an unreadable state file
  (it does not load the file first)
Returns `ActionResult(ok: bool, message: str)`.

### `site_ui/app.py`
- Header: site, counts by dot, active-fault count, **Reset all faults**
  (needs a confirm checkbox/second click).
- Left: per switch, a switch button, 24 port buttons in 2 rows of 12, then its
  cabled devices as buttons labelled with dot, id, and latency or "timeout".
- Right: action panel for the selection (kept in `st.session_state`):
  - port → **Bring port up** or **Take port down** (empty ports too)
  - device → **Offline**, **Timeout**, **Slow [ms]** + Set, **Clear**
  - switch → same as device; Clear notes it also brings its ports up
  - below: active faults list and last action result (`st.toast` +
    persistent caption)
- Topology is drawn in `st.fragment(run_every=2)` so CLI changes appear;
  selection survives the refresh.

## Error handling
| Situation | Behaviour |
|---|---|
| State file missing | Healthy site (as the CLI); first action creates it |
| State file unreadable | Red banner with path; all fault buttons disabled; only Reset, worded "Overwrite unreadable file with a healthy site" |
| `faults.*` rejects input | `st.error(message)`; file unchanged |
| `check_device` internal failure | Device shows ⚪ unknown with the error text |
| Concurrent CLI write | Accepted race; actions re-read at click time; documented in `actions.py` |

## Testing (TDD)
1. `tests/test_faults.py`: `clear_port` removes only that port_down; keeps
   switch condition and other ports; rejects non-switch and out-of-range port.
2. `tests/test_site_view.py` (plain pytest, runs on 3.10): port down →
   CAM-03 offline with cause; slow above poll deadline → unknown (timeout);
   slow below → online + slow; switch slow → attached devices slow; empty
   ports; counts; unreadable file → `error` set.
3. `tests/test_site_actions.py`: each action changes a temp state file as
   expected; bad input leaves the file byte-identical; reset fixes a corrupt
   file.
4. `tests/test_site_app.py` (`AppTest`, `importorskip("streamlit")`): starts
   without exceptions; select SW-01 port 3 → Take port down → CAM-03 shows 🔴;
   Reset needs confirmation; corrupt file disables fault buttons.
5. AST guards: extend `tests/test_ui_readonly.py` so `ui/` may not import
   `site_ui`; new `tests/test_site_ui_writes.py` so only `site_ui/actions.py`
   imports `save_state` or `mock_site.faults` and no `site_ui` file writes
   files directly.
6. End to end, no model: inject via `site_ui.actions`, then call the real
   `mcp_server.checks.check_device` and compare with `site_model`.

## Packaging and docs
- `pyproject.toml`: add `site_ui` to packages; reuse the `[ui]` extra. No
  new dependencies.
- Run: `python -m streamlit run site_ui/app.py --server.address localhost --server.port 8502`
- CLAUDE.md: add `site_ui/` to Structure, the run command to Commands, and
  "10. Site control UI" to the build order.

## Out of scope
Running checks from the UI; editing the inventory or cabling; multiple sites;
undo/history of actions.
