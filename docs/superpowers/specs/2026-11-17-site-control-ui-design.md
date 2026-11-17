# Site control UI for the mock site — design

Date: 2026-11-17
Status: implemented (branch site-control-ui)

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
| Status computed via `mcp_server.checks.check_state` (no-op sleep), split out of `check_device`, which the agent's tool still uses | `mock_site.poll.poll_device` directly | Panel must show what the agent will see; they differ when slow > poll deadline (→ `unknown`) |
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
- `read_state(path) -> (state, error)`: loads the file and validates its shape
  and every fault entry (known type; `device` is a str; `port`/`ms` are ints,
  not bools). Shared by `site_model` and `actions`: actions may import view;
  view may not import actions.
- `site_model(path) -> SiteModel`: loads the file **once** and polls every
  device from that one snapshot with `check_state(id, state, sleep=no-op)`.
  Contains:
  - per device: id, type, `status` (`online|offline|unknown`), `slow`
    (online with latency above the default 5ms), latency_ms, `cause`, and the
    device's own active faults;
  - cause rules: unknown keeps the poll message, plus the device's own
    slowness, plus upstream causes (e.g. "via SW-01 port 3 down",
    "switch SW-01 slow 1500ms"); offline drops slowness (it never answered);
  - per switch: 24 ports, each `{port, cabled_to | None, down}`. Ports show
    configuration (cabling and injected port faults), even while the switch is
    unreachable; device dots show what a poll returns;
  - counts by status display (online / slow / offline / unknown);
  - active faults list;
  - `error`: set when the state file can't be read (then devices are omitted).
- Labels: 🟢 online · 🟡 online but slow (`🟡 CAM-06 800ms`) · 🔴 offline ·
  an unknown device is `⚪ <ID> unknown`; ▫️ for an empty, up port.

### `site_ui/actions.py`
Each function: `load_state(path)` at click time → one `faults.*` call →
`save_state(path, new)`. On `ValueError` nothing is written and
the error is returned as a message.
- `inject(path, kind, device, *, port=None, ms=None)` — kind ∈
  offline / timeout / slow / port_down
- `clear_device(path, device)`, `bring_port_up(path, switch, port)`
- `reset(path)` — also the recovery for an unreadable state file
  (it does not load the file first)
Every action returns `ActionResult(ok, message)` and never raises: failed
saves (`OSError`), non-int `port`/`ms` and wrong-shape files all return
`ok=False`. Messages look like "CAM-06 slow 800ms", "SW-01 port 3 down",
"CAM-01 set offline".

### `site_ui/app.py`
- Header: site, counts by dot, active-fault count, state path.
- Left: per switch, a switch button, 24 port buttons in 2 rows of 12, then its
  cabled devices as buttons. The selected port or device button is highlighted
  (`type="primary"`).
- Right: action panel for the selection (kept in `st.session_state`):
  - port: **Bring port up** or **Take port down** (empty ports too)
  - device: **Offline**, **Timeout**, **Slow [ms]** + Set, **Clear**
  - switch: same as device; Clear notes it also brings its ports up
  - below: the last action result, then the active faults list, then **Reset
    all faults** at the bottom, which needs a confirm checkbox.
- Action results are a persistent, timestamped `st.success`/`st.error` above
  the faults list, cleared on a new selection. There is no toast. Selecting
  anything also un-ticks the reset confirmation.
- Topology is drawn in `st.fragment(run_every=2)` so CLI changes appear;
  selection survives the refresh.

## Error handling
| Situation | Behaviour |
|---|---|
| State file missing | Healthy site (as the CLI); first action creates it |
| State file unreadable | Red banner with path; fault controls are **not drawn**; only Reset is shown, labelled "Overwrite unreadable file with a healthy site" |
| `faults.*` rejects input | `ActionResult(ok=False)`, shown as `st.error`; file unchanged |
| `check_state` internal failure | Device shows ⚪ unknown with the error text |
| Concurrent CLI write | Accepted race; actions re-read at click time; documented in `actions.py` |

## Testing (TDD)
Files (the UI tests use `importorskip("streamlit")`; the rest run on 3.10):
- `tests/test_faults.py`: `clear_port` removes only that port_down; keeps the
  switch condition and other ports; rejects non-switch and out-of-range port.
- `tests/test_checks.py`: `check_state` parity with `check_device`.
- `tests/test_site_view.py`: topology, causes, slow vs the poll deadline,
  single load of the file, malformed fault entries and unreadable file set
  `error`.
- `tests/test_site_actions.py`: each action changes a temp state file as
  expected; bad input leaves the file byte-identical; reset fixes a corrupt
  file.
- `tests/test_site_agreement.py`: end to end, no model: inject via
  `site_ui.actions`, then compare the real `check_device` with `site_model`.
- `tests/test_site_app.py` (`AppTest`): selection, actions, single error
  banner, reset confirmation, unreadable file.
- `tests/test_ui_readonly.py` and `tests/test_site_ui_writes.py`: AST guards.
  `ui/` may not import `site_ui`. In `site_ui/`, only `actions.py` imports
  `mock_site.faults` or writer names. Writers reached through attributes,
  relative imports of actions, `Path.open` in write mode, and shutil/subprocess
  are all caught.
- `tests/ast_guards.py`: the shared scanners.

## Packaging and docs
- `pyproject.toml`: add `site_ui` to packages; reuse the `[ui]` extra. No
  new dependencies.
- Run: `python -m streamlit run site_ui/app.py --server.address localhost --server.port 8502`
- CLAUDE.md: add `site_ui/` to Structure, the run command to Commands, and
  "10. Site control UI" to the build order.

## Out of scope
Running checks from the UI; editing the inventory or cabling; multiple sites;
undo/history of actions.
