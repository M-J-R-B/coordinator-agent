"""Shared AST scanners for the source-level guards (test_ui_readonly, test_site_ui_writes)."""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Path / file-object methods that change the filesystem.
WRITING_METHODS = {"write_text", "write_bytes", "unlink", "mkdir", "rename", "rmdir",
                   "touch", "symlink_to", "hardlink_to", "chmod"}
# os.<name>(...) calls that change the filesystem.
WRITING_OS = {"replace", "remove", "rename", "unlink", "makedirs", "mkdir", "rmdir",
              "removedirs", "truncate"}
WRITER_NAMES = {"save_state", "write_json_atomic", "save_baseline", "save_report"}


def writes(func: ast.Attribute, call: ast.Call) -> bool:
    if isinstance(func.value, ast.Name) and func.value.id == "os":
        return func.attr in WRITING_OS
    if func.attr == "replace":
        # Path.replace(target) takes one argument; str.replace(old, new) takes two.
        return len(call.args) == 1
    return func.attr in WRITING_METHODS


def _opens_for_writing(call: ast.Call, position: int) -> bool:
    """position: index of the positional mode argument (open(p, mode): 1; p.open(mode): 0)."""
    modes = [a.value for a in call.args[position:position + 1] if isinstance(a, ast.Constant)]
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
        if isinstance(func, ast.Attribute) and func.attr == "open" and _opens_for_writing(node, 0):
            found.append(f"{node.lineno}: .open() for writing")
        if isinstance(func, ast.Name) and func.id == "open" and _opens_for_writing(node, 1):
            found.append(f"{node.lineno}: open() for writing")
    return found


# The broad name match is deliberate: a false positive fails loudly and costs a rename.
def writer_attribute_calls(tree: ast.AST) -> list[str]:
    """Writers reached through a module attribute, e.g. state.save_state(...)."""
    return [f"{n.lineno}: .{n.attr}" for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr in WRITER_NAMES]


def imported_modules(tree: ast.AST) -> list[str]:
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return mods


def sources(directory: Path):
    files = sorted(directory.glob("*.py"))
    assert files, f"{directory.name}/ has no Python files"
    return [(f, ast.parse(f.read_text(encoding="utf-8"))) for f in files]
