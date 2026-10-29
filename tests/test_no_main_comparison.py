"""Permanent guard: no CI definition of this repository compares a pull request with main.

Owner rule, 2026-10-29, verbatim: "je veux plus la revoir À VIE".

The workflow-definition proof against main (`authorize_workflow`), the update of a
branch from main, the merge-base against main's tip, the rendered-output comparison
between head and base, the strict "up to date" protection and the per-render hash in
the generated header made every open pull request stale each time main moved. Any
of them returning to `templates/`, `tools/`, `scripts/` or `.github/workflows/` fails
here. The same scan is delivered to consumers as `scripts/tests/test_no_main_comparison.py`.

Legitimate uses stay out of the forbidden list: `_confirm_main_merge` (the merged
commit is in main), the tag publication on a push to main (`merge-base --is-ancestor`)
and the diff perimeter `origin/$BASE_REF...$HEAD_SHA`.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "templates/ci/native/assets/scripts/tests/test_no_main_comparison.py"
DIRECTORIES = ("templates", "tools", "scripts", ".github/workflows")


def guard():
    spec = importlib.util.spec_from_file_location("consumer_no_main_comparison", ASSET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_ci_definition_compares_with_main():
    assert guard().violations(ROOT, DIRECTORIES) == []


def test_the_guard_detects_every_forbidden_trace(tmp_path):
    module = guard()
    workflows = tmp_path / ".github/workflows"
    workflows.mkdir(parents=True)
    traces = (*module.FORBIDDEN, "header + blob(source)")
    for number, trace in enumerate(traces):
        (workflows / f"w{number}.yml").write_text(f"# {trace}\n")
    for name, text in (
        ("strict-json.yml", 'required_status_checks: {"strict": true}\n'),
        ("strict-yaml.yml", "gh api repos/o/r/branches/main/protection\nstrict: true\n"),
    ):
        (workflows / name).write_text(text)
    # `strict: true` outside a protection configuration is not a comparison with main.
    (workflows / "unrelated-strict.yml").write_text("with:\n  strict: true\n")
    (workflows / "header.yml").write_text(module.HEADER + " 779f3b68def9d0d194cb453af5742f468fc26fa2\n")
    (workflows / "fixed.yml").write_text(module.HEADER + "\n")
    (workflows / "legitimate.yml").write_text(
        'git merge-base --is-ancestor "$sha" origin/main\n'
        "git diff origin/$BASE_REF...$HEAD_SHA\n"
        "_confirm_main_merge(pr_path, pr, sha, api)\n"
    )
    found = module.violations(tmp_path, (".github/workflows",))
    assert {line.split(":")[0].rsplit("/", 1)[-1] for line in found} == {
        *(f"w{number}.yml" for number in range(len(traces))),
        "header.yml",
        "strict-json.yml",
        "strict-yaml.yml",
    }
