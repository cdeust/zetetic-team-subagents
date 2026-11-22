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

assert comments.EvidenceError is runtime.EvidenceError
assert comments._comment_pages is runtime._comment_pages
assert comments.summary_comments is runtime.summary_comments
assert reader._outputs is runtime._outputs
'''
    subprocess.run(
        [sys.executable, "-IB", "-c", program, str(tmp_path / "scripts"), first],
        check=True,
    )
