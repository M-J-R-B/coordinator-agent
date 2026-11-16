"""CLI: python -m agent precheck | postcheck"""
import argparse
import sys

import anyio

from agent.options import DEFAULT_MODEL
from agent.run import run_check


def _print_precheck(report: dict) -> int:
    agent = report["agent"]
    print(f"{report['check_id']}  ({agent['model']}, {agent['check_calls']} checks, "
          f"cost ${agent['total_cost_usd'] or 0:.4f})")
    for d in report["devices"]:
        if d["status"] != "online":
            print(f"  {d['device_id']:<7} {d['status']}  {d.get('message', '')}")
    print(f"Baseline saved: {report['baseline_saved']}")
    if agent["error"]:
        print(f"Agent error: {agent['error']}")
    return 0 if report["baseline_saved"] else 1


def _print_postcheck(report: dict) -> int:
    print(report["check_id"])
    if report["error"]:
        print(f"  {report['error']}")
    if report["diff"]:
        for d in report["diff"]["devices"]:
            if d["classification"] != "ok":
                cause = f"  likely cause: {d['likely_cause']}" if d.get("likely_cause") else ""
                print(f"  {d['device_id']:<7} {d['classification']}{cause}")
    for reason in (report.get("agent_decision") or {}).get("release_denials", []):
        print(f"  release attempt blocked: {reason}")
    print(f"Decision: {report['decision'].upper()}")
    return 0 if report["decision"] == "release" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent", description="STORE-001 pre/post-check")
    parser.add_argument("kind", choices=["precheck", "postcheck"])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--state", default=None, help="simulator state file")
    args = parser.parse_args(argv)
    report = anyio.run(lambda: run_check(args.kind, model=args.model, state_path=args.state))
    if report["agent"] and report["agent"]["summary"]:
        print(report["agent"]["summary"].strip(), end="\n\n")
    printer = _print_precheck if args.kind == "precheck" else _print_postcheck
    code = printer(report)
    print(f"Event log: {report['event_log']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
