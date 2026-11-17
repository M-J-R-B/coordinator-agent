"""site_ui/ changes the site only through actions.py, and never writes files directly.

app.py and view.py may read (read_state, check_state) but may not import
mock_site.faults or save_state. view.py (the reader) may not import actions
(the writer); actions may import view. actions.py writes only via save_state.
"""
import ast

from tests.test_ui_readonly import REPO, imported_modules, sources, write_calls

SITE_UI = REPO / "site_ui"


def writer_imports(tree: ast.AST) -> list[str]:
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name == "mock_site.faults"]
        elif isinstance(node, ast.ImportFrom):
            names = {a.name for a in node.names}
            if node.module == "mock_site.faults" or (node.module == "mock_site" and "faults" in names):
                bad.append("mock_site.faults")
            if "save_state" in names:
                bad.append("save_state")
    return bad


def imports_actions(tree: ast.AST) -> bool:
    """True if the module imports site_ui.actions in any spelling."""
    if "site_ui.actions" in imported_modules(tree):
        return True
    return any(isinstance(n, ast.ImportFrom) and n.module == "site_ui"
               and any(a.name == "actions" for a in n.names) for n in ast.walk(tree))


def test_only_actions_imports_state_writers():
    for path, tree in sources(SITE_UI):
        if path.name != "actions.py":
            assert not writer_imports(tree), f"{path.name} imports {writer_imports(tree)}"


def test_guard_sees_the_writers_in_actions():
    """Self-test: if this fails the guard above is blind, not the code clean."""
    tree = dict(sources(SITE_UI))[SITE_UI / "actions.py"]
    assert set(writer_imports(tree)) == {"mock_site.faults", "save_state"}


def test_view_does_not_import_actions():
    tree = dict(sources(SITE_UI))[SITE_UI / "view.py"]
    assert not imports_actions(tree), "view.py (reader) must not import actions (writer)"


def test_imports_actions_detector():
    """Self-test for the detector above."""
    assert imports_actions(ast.parse("from site_ui import actions"))
    assert imports_actions(ast.parse("import site_ui.actions"))
    assert imports_actions(ast.parse("from site_ui.actions import inject"))
    assert not imports_actions(ast.parse("from site_ui import view"))


def test_site_ui_never_writes_files_directly():
    for path, tree in sources(SITE_UI):
        found = write_calls(tree)
        assert not found, f"{path.name}: {found}"
