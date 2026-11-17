"""Turn scored results into a summary, a JSON file and a readable SCORECARD.md.

Design note: SCORECARD.md is regenerated on every run, but anything written by
hand below the notes marker is kept. The alternative (a separate notes file)
would separate the explanation of a wrong answer from the wrong answer.
"""
import json
from dataclasses import asdict
from pathlib import Path

from evals.runner import Result
from evals.scenarios import SCENARIOS

NOTES_MARKER = "<!-- notes -->"
_DESCRIPTIONS = {s.id: s.description for s in SCENARIOS}


def summarize(results: list[Result], *, model: str, generated_at: str) -> dict:
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    total = len(results)
    correct = sum(r.correct for r in results)
    return {
        "model": model,
        "generated_at": generated_at,
        "scenarios": total,
        "correct": correct,
        "accuracy": correct / total if total else None,
        "false_releases": sum(r.expected_decision == "hold" and r.actual_decision == "release"
                              for r in results),
        "false_holds": sum(r.expected_decision == "release" and r.actual_decision == "hold"
                           for r in results),
        "errors": sum(r.error is not None for r in results),
        "blocked_release_attempts": sum(r.blocked_release_attempts for r in results),
        "blocking_matches": sum(r.blocking_match for r in results),
        "schema_valid": sum(r.schema_valid for r in results),
        "total_cost_usd": sum(costs) if costs else None,
        "mean_cost_usd": sum(costs) / len(costs) if costs else None,
        "runs_without_cost": total - len(costs),
    }


def _usd(value: float | None) -> str:
    return "not recorded" if value is None else f"${value:.4f}"


def _cell(text: str | None) -> str:
    """Keep free text on one table row: no newlines, pipes escaped."""
    return " ".join(str(text or "").split()).replace("|", "\\|")


def _row(r: Result) -> str:
    actual = r.actual_decision or "none"
    if r.error:
        actual += f" (error: {_cell(r.error)})"
    elif not r.correct and r.agent_action:
        why = f": {_cell(r.agent_reason)}" if r.agent_reason else ""
        actual += f" (agent {r.agent_action}{why})"
    return (f"| {r.scenario_id} | {_cell(_DESCRIPTIONS.get(r.scenario_id))} | "
            f"{r.expected_decision} | {actual} | {'yes' if r.correct else 'NO'} | "
            f"{r.blocked_release_attempts} | {_usd(r.cost_usd)} |")


def render_markdown(summary: dict, results: list[Result]) -> str:
    s = summary
    lines = [
        "# Scorecard",
        "",
        "The agent is run against a simulated store (8 cameras, 2 switches, 4 POS terminals). "
        "Each scenario is one technician visit: a pre-check, faults injected while the "
        "technician works, then a post-check. The expected decision comes from the rules, "
        "not from the model.",
        "",
        f"- **Correct decisions:** {s['correct']} of {s['scenarios']}",
        f"- **False releases:** {s['false_releases']} "
        "(the technician was released when the rules say hold; this is the mistake that matters)",
        f"- **False holds:** {s['false_holds']}",
        f"- **Release attempts stopped by the code-level gate:** {s['blocked_release_attempts']} "
        "(the agent asked to release while a blocking fault was present, and the hook refused)",
        f"- **Runs that ended in an error:** {s['errors']}",
        f"- **Right devices named as blocking:** {s['blocking_matches']} of {s['scenarios']}",
        f"- **Reports that passed the schema:** {s['schema_valid']} of {s['scenarios']}",
        f"- **Cost per visit (pre-check plus post-check):** {_usd(s['mean_cost_usd'])} on average, "
        f"{_usd(s['total_cost_usd'])} in total",
    ]
    if s["runs_without_cost"]:
        lines.append(f"- {s['runs_without_cost']} runs had no cost recorded and are left out "
                     "of the cost figures.")
    lines += [
        f"- **Model:** {s['model']}",
        f"- **Run at:** {s['generated_at']}",
        "",
        "| Scenario | What happens | Expected | Actual | Correct | Blocked release attempts | Cost |",
        "|---|---|---|---|---|---|---|",
        *[_row(r) for r in results],
        "",
        "Reproduce with `PRECHECK_LIVE=1 python -m evals` (this spends model usage).",
        "",
    ]
    return "\n".join(lines)


def _kept_notes(markdown_path: Path) -> str:
    if not markdown_path.exists():
        return ""
    _, marker, notes = markdown_path.read_text(encoding="utf-8").partition(NOTES_MARKER)
    return notes if marker else ""


def write(summary: dict, results: list[Result], *, json_path: Path, markdown_path: Path) -> None:
    json_path, markdown_path = Path(json_path), Path(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "results": [asdict(r) for r in results]}
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    notes = _kept_notes(markdown_path) or "\n"
    markdown_path.write_text(
        render_markdown(summary, results) + "## Notes\n\n" + NOTES_MARKER + notes,
        encoding="utf-8")
