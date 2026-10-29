"""Permanent guard: no CI definition of this repository compares a pull request with main.

Owner rule, 2026-10-29, verbatim: "je veux plus la revoir À VIE".

The workflow-definition proof against main (`authorize_workflow`), the update of a
branch from main, the merge-base against main's tip, the rendered-output comparison
between head and base, the strict "up to date" protection and the per-render hash in
the generated header made every open pull request stale each time main moved. Any
of them returning to `templates/`, `tools/`, `scripts/`, `.github/workflows/`, `docs/`,
`skills/`, `commands/`, `agents/` or `rules/` fails here. The same scan is delivered to consumers as `scripts/tests/test_no_main_comparison.py`.

Also forbidden since the owner rule "Supprime le sha de main et la comparaison des
gates": the `compare/main...sha` request, the read of `refs/remotes/origin/main` to
trust a checkout, the "differs from trusted main" refusal, `_confirm_main_merge` and a
`MAIN_SHA` / `TRUSTED_SHA` variable. A tag goes on the commit the push event built.

Legitimate uses stay out of the forbidden list: a SHA cited as provenance, a
`merge-base --is-ancestor` safety check before a deletion, the `headRefOid` of the
reviewed pull request and the diff perimeter `origin/$BASE_REF...$HEAD_SHA`.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "templates/ci/native/assets/scripts/tests/test_no_main_comparison.py"
DIRECTORIES = (
    "templates", "tools", "scripts", ".github/workflows",
    "docs", "skills", "commands", "agents", "rules",
)


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
    traces = (*module.FORBIDDEN, "header + blob(source)", "MAIN_SHA=$(git rev-parse origin/main)", "trusted_sha")
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
        "gh pr view $PR --json headRefOid\n"
        "# Source: provenance, cdeust/Cortex commit 8e7375bf2edfb33fb9c45809b9af6b428f0f4235\n"
        "_confirm_pr_merge(pr_path, pr, sha, api)\n"
    )
    found = module.violations(tmp_path, (".github/workflows",))
    assert {line.split(":")[0].rsplit("/", 1)[-1] for line in found} == {
        *(f"w{number}.yml" for number in range(len(traces))),
        "header.yml",
        "strict-json.yml",
        "strict-yaml.yml",
    }


def test_the_guard_scans_the_documentation_directories_without_false_positives(tmp_path):
    module = guard()
    for directory in ("docs", "skills", "commands", "agents", "rules"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "violation.md").write_text("Compare with `compare/main...$SHA`.\n")
        (tmp_path / directory / "legitimate.md").write_text(
            "A branch is deleted only if `git merge-base --is-ancestor <tip> origin/main`.\n"
            "The review reads `headRefOid` of the reviewed pull request.\n"
            "Provenance: cdeust/Cortex@8e7375bf2edfb33fb9c45809b9af6b428f0f4235.\n"
        )
    found = module.violations(tmp_path, DIRECTORIES)
    assert sorted(line.split(":")[0] for line in found) == sorted(
        f"{directory}/violation.md" for directory in ("docs", "skills", "commands", "agents", "rules")
    )
