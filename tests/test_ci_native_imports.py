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


COMPATIBILITY_PROGRAM = '''
import importlib
import sys

sys.path.insert(0, sys.argv[1])
importlib.import_module(sys.argv[2])
import ci_codex_review_comments as comments
import ci_codex_review_runtime as runtime
import ci_codex_reviews as reader
from ci_codex_review_comments import _comment_pages as comment_pages, _comment_row
from ci_codex_review_runtime import _comment_pages

assert comments.EvidenceError is runtime.EvidenceError
assert reader._outputs is runtime._outputs
for module in (comments, runtime):
    wildcard = {}
    exec(f"from {module.__name__} import *", wildcard)
    assert set(wildcard) - {"__builtins__"} == {
        name for name in vars(module) if not name.startswith("_")
    }
    assert not {"_comment_pages", "_comment_row"} & wildcard.keys()
sha, pr = "c" * 40, 1
node = {
    "databaseId": 7, "body": "review body", "updatedAt": "2026-11-22T12:00:00Z",
    "author": {"login": "claude", "__typename": "Bot", "id": "bot"},
    "editor": None, "lastEditedAt": None,
}
page = {"data": {"repository": {"pullRequest": {
    "number": pr, "headRefOid": sha, "headRefName": "dependabot/test",
    "author": {"login": "dependabot", "__typename": "Bot"},
    "comments": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [node]},
}}}}
expected = {
    "id": 7, "body": "review body", "updated_at": "2026-11-22T12:00:00Z",
    "user": {"login": "claude[bot]", "type": "Bot", "node_id": "bot"},
    "editor": None, "lastEditedAt": None,
}
assert _comment_row(node=node) == expected
for normalize in (comment_pages, _comment_pages):
    rows = normalize(pages=[page], sha=sha, pr=pr)
    assert rows == [expected] and rows.dependabot

def request(endpoint, *, paginate, fields):
    assert endpoint == "graphql" and paginate
    assert fields == dict(query=comments.COMMENTS_QUERY, owner="owner", name="repo", number=pr)
    return [page]

for fetch in (comments.summary_comments, runtime.summary_comments):
    rows = fetch(repo="owner/repo", pr=pr, sha=sha, request=request)
    assert rows == [expected] and rows.dependabot

for read, args in (
    (_comment_row, {"node": None}),
    (comment_pages, {"pages": [], "sha": sha, "pr": pr}),
    (_comment_pages, {"pages": [], "sha": sha, "pr": pr}),
):
    try:
        read(**args)
    except comments.EvidenceError as error:
        assert type(error) is runtime.EvidenceError and str(error) == "protocol"
    else:
        raise AssertionError("malformed input did not raise the shared error")
'''


@pytest.mark.parametrize("first", ["ci_codex_review_comments", "ci_codex_review_runtime"])
def test_rendered_assets_support_direct_imports_in_either_order(tmp_path, first):
    renderer.deliver(renderer.prepare_files(tmp_path, native_review=True))
    subprocess.run(
        [sys.executable, "-IB", "-c", COMPATIBILITY_PROGRAM, str(tmp_path / "scripts"), first],
        check=True,
    )
