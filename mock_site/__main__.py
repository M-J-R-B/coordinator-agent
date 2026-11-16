"""CLI for the simulator: python -m mock_site <command>."""
import argparse
import sys

from mock_site import faults
from mock_site.devices import INVENTORY
from mock_site.poll import DeviceTimeout, poll_device
from mock_site.state import DEFAULT_STATE_PATH, load_state, save_state


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mock_site", description="STORE-001 simulator")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="state file path")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="poll every device and show active faults")
    sub.add_parser("reset", help="clear all faults")
    clear = sub.add_parser("clear", help="clear all faults on one device")
    clear.add_argument("device")

    inject = sub.add_parser("inject", help="inject a fault").add_subparsers(
        dest="fault", required=True)
    inject.add_parser("offline").add_argument("device")
    inject.add_parser("timeout").add_argument("device")
    port_down = inject.add_parser("port-down")
    port_down.add_argument("device")
    port_down.add_argument("port", type=int)
    slow = inject.add_parser("slow")
    slow.add_argument("device")
    slow.add_argument("--ms", type=int, required=True)
    return parser


def _apply(args: argparse.Namespace, state: dict) -> dict:
    if args.command == "reset":
        return faults.reset(state)
    if args.command == "clear":
        return faults.clear_device(state, args.device)
    if args.fault == "offline":
        return faults.inject_offline(state, args.device)
    if args.fault == "timeout":
        return faults.inject_timeout(state, args.device)
    if args.fault == "port-down":
        return faults.inject_port_down(state, args.device, args.port)
    return faults.inject_slow(state, args.device, args.ms)


def _describe(device_id: str, state: dict) -> str:
    """One status line. Uses no real sleep: status should be instant."""
    try:
        reading = poll_device(device_id, state, sleep=lambda _s: None)
    except DeviceTimeout:
        return f"{device_id:<7} TIMEOUT"
    if not reading["reachable"]:
        return f"{device_id:<7} UNREACHABLE"
    line = f"{device_id:<7} reachable  {reading['latency_ms']}ms"
    down = [p for p in reading.get("ports", []) if p["state"] == "down"]
    if down:
        ports = ", ".join(f"{p['port']} ({p['label'] or 'empty'})" for p in down)
        line += f"  ports down: {ports}"
    return line


def _print_status(state: dict) -> None:
    print(f"Site {state['site']}")
    for device_id in INVENTORY:
        print("  " + _describe(device_id, state))
    print(f"Active faults: {len(state['faults'])}")
    for fault in state["faults"]:
        print(f"  {fault}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    state = load_state(args.state)
    if args.command == "status":
        _print_status(state)
        return 0
    try:
        new_state = _apply(args, state)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    save_state(args.state, new_state)
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
