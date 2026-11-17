"""python -m evals: run the scenarios against the real agent and write the scorecard.

Spends model usage, so it refuses to run unless PRECHECK_LIVE=1 is set (the
same switch tests/test_live.py uses).
"""
import argparse
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import anyio

from agent.options import DEFAULT_MODEL
from evals.runner import run_all
from evals.scenarios import SCENARIOS
from evals.scorecard import summarize, write

REPO_ROOT = Path(__file__).resolve().parent.parent


def _select(only: list[str] | None):
    if not only:
        return list(SCENARIOS), []
    known = {s.id: s for s in SCENARIOS}
    return [known[i] for i in only if i in known], [i for i in only if i not in known]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals", description="Coordinator Agent scorecard")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--only", nargs="+", metavar="SCENARIO_ID",
                        help="run only these scenarios")
    parser.add_argument("--out-dir", default=None,
                        help="write scorecard.json and SCORECARD.md here instead of the repo")
    args = parser.parse_args(argv)

    if os.environ.get("PRECHECK_LIVE") != "1":
        print("This runs the real agent and spends model usage. "
              "Set PRECHECK_LIVE=1 to confirm.", file=sys.stderr)
        return 2
    scenarios, unknown = _select(args.only)
    if unknown:
        print(f"Unknown scenario id(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    if args.out_dir:
        json_path = Path(args.out_dir) / "scorecard.json"
        markdown_path = Path(args.out_dir) / "SCORECARD.md"
    else:
        json_path = REPO_ROOT / "evals" / "results" / "scorecard.json"
        markdown_path = REPO_ROOT / "SCORECARD.md"

    with tempfile.TemporaryDirectory(prefix="evals-") as workdir:
        results = anyio.run(lambda: run_all(scenarios, model=args.model, workdir=Path(workdir)))
    summary = summarize(results, model=args.model,
                        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    write(summary, results, json_path=json_path, markdown_path=markdown_path)
    cost = summary["total_cost_usd"]
    print(f"{summary['correct']} of {summary['scenarios']} correct, "
          f"{summary['false_releases']} false releases, "
          f"total cost {'not recorded' if cost is None else f'${cost:.4f}'}")
    print(f"Wrote {markdown_path} and {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
