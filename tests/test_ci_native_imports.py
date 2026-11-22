"""Guard the native review package import graph behind the generated workflows."""

import ast
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.lib import render_ci as renderer

SCRIPTS = Path(__file__).resolve().parents[1] / "templates/ci/native/assets/scripts"


def test_native_review_module_imports_are_acyclic_and_use_one_form():
    modules = {path.stem: ast.parse(path.read_text()) for path in SCRIPTS.glob("*.py")}
    graph = {}
    mixed = set()
    for name, tree in modules.items():
        direct = set()
        from_imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                direct.update(alias.name for alias in node.names if alias.name in modules)
            elif isinstance(node, ast.ImportFrom) and node.module in modules:
                from_imports.add(node.module)
        mixed.update((name, dependency) for dependency in direct & from_imports)
        graph[name] = direct | from_imports

    def visit(node, ancestors):
        assert node not in ancestors, " -> ".join((*ancestors, node))
        for dependency in sorted(graph[node]):
            visit(dependency, (*ancestors, node))

    for name in sorted(graph):
        visit(name, ())
    assert not mixed


@pytest.mark.parametrize("first", ["ci_codex_review_comments", "ci_codex_review_runtime"])
def test_rendered_assets_support_direct_imports_in_either_order(tmp_path, first):
    renderer.deliver(renderer.prepare_files(tmp_path, native_review=True))
    program = '''
import importlib
import sys

sys.path.insert(0, sys.argv[1])
importlib.import_module(sys.argv[2])
import ci_codex_review_comments as comments
import ci_codex_review_runtime as runtime
import ci_codex_reviews as reader
from ci_codex_review_comments import _comment_row
from ci_codex_review_runtime import _comment_pages

assert comments.EvidenceError is runtime.EvidenceError
assert comments._comment_pages is runtime._comment_pages
assert comments.summary_comments is runtime.summary_comments
assert reader._outputs is runtime._outputs
for module in (comments, runtime):
    wildcard = {}
    exec(f"from {module.__name__} import *", wildcard)
    assert set(wildcard) - {"__builtins__"} == {
        name for name in vars(module) if not name.startswith("_")
    }
    assert not {"_comment_pages", "_comment_row"} & wildcard.keys()
for read, args in [(_comment_row, (None,)), (_comment_pages, ([], "c" * 40, 1))]:
    try:
        read(*args)
    except comments.EvidenceError as error:
        assert str(error) == "protocol"
    else:
        raise AssertionError("malformed input did not raise the shared error")
'''
    subprocess.run(
        [sys.executable, "-IB", "-c", program, str(tmp_path / "scripts"), first],
        check=True,
    )


@pytest.mark.parametrize(
    ("module", "exports"),
    [
        ("ci_codex_review_comments",
         {"COMMENTS_QUERY", "DEPENDABOT", "Comments", "EvidenceError",
          "_comment_pages", "_comment_row", "summary_comments"}),
        ("ci_codex_review_runtime", {"EvidenceError", "_comment_pages", "summary_comments"}),
    ],
)
def test_historical_aliases_are_explicit_assignments_from_the_pages_module(module, exports):
    tree = ast.parse((SCRIPTS / f"{module}.py").read_text())
    bindings = {
        node.targets[0].id: node.value.attr
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "_pages"
    }
    assert bindings == {name: name for name in exports}
