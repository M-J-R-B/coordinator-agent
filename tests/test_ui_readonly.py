"""The report UI is read-only: enforce it on the source, not just by convention.

Fails if anything in ui/ imports a module or name that changes state (runs a
check, injects a fault, saves a baseline/report/state), imports the site
control panel, reaches a writer through an attribute, or calls a writing file
API. The scanners live in tests/ast_guards.py and are shared with
tests/test_site_ui_writes.py.
"""
import ast

from tests.ast_guards import REPO, imported_modules, sources, write_calls, writer_attribute_calls

UI_DIR = REPO / "ui"

FORBIDDEN_MODULES = {"agent.run", "agent.baseline", "agent.report", "agent.decision",
                     "agent.hooks", "mock_site.faults", "mock_site.state",
                     "mock_site.__main__", "mcp_server.server", "subprocess", "shutil"}
FORBIDDEN_NAMES = {"write_json_atomic", "save_state", "save_baseline", "save_report",
                   "finalize", "run_check", "EventLog"}


def test_no_state_changing_imports():
    for path, tree in sources(UI_DIR):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                bad = [a.name for a in node.names if a.name in FORBIDDEN_MODULES]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                bad = [module] if module in FORBIDDEN_MODULES else []
                bad += [a.name for a in node.names if a.name in FORBIDDEN_NAMES]
            else:
                continue
            assert not bad, f"{path.name}:{node.lineno} imports {bad}"


def test_ui_does_not_import_the_site_control_panel():
    for path, tree in sources(UI_DIR):
        bad = [m for m in imported_modules(tree) if m == "site_ui" or m.startswith("site_ui.")]
        assert not bad, f"{path.name} imports {bad}"


def test_no_file_writes():
    for path, tree in sources(UI_DIR):
        found = write_calls(tree)
        assert not found, f"{path.name}: {found}"


def test_no_writer_reached_through_an_attribute():
    for path, tree in sources(UI_DIR):
        found = writer_attribute_calls(tree)
        assert not found, f"{path.name}: {found}"


def test_scanner_catches_writes_and_ignores_string_replace():
    """The scanner itself: flags real writes, not str.replace."""
    def flagged(src: str) -> bool:
        return bool(write_calls(ast.parse(src)))
    assert flagged("p.write_text('x')")
    assert flagged("os.replace(a, b)")
    assert flagged("p.replace(target)")
    assert flagged("p.mkdir()")
    assert flagged("open(p, 'w')")
    assert flagged("open(p, mode='a')")
    assert flagged("p.open('w')")
    assert flagged("Path(p).open(mode='a')")
    assert not flagged("p.open()")
    assert not flagged("p.open('rb')")
    assert not flagged("s.replace('T', ' ')")
    assert not flagged("p.read_text()")
    assert not flagged("open(p, 'rb')")
    assert writer_attribute_calls(ast.parse("from mock_site import state\nstate.save_state(p, s)"))
    assert not writer_attribute_calls(ast.parse("from mock_site.state import load_state"))
