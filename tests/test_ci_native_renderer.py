"""Opt-in delivery of the native review configuration proven in Cortex PR811."""

import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import textwrap

import pytest
import yaml

from scripts.lib import render_ci as renderer

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "templates/ci/native"


def native_common_jobs():
    # Source: Cortex8e7375bf/Spec616eb04 pin v7.1.0; npm ci docs define frozen installs.
    text = renderer.artifacts()["pipeline.yml"].replace(
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0",
        "actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0",
    )
    text = text.replace(
        "        run: npm install -g @anthropic-ai/claude-code@2.1.306",
        "        run: |\n"
        '          npm ci --prefix "$GITHUB_WORKSPACE/.github/claude-cli"\n'
        '          echo "$GITHUB_WORKSPACE/.github/claude-cli/node_modules/.bin" >> "$GITHUB_PATH"',
    )
    return yaml.safe_load(text)


def test_native_keeps_common_jobs_and_separates_both_reviewers(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    direct = yaml.safe_load(files[tmp_path / ".github/workflows/pipeline.yml"])
    legacy = native_common_jobs()
    for name in ("contract", *renderer.CATEGORIES, "tag"):
        actual = direct["jobs"][name]
        if name == "contract":
            omitted = {"Test embedded workflow authorization", "Test native review recovery and resumption"}
            steps = [step for step in actual["steps"] if step.get("name") not in omitted]
            actual = {**actual, "steps": steps}
        assert actual == legacy["jobs"][name]
    review = str(direct["jobs"]["review"])
    assert "claude-code-action" not in review
    assert "Require completed Codex reviews" in review
    assert "CODEX_COMPLETION_ONLY" in review
    claude = yaml.safe_load(files[tmp_path / ".github/workflows/claude-review.yml"])
    assert set(claude[True]) == {"pull_request"}
    assert claude["jobs"]["review"]["steps"][-1]["with"]["track_progress"] is True
    assert (
        "security-code-reviewer"
        in files[tmp_path / ".claude/commands/review-pr.md"].decode()
    )
    runtime = files[tmp_path / "scripts/ci_codex_review_runtime.py"].decode()
    assert "resolvedBy" in runtime
    assert "_trusted_resolver" in runtime
    reader = files[tmp_path / "scripts/ci_codex_reviews.py"].decode()
    assert 'KINDS = ("code_review", "security_review")' in reader


def test_native_cli_preserves_configuration_and_unrelated_files(tmp_path):
    settings = tmp_path / "ci.json"
    settings.write_bytes(b'{"unit":"owner command"}\n')
    unrelated = tmp_path / "owner.txt"
    unrelated.write_text("keep")
    env = {key: val for key, val in os.environ.items() if key != "CLAUDE_PLUGIN_ROOT"}
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts/setup.sh"),
            "render-ci",
            str(tmp_path),
            "--native-review",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert settings.read_bytes() == b'{"unit":"owner command"}\n'
    assert unrelated.read_text() == "keep"
    assert (tmp_path / "scripts/ci_codex_reviews.py").is_file()
    assert (tmp_path / ".github/workflows/Codex.yml").is_file()


def original_security_runtime(delivered):
    original = delivered.split(b"\n\n# Body and edit attribution", 1)[0]
    original = original.replace(b"from http import HTTPStatus\n", b"")
    first = original.index(b"class APIError(")
    last = original.index(b"def _pairs(", first)
    original = original[:first] + original[last:]
    original = original.replace(
        b"    except subprocess.CalledProcessError as exc:\n"
        b"        raise APIError(_api_category(exc.stdout)) from exc\n"
        b"    except (OSError, subprocess.SubprocessError) as exc:\n"
        b"        raise APIError() from exc",
        b"    except (OSError, subprocess.SubprocessError) as exc:\n"
        b'        raise EvidenceError("api") from exc',
    )
    original = original.replace(
        b"if not expected.issubset(states):", b"if states.keys() != expected:"
    ).replace(b'"finding_ids": sorted(expected),', b'"finding_ids": sorted(states),')
    return re.sub(
        rb'"state": \(\s*"success"\s*if all\(states\[identity\] for identity in expected\)\s*else "unresolved"\s*\),',
        b'"state": "success" if all(states.values()) else "unresolved",',
        original,
    )


def original_reader_api(original):
    first = original.index("class APIError(")
    last = original.index("def _json(", first)
    original = original[:first] + original[last:]
    original = original.replace(
        "    except runtime.APIError as exc:\n        raise APIError(exc.category) from exc\n",
        "",
    ).replace(
        '        if isinstance(exc, runtime.APIError):\n            result["api_category"] = exc.category\n',
        "",
    )
    return original


def original_security_reader(delivered):
    original = delivered.decode()
    original = original_reader_api(original)
    imported = (
        "from ci_codex_review_comments import _authenticate_editor, "
        "_bot_author, _canonical  # noqa: E402\n"
    )
    if imported in original:
        original = original.replace(imported, "")
        shared = (NATIVE / "assets/scripts/ci_codex_review_comments.py").read_text()
        first = shared.index("def _canonical(")
        last = shared.index("\n\ndef _bot_author(", first)
        canonical = shared[first:last]
        original = original.replace(
            "\n\ndef _order(", "\n\n" + canonical + "\n\ndef _order("
        )
    for start, end in (("_bot_author", "_order"), ("summary_comments", "_eligible")):
        if "\n\ndef " + start + "(" not in original:
            continue
        first = original.index("\n\ndef " + start + "(")
        last = original.index("\n\ndef " + end + "(", first)
        original = original[:first] + original[last:]
    original = original.replace(
        "def _api(endpoint: str, *, paginate: bool = False, fields: Record | None = None) -> Any:",
        "def _api(endpoint: str, *, paginate: bool = False) -> Any:",
    ).replace(
        '        options = {"fields": fields} if fields is not None else {}\n'
        "        return runtime._api(endpoint, paginate=paginate, **options)",
        "        return runtime._api(endpoint, paginate=paginate)",
    )
    first = original.index("        latest_order = _order(latest)\n")
    last = original.index('        if latest["body"].count(SUMMARY)', first)
    original = original[:first] + original[last:]
    return original.replace(
        "    comments = summary_comments(args.repo, args.pr, args.sha, _api)\n"
        "    result = review_evidence(comments, args.sha, args.repo, args.pr)",
        '    pages = _api(f"repos/{args.repo}/issues/{args.pr}/comments", paginate=True)\n'
        "    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):\n"
        '        raise EvidenceError("protocol")\n'
        "    result = review_evidence(\n"
        "        [comment for page in pages for comment in page], args.sha, args.repo, args.pr\n"
        "    )",
    ).encode()


def original_review_job(delivered):
    original = delivered.decode()
    marker = "          COMMENTS_SOURCE = r'''\n"
    if marker in original:
        first = original.index(marker)
        last = original.index("          READER_SOURCE = r'''\n", first)
        original = original[:first] + original[last:]
        original = original.replace(
            '          _comments = ModuleType("ci_codex_review_comments")\n'
            '          exec(compile(COMMENTS_SOURCE, "ci_codex_review_comments.py", "exec"), _comments.__dict__)\n'
            "          sys.modules[_comments.__name__] = _comments\n",
            "",
        )
    for variable, filename in (
        ("RUNTIME_SOURCE", "ci_codex_review_runtime.py"),
        ("READER_SOURCE", "ci_codex_reviews.py"),
    ):
        marker = "          " + variable + " = r'''\n"
        first = original.index(marker) + len(marker)
        last = original.index("\n          '''", first)
        source = textwrap.dedent(original[first:last]).encode() + b"\n"
        restored = original_asset(source, "scripts/" + filename).decode().rstrip()
        original = (
            original[:first] + textwrap.indent(restored, "          ") + original[last:]
        )
    return original.encode()


def original_merge_job(delivered):
    # Inverse of source.json adaptation "merge-condition-diagnostics".
    text = delivered.decode()
    live = 'live="$(gh pr view "$PR" --json state,isDraft,headRefOid,title,labels)" ||\n            { echo "::error::PR state is unreadable."; exit 1; }\n'
    text = text.replace(live, live.split(" ||")[0] + "\n", 1)
    first = text.index("          # Name the failing condition:")
    last = text.index("          if [ \"$cause\" != eligible ]; then\n", first)
    last = text.index("          fi\n", last) + len("          fi\n")
    original = (
        '          if ! jq -e --arg sha "$HEAD_SHA" \'\n'
        "            .state == \"OPEN\" and .isDraft == false and .headRefOid == $sha\n"
        "            and (.title | ascii_downcase | contains(\"do not merge\") | not)\n"
        '            and ([.labels[].name | ascii_downcase] | all(. != "hold" and . != "do-not-merge"))\n'
        "          ' <<<\"$live\" >/dev/null; then\n"
        '            echo "::error::PR is closed, draft, held, or no longer at the tested head."\n'
        "            exit 1\n"
        "          fi\n"
    )
    return (text[:first] + original + text[last:]).encode()


def original_event_jobs(delivered):
    # Inverse of source.json adaptation "rerun-merge-job-identity".
    return delivered.replace(
        b"Keep the newest logical job, including jobs untouched by partial reruns.",
        b"Keep the newest result per name, including jobs untouched by partial reruns.",
    ).replace(
        b"            # pipeline.yml gives its single merge job two review-dependent names.\n"
        b"            # Source: cortex-vision PR5 discussion_r4408735600.\n"
        b'            name = "merge" if job["name"] == "merge pending review" else job["name"]\n',
        b"",
    ).replace(
        b"if name in names or", b'if job["name"] in names or',
    ).replace(
        b"names.add(name)", b'names.add(job["name"])',
    ).replace(
        b"effective.setdefault(name, job)", b'effective.setdefault(job["name"], job)',
    )


def original_claude_owner(delivered):
    first = delivered.index(b"      - name: Authorize owner fix target\n")
    last = delivered.index(b"      - uses: actions/checkout@", first)
    delivered = delivered[:first] + delivered[last:]
    first = delivered.index(b"          include_comments_by_actor:")
    last = delivered.index(b"          claude_args: |\n", first)
    delivered = delivered[:first] + delivered[last:]
    delivered = re.sub(
        rb'            --allowedTools "[^\n]+\n',
        b"            --permission-mode auto\n", delivered,
    )
    return re.sub(rb'            --append-system-prompt "[^\n]+\n', b"", delivered)


def original_recovery_event(delivered):
    # Inverse of source.json adaptation "automatic-security-review-recovery".
    return delivered.replace(
        b"import ci_codex_review_request as requests  # noqa: E402\n", b"",
    ).replace(
        b"def resume(repo: str, trigger: Record, *, dry_run=False) -> Record:",
        b"def resume(repo: str, trigger: Record) -> Record:",
    ).replace(
        b"    proof = _proof(repo, number, run, jobs)\n"
        b"    if requests.needs_request(proof, jobs):\n"
        b"        return requests.recover(dict(repository=repo, number=number, sha=sha), _jobs, dry_run=dry_run)\n"
        b"    plan = _plan(run, jobs, proof, sha)",
        b"    plan = _plan(run, jobs, _proof(repo, number, run, jobs), sha)",
    ).replace(
        b"    if dry_run:\n        return {**plan, \"dry_run\": True}\n", b"",
    )


def original_asset(delivered, relative):
    if relative == ".github/workflows/Codex.yml":
        original = delivered.replace(
            b"      issues: write\n      actions: write", b"      issues: read\n      actions: write",
        ).replace(
            b"    timeout-minutes: 5 # source: one five-minute schedule period; operational cap.\n",
            b"",
        ).split(b"\n  reconcile-identify:\n", 1)[0]
        first = original.index(b"  # Supported fallback:")
        last = original.index(b"\npermissions:\n", first)
        return original[:first] + original[last:]
    if relative == "scripts/ci_codex_review_runtime.py":
        return original_security_runtime(delivered)
    if relative == "scripts/ci_codex_reviews.py":
        return original_security_reader(delivered)
    if relative == "scripts/ci_codex_review_event.py":
        delivered = original_event_jobs(original_recovery_event(delivered)).replace(
            b'    return head_proof(repo, number, run["head_sha"])\n\n\n'
            b"def head_proof(repo: str, number: int, sha: str) -> Record:",
            b'    sha = run["head_sha"]',
        )
        return delivered.replace(
            b"from ci_codex_reviews import summary_comments  # noqa: E402\n", b""
        ).replace(
            b"rows = summary_comments(repo, number, sha, source._api)",
            b'rows = source.records(f"repos/{repo}/issues/{number}/comments")',
        )
    if relative.endswith("/claude.yml"):
        delivered = original_claude_owner(delivered)
    original = delivered.replace(b"            --strict-mcp-config\n", b"")
    original = original.replace(
        b'--model "claude-opus-5-5"', b'--model "claude-opus-4-7"'
    )
    if relative.endswith("/claude-review.yml"):
        original = original.replace(b"  pull_request:\n", b"  pull_request_target:\n")
        original = original.replace(b"      id-token: write\n", b"")
        original = original.replace(
            b"          claude_code_oauth_token:",
            b"          github_token: ${{ secrets.GITHUB_TOKEN }}\n          claude_code_oauth_token:",
        )
        original = original.replace(
            b"# Native App OIDC auth on same-repository PRs; main checkout retained.",
            b"# Trusted-base variant: upstream docs/security.md. Auth: upstream issue713.",
        )
    return original


def test_native_assets_match_the_pinned_source_receipt(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    receipt = json.loads((NATIVE / "source.json").read_text())
    assert receipt["commit"] == "8e7375bf2edfb33fb9c45809b9af6b428f0f4235"
    for relative, digest in receipt["assets"].items():
        assert hashlib.sha256(files[tmp_path / relative]).hexdigest() == digest
    assert len(receipt["assets"]) == 8
    for relative, source in receipt["adapted_assets"].items():
        delivered = files[tmp_path / relative]
        assert hashlib.sha256(delivered).hexdigest() == source["sha256"]
        original = original_asset(delivered, relative)
        assert hashlib.sha256(original).hexdigest() == source["source_sha256"]
    assert len(receipt["adapted_assets"]) == 6
    for relative, digest in receipt["authored_assets"].items():
        assert hashlib.sha256(files[tmp_path / relative]).hexdigest() == digest
    assert (
        set(receipt["assets"])
        | set(receipt["adapted_assets"])
        | set(receipt["authored_assets"])
    ) == set(renderer.NATIVE_ASSETS)
    jobs = renderer.split_jobs((NATIVE / "pipeline.yml").read_text())[1]
    for name, source in receipt["jobs"].items():
        assert hashlib.sha256(jobs[name].encode()).hexdigest() == source["sha256"]
    for name, source in receipt["adapted_jobs"].items():
        delivered = jobs[name].encode()
        assert hashlib.sha256(delivered).hexdigest() == source["sha256"]
        original = {"review": original_review_job, "merge": original_merge_job}[name]
        assert hashlib.sha256(original(delivered)).hexdigest() == source["source_sha256"]


def test_native_delivery_rolls_back_workflows_and_assets(tmp_path, monkeypatch):
    files = renderer.prepare_files(tmp_path, native_review=True)
    old = tmp_path / ".github/workflows/pipeline.yml"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"previous workflow")
    before = {path: path.read_bytes() if path.exists() else None for path in files}
    last = list(files)[-1]
    replace = renderer.os.replace

    def fail_last(temporary, destination):
        if destination == last:
            raise OSError("fixture native delivery failure")
        replace(temporary, destination)

    monkeypatch.setattr(renderer.os, "replace", fail_last)
    with pytest.raises(OSError, match="fixture native delivery failure"):
        renderer.deliver(files)
    assert {p: p.read_bytes() if p.exists() else None for p in files} == before
    assert not list(tmp_path.rglob(".render-ci-*"))


def test_native_invalid_asset_destination_preflights_the_entire_set(tmp_path):
    directory = tmp_path / ".claude/agents/security-code-reviewer.md"
    directory.mkdir(parents=True)
    with pytest.raises(ValueError, match="non-file"):
        renderer.prepare_files(tmp_path, native_review=True)
    assert not (tmp_path / ".github").exists()


def test_native_symlinked_parent_cannot_escape_the_destination(tmp_path):
    target = tmp_path / "consumer"
    outside = tmp_path / "outside"
    target.mkdir()
    outside.mkdir()
    (target / "scripts").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        renderer.prepare_files(target, native_review=True)
    assert list(outside.iterdir()) == []
    assert not (target / ".github").exists()


def test_native_rendered_workflows_pass_actionlint(tmp_path):
    import shutil
    import sysconfig

    renderer.deliver(renderer.prepare_files(tmp_path, native_review=True))
    scripts = Path(sysconfig.get_path("scripts")) / "actionlint"
    linter = str(scripts) if scripts.is_file() else shutil.which("actionlint")
    assert linter, "actionlint missing: install requirements-dev.lock"
    workflows = sorted((tmp_path / ".github/workflows").glob("*.yml"))
    assert len(workflows) == 6
    result = subprocess.run(
        [linter, *map(str, workflows)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_inline_codex_readers_match_the_delivered_scripts(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    direct = yaml.safe_load(files[tmp_path / ".github/workflows/pipeline.yml"])
    command = direct["jobs"]["review"]["steps"][0]["run"]
    for variable, filename in (
        ("RUNTIME_SOURCE", "ci_codex_review_runtime.py"),
        ("COMMENTS_SOURCE", "ci_codex_review_comments.py"),
        ("READER_SOURCE", "ci_codex_reviews.py"),
    ):
        embedded = command.split(variable + " = r'''\n", 1)[1].split("\n'''", 1)[0]
        assert embedded == files[tmp_path / "scripts" / filename].decode().rstrip()


def test_native_comment_boundary_loads_in_isolation_with_the_shared_error(tmp_path):
    import sys
    from types import ModuleType
    from unittest.mock import patch
    from test_ci_native_editor import comment, page, SHA, REPO, PR

    files = renderer.prepare_files(tmp_path, native_review=True)
    loaded = {}
    with patch.dict(sys.modules):
        for name in (
            "ci_codex_review_runtime",
            "ci_codex_review_comments",
            "ci_codex_reviews",
        ):
            module = ModuleType(name)
            module.__file__ = "/untrusted-candidate/" + name + ".py"
            source = files[tmp_path / "scripts" / (name + ".py")].decode()
            # Source: Cortex craftsmanship_rules.FILE_LINE_LIMIT, ADR-0726.
            assert len(source.splitlines()) <= 300
            exec(compile(source, module.__file__, "exec"), module.__dict__)
            sys.modules[name] = module
            loaded[name] = module
        runtime, comments, reader = loaded.values()
        assert comments.EvidenceError is runtime.EvidenceError
        assert reader.review_evidence([comment()], SHA, REPO, PR)["state"] == "success"
        rows = runtime._comment_pages([page([comment()])], SHA, PR)
        assert rows[0]["body"] == comment()["body"]
        with pytest.raises(runtime.EvidenceError):
            runtime._comment_pages([], SHA, PR)


@pytest.mark.parametrize("workflow", ["claude-review.yml", "claude.yml"])
def test_native_claude_limits_mcp_to_the_actions_configuration(tmp_path, workflow):
    import shlex

    files = renderer.prepare_files(tmp_path, native_review=True)
    document = yaml.safe_load(files[tmp_path / ".github/workflows" / workflow])
    steps = next(iter(document["jobs"].values()))["steps"]
    action = next(
        step
        for step in steps
        if "anthropics/claude-code-action@" in step.get("uses", "")
    )
    arguments = shlex.split(action["with"]["claude_args"])
    assert arguments.count("--strict-mcp-config") == 1
    assert arguments[arguments.index("--model") + 1] == "claude-opus-5-5"
    assert "--mcp-config" not in arguments  # The pinned action supplies its own.
    assert files[tmp_path / ".claude/commands/review-pr.md"]
    reviewers = [
        name for name in renderer.NATIVE_ASSETS if name.startswith(".claude/agents/")
    ]
    assert len(reviewers) == 5
    assert all(files[tmp_path / name] for name in reviewers)


def test_native_claude_uses_app_oidc_and_a_main_checkout(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    document = yaml.safe_load(files[tmp_path / ".github/workflows/claude-review.yml"])
    job = document["jobs"]["review"]
    assert job["permissions"].get("id-token") == "write"
    assert "github_token" not in job["steps"][-1]["with"]
    assert job["steps"][0]["with"]["ref"] == "main"
    assert "head.repo.full_name == github.repository" in job["if"]
    assert "!github.event.pull_request.draft" in job["if"]
