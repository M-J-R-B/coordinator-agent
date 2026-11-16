# Pre/Post-Check Agent

## Goal
An agent that checks a retail site's systems before and after a field
technician works, then decides whether the tech can be released.
This is a practice project for the Claude Certified Architect - Foundations
exam, so prefer clear, explainable designs over clever ones.

## Workflow
1. Pre-check: poll every device at the site and save a baseline.
2. Tech works (simulated by injecting or clearing faults).
3. Post-check: poll again and diff against the baseline.
4. Decision: release the tech, or hold and escalate with the affected devices.

## Mock site
No real hardware. One simulated site, STORE-001:
- 8 CCTV cameras (CAM-01 to CAM-08)
- 2 network switches (SW-01, SW-02), 24 ports each
- 4 POS terminals (POS-01 to POS-04)

The simulator must support fault injection: device offline, switch port
down, slow response, and tool timeout.

## Stack
- Python 3.10+
- Claude Agent SDK for Python (`claude-agent-sdk`)
- MCP server (Python) exposing the device tools
- pytest for tests
- Site state and baselines stored as JSON files in `data/`

Check the current Agent SDK and MCP docs before writing SDK code.
Do not rely on remembered API signatures.

## Structure
- `mock_site/`  simulator and fault injection
- `mcp_server/` device tools
- `agent/`      coordinator, subagents, hooks
- `schemas/`    JSON schemas for reports
- `data/`       site state and saved baselines
- `tests/`

## Rules
- Status has three values: `online`, `offline`, `unknown`.
  A tool timeout or error is `unknown`, never `online`.
- A device already offline in the pre-check is not a post-check failure.
  Report it as `pre-existing`.
- The tech can be released only when the post-check has no new `offline`
  and no `unknown` devices. Enforce this in code (a hook), not only in
  the prompt.
- Tools return structured errors that separate "device offline" from
  "tool failed".
- The baseline is saved to disk and reloaded for the post-check. Never
  depend on conversation history to remember it.
- Every check ends with a report that validates against the JSON schema.

## Build order
1. Mock site with fault injection
2. MCP server with device tools
3. Single agent running pre-check and post-check
4. Coordinator with CCTV, network and POS subagents, plus the release hook
5. Report schema with validation and retry
6. CI check

Build one step at a time. Each step needs passing tests before the next.

## Working style
- Explain each design decision briefly, including the alternative you
  rejected, so I can learn the trade-off.
- Keep functions small. No extra dependencies without asking.
- Commands: `pytest` to test, `python -m mock_site` to run the simulator,
  `python -m mcp_server` to run the device tools over stdio.
