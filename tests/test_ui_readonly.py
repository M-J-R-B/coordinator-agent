"""The report UI is read-only: enforce it on the source, not just by convention.

Fails if anything in ui/ imports a module or name that changes state (runs a
check, injects a fault, saves a baseline/report/state), imports the site
control panel, or calls a writing file API. The scanners are reused by
tests/test_site_ui_writes.py.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
UI_DIR = REPO / "ui"

FORBIDDEN_MODULES = {"agent.run", "agent.baseline", "agent.report", "agent.decision",
                     "agent.hooks", "mock_site.faults", "mock_site.state",
                     "mock_site.__main__", "mcp_server.server", "subprocess", "shutil"}
FORBIDDEN_NAMES = {"write_json_atomic", "save_state", "save_baseline", "save_report",
                   "finalize", "run_check", "EventLog"}
# Path / file-object methods that change the filesystem.
WRITING_METHODS = {"write_text", "write_bytes", "unlink", "mkdir", "rename", "rmdir",
                   "touch", "symlink_to", "hardlink_to", "chmod"}
# os.<name>(...) calls that change the filesystem.
WRITING_OS = {"replace", "remove", "rename", "unlink", "makedirs", "mkdir", "rmdir",
              "removedirs", "truncate"}


def writes(func: ast.Attribute, call: ast.Call) -> bool:
    if isinstance(func.value, ast.Name) and func.value.id == "os":
        return func.attr in WRITING_OS
    if func.attr == "replace":
        # Path.replace(target) takes one argument; str.replace(old, new) takes two.
        return len(call.args) == 1
    return func.attr in WRITING_METHODS


def _opens_for_writing(call: ast.Call) -> bool:
    modes = [a.value for a in call.args[1:2] if isinstance(a, ast.Constant)]
    modes += [k.value.value for k in call.keywords
              if k.arg == "mode" and isinstance(k.value, ast.Constant)]
    return not all(set(str(m)) <= set("rbt") for m in modes)


def write_calls(tree: ast.AST) -> list[str]:
    """Every call in the tree that writes to the filesystem, as 'line: what'."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and writes(func, node):
            found.append(f"{node.lineno}: .{func.attr}()")
        if isinstance(func, ast.Name) and func.id == "open" and _opens_for_writing(node):
            found.append(f"{node.lineno}: open() for writing")
    return found


def imported_modules(tree: ast.AST) -> list[str]:
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return mods


def sources(directory: Path = UI_DIR):
    files = sorted(directory.glob("*.py"))
    assert files, f"{directory.name}/ has no Python files"
    return [(f, ast.parse(f.read_text(encoding="utf-8"))) for f in files]


def test_no_state_changing_imports():
    for path, tree in sources():
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
    for path, tree in sources():
        bad = [m for m in imported_modules(tree) if m == "site_ui" or m.startswith("site_ui.")]
        assert not bad, f"{path.name} imports {bad}"


def test_no_file_writes():
    for path, tree in sources():
        found = write_calls(tree)
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
    assert not flagged("s.replace('T', ' ')")
    assert not flagged("p.read_text()")
    assert not flagged("open(p, 'rb')")
