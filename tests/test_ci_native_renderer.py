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
            omitted = "Test embedded workflow authorization"
            steps = [step for step in actual["steps"] if step.get("name") != omitted]
            actual = {**actual, "steps": steps}
        assert actual == legacy["jobs"][name]
    review = str(direct["jobs"]["review"])
    assert "claude-code-action" not in review
    assert "Require completed Codex reviews" in review
    assert "CODEX_COMPLETION_ONLY" in review
    claude = yaml.safe_load(files[tmp_path / ".github/workflows/claude-review.yml"])
    assert set(claude[True]) == {"pull_request"}
    action = next(s for s in claude["jobs"]["review"]["steps"] if s.get("name") == "PR Review")
    assert action["with"]["track_progress"] is True
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


# Inverse of source.json adaptation "reviewer-agreement-lifts-review-holds".
AGREEMENT_OUTPUT = (
    b"        # Fixed identifiers only: the merge job names why a head cannot merge yet.\n"
    b"        f\"reason={result['reason']}\\ncauses={','.join(result.get('causes', [result['reason']]))}\\n\"\n"
)
AGREEMENT_READER = (
    (
        "from ci_codex_review_comments import security_receipt  # noqa: E402\n"
        "from ci_codex_review_agreement import conclude  # noqa: E402\n",
        "from ci_codex_review_comments import BLOCKED_REASONS, BLOCKING, security_receipt"
        "  # noqa: E402\n",
    ),
    (
        "            return {**result, **conclude(None, comments, expected_sha)}\n",
        "            return result\n",
    ),
    (
        "        result.update(conclude(states, comments, expected_sha))  # Codex, then Claude.\n",
        '        result["reviews_complete"] = all(s in ("success", "unresolved") for s in states)\n'
        '        result["state"] = (\n'
        '            "blocked"\n'
        "            if any(s in BLOCKING for s in states)\n"
        '            else ("pending" if "pending" in states else "success")\n'
        "        )\n"
        '        result["reason"] = {\n'
        '            "blocked": next((r for s, r in BLOCKED_REASONS if s in states), "review_unresolved"),\n'
        '            "pending": "review_pending",\n'
        '            "success": "reviews_complete",\n'
        '        }[result["state"]]\n',
    ),
)
AGREEMENT_EVENT_SOURCE = (
    b"    # Owner rule 2026-10-29: hold and autopilot:hold wait for both reviewers, and\n"
    b"    # the gate lifts them; only the owner's holds end resumption here.\n"
    b'    if "do not merge" in title.casefold() or any(\n'
    b'        label["name"].casefold() == "do-not-merge" for label in labels\n',
    b'    if "do not merge" in title.casefold() or any(\n'
    b'        label["name"].casefold() in ("hold", "do-not-merge") for label in labels\n',
)


def without_agreement(text, pairs):
    for delivered, original in pairs:
        assert text.count(delivered) == 1, delivered
        text = text.replace(delivered, original)
    return text


def original_security_runtime(delivered):
    delivered = without_agreement(delivered, [(AGREEMENT_OUTPUT, b"")])
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


def original_security_receipt(original):
    # Inverse of source.json adaptation "security-receipt-proof".
    signature = "def _reviews(latest, target"
    return (
        original.replace(
            "from ci_codex_review_comments import BLOCKED_REASONS, BLOCKING, "
            "security_receipt  # noqa: E402\n",
            "",
        )
        .replace(
            "if any(s in BLOCKING for s in states)",
            'if any(s in ("failed", "unresolved") for s in states)',
        )
        .replace(
            '"blocked": next((r for s, r in BLOCKED_REASONS if s in states), '
            '"review_unresolved"),',
            '"blocked": "review_failed" if "failed" in states else "review_unresolved",',
        )
        .replace(signature + ", comments):", signature + "):")
        .replace(
            "            ) or security_receipt(\n"
            "                comments, (repo, pr, expected_sha), reviews[kind], security\n"
            "            )\n",
            "            )\n",
        )
        .replace(
            "_reviews(latest, (expected_sha, repo, pr), comments)",
            "_reviews(latest, (expected_sha, repo, pr))",
        )
    )


def original_security_reader(delivered):
    original = without_agreement(delivered.decode(), AGREEMENT_READER)
    original = original_security_receipt(original_reader_api(original))
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
    original = without_agreement(
        delivered.decode(), [("      causes: ${{ steps.evidence.outputs.causes }}\n", "")]
    )
    first = original.index("          AGREEMENT_SOURCE = r'''\n")
    last = original.index("          READER_SOURCE = r'''\n", first)
    original = without_agreement(original[:first] + original[last:], [(
        '          _agreement = ModuleType("ci_codex_review_agreement")\n'
        '          exec(compile(AGREEMENT_SOURCE, "ci_codex_review_agreement.py", "exec"),'
        " _agreement.__dict__)\n"
        "          sys.modules[_agreement.__name__] = _agreement\n", "",
    )])
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


def _resolve_block(text):
    """A resolve-job excerpt at its YAML indentation (kept shallow here, §4)."""
    return textwrap.indent(text, " " * 10).encode()


AGREEMENT_RESOLVE = (
    (
        b"          from urllib.error import HTTPError, URLError\n"
        b"          from urllib.parse import quote\n",
        b"          from urllib.error import HTTPError, URLError\n",
    ),
    (
        _resolve_block(
            """\
# Owner rule 2026-10-29: hold and autopilot:hold mean "reviews incomplete";
# the source merge job read Codex and Claude agreeing on this head, so the
# gate lifts them. do-not-merge and a "do not merge" title stay the owner's.
# source: docs.github.com/en/rest/authentication/permissions-required-for-
# fine-grained-personal-access-tokens lists issues labels DELETE under Pull requests (write).
REVIEW_HOLDS = ("hold", "autopilot:hold")


def _review_holds(pr):
    require(
        pr.get("state") == "open" and pr.get("draft") is False,
        "PR is closed or draft",
    )
    require("do not merge" not in pr.get("title", "").lower(), "PR title holds merge")
    names = [label.get("name", "") for label in pr.get("labels", [])]
    require("do-not-merge" not in map(str.lower, names), "PR label holds merge")
    return [name for name in names if name.lower() in REVIEW_HOLDS]


def _merge_open_pr(pr, merge_path, head, api):
    held = _review_holds(pr)
    if held:
        pr_path = merge_path.removesuffix("/merge")
        labels = pr_path.replace("/pulls/", "/issues/") + "/labels/"
        for name in held:
            api.request("DELETE", labels + quote(name, safe=""))
        pr = api.request("GET", pr_path)
        require(pr.get("head", {}).get("sha") == head, "PR head advanced after testing")
        require(not _review_holds(pr), "PR label holds merge")
"""
        ),
        _resolve_block(
            """\
def _merge_open_pr(pr, merge_path, head, api):
    require(
        pr.get("state") == "open" and pr.get("draft") is False,
        "PR is closed or draft",
    )
    require("do not merge" not in pr.get("title", "").lower(), "PR title holds merge")
    require(
        not any(
            label.get("name", "").lower() in ("hold", "do-not-merge")
            for label in pr.get("labels", [])
        ),
        "PR label holds merge",
    )
"""
        ),
    ),
)
AGREEMENT_MERGE = (
    ("          REVIEW_CAUSES: ${{ needs.review.outputs.causes }}\n", ""),
    (
        """          # Owner rule 2026-10-29: hold and autopilot:hold mean "reviews incomplete".
          # They stay while a reviewer has no verdict for this head; once Codex and
          # Claude agree, the resolve job lifts them and merges.
          holds="$(jq -r '[.labels[].name | select(ascii_downcase == "hold" or ascii_downcase == "autopilot:hold")] | join(", ")' <<<"$live")"
          if [ "$REVIEW_STATE" = pending ]; then
            echo "## Tests passed; reviews pending for #$PR at $HEAD_SHA: ${REVIEW_CAUSES:-unnamed}" >> "$GITHUB_STEP_SUMMARY"
            if [ -n "$holds" ]; then echo "Review hold kept ($holds): ${REVIEW_CAUSES:-unnamed}." >> "$GITHUB_STEP_SUMMARY"; fi
          else
            echo "## Merge: gate passed for #$PR at $HEAD_SHA" >> "$GITHUB_STEP_SUMMARY"
            if [ -n "$holds" ]; then echo "Codex and Claude agree on this head; resolve lifts $holds and merges." >> "$GITHUB_STEP_SUMMARY"; fi
          fi
""",
        """          if [ "$REVIEW_STATE" = pending ]; then
            echo "## Tests passed; native Codex reviews pending for #$PR at $HEAD_SHA" >> "$GITHUB_STEP_SUMMARY"
          else
            echo "## Merge: gate passed for #$PR at $HEAD_SHA" >> "$GITHUB_STEP_SUMMARY"
          fi
""",
    ),
)


def original_resolve_job(delivered):
    # Inverse of source.json adaptation "draft-pipeline-decline".
    pairs = json.loads((ROOT / "tests/fixtures/native_resolve_draft_decline.json").read_text())
    for new, old in pairs["pairs"]:
        assert delivered.count(new.encode()) == 1
        delivered = delivered.replace(new.encode(), old.encode())
    delivered = without_agreement(delivered, AGREEMENT_RESOLVE)
    # Inverse of source.json adaptation "post-merge-merge-alias".
    folded = (
        b"                  # The single merge job has two review-dependent display names;\n"
        b"                  # fold them so a stale attempt cannot outvote the newest one.\n"
        b"                  # Source: session-optimizer PR87 discussion_r4409903427.\n"
        b'                  key = "merge" if name == "merge pending review" else name\n'
        b"                  previous = indexed.get(key)\n"
    )
    assert delivered.count(folded) == 1
    original = delivered.replace(folded, b"                  previous = indexed.get(name)\n")
    assert original.count(b"indexed[key] = job") == 1
    return original.replace(b"indexed[key] = job", b"indexed[name] = job")


def original_merge_job(delivered):
    text = without_agreement(delivered.decode(), AGREEMENT_MERGE)
    # Inverse of source.json adaptation "merge-condition-diagnostics".
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
    # Inverse of source.json adaptation "owner-mention-concurrency".
    delivered = cut_block(
        delivered,
        b"    # Run one owner request per thread at a time (Cortex #822). Without\n",
        b"    runs-on: ubuntu-latest\n",
    )
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


def cut_block(delivered, first, last):
    """Remove the one block from `first` up to, not including, `last`."""
    assert delivered.count(first) == 1, first
    start = delivered.index(first)
    end = delivered.index(last, start)
    return delivered[:start] + delivered[end:]


def without_review_procedure_tools(delivered):
    # Inverse of source.json adaptation "native-review-procedure-tools".
    delivered = cut_block(
        delivered,
        b"      # The pinned action installs its github_ci tools (Pipeline logs of this\n",
        b"    steps:\n",
    )
    delivered = cut_block(
        delivered,
        b"      # The reviewer runs the tests that cover the change; a repository that\n",
        b"      - name: PR Review\n",
    )
    delivered = cut_block(delivered, b"        id: claude_review\n", b"        uses: ")
    delivered = cut_block(delivered, b"          show_full_output: false\n", b"          allowed_bots:")
    delivered = cut_block(
        delivered,
        b"            Review head ${{ github.event.pull_request.head.sha }}",
        b"            Complete all five reviews",
    )
    namer = b"      # show_full_output stays false (the output can quote the code under\n"
    assert delivered.count(namer) == 1
    delivered = delivered[: delivered.index(namer)]  # The namer step ends the file.
    tools = re.findall(rb'            --allowedTools "[^\n]+\n', delivered)
    assert len(tools) == 1
    return delivered.replace(
        tools[0],
        b'            --allowedTools "mcp__github_inline_comment__create_inline_comment,'
        b'Bash(gh pr comment:*),Bash(gh pr diff:*),Bash(gh pr view:*)"\n',
    )


def without_fetch_authorization(delivered):
    first = delivered.index(b"      # source: pinned action src/modes/tag/index.ts#L79")
    last = delivered.index(b"      - name: Install subprocess isolation\n", first)
    return delivered[:first] + delivered[last:]


def original_event_source(delivered):
    delivered = without_agreement(delivered, [AGREEMENT_EVENT_SOURCE])
    # Inverse of source.json adaptation "receipt-event-resumption".
    return delivered.replace(
        b"from ci_codex_review_comments import RECEIPT\n", b""
    ).replace(
        b'item["body"].startswith((SUMMARY, RECEIPT))', b'item["body"].startswith(SUMMARY)'
    )


def original_asset(delivered, relative):
    if relative.endswith("/claude-review.yml"):
        delivered = without_review_procedure_tools(delivered)
    if relative.endswith(("/claude-review.yml", "/claude.yml")):
        delivered = without_fetch_authorization(delivered)
    if relative == ".github/workflows/Codex.yml":
        original = delivered.replace(
            b"    timeout-minutes: 5 # source: one five-minute schedule period; operational cap.\n",
            b"",
        ).split(b"\n  reconcile-identify:\n", 1)[0]
        first = original.index(b"  # Supported fallback:")
        last = original.index(b"\npermissions:\n", first)
        return original[:first] + original[last:]
    if relative == "scripts/ci_codex_review_event_source.py":
        return original_event_source(delivered)
    if relative == "scripts/ci_codex_review_runtime.py":
        return original_security_runtime(delivered)
    if relative == "scripts/ci_codex_reviews.py":
        return original_security_reader(delivered)
    if relative == "scripts/ci_codex_review_event.py":
        delivered = original_event_jobs(delivered).replace(
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
        original = original_claude_review(original)
    return original


def original_claude_review(original):
    # Inverse of source.json adaptation "claude-review-verdict-marker".
    marker = (
        b"            End the completion summary with this exact last line, unchanged except"
        b" `true` becomes `false` when any finding blocks the merge:\n"
        b'            <!-- claude-review-verdict:v1 {"head":"${{ github.event.pull_request.head.sha }}","merge":true} -->\n'
    )
    assert original.count(marker) == 1
    original = original.replace(marker, b"")
    # Inverse of source.json adaptation "native-app-oidc".
    original = original.replace(b"  pull_request:\n", b"  pull_request_target:\n")
    original = original.replace(b"      id-token: write\n", b"")
    original = original.replace(
        b"          claude_code_oauth_token:",
        b"          github_token: ${{ secrets.GITHUB_TOKEN }}\n          claude_code_oauth_token:",
    )
    return original.replace(
        b"# Native App OIDC auth on same-repository PRs; main checkout retained.",
        b"# Trusted-base variant: upstream docs/security.md. Auth: upstream issue713.",
    )


def test_native_assets_match_the_pinned_source_receipt(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    receipt = json.loads((NATIVE / "source.json").read_text())
    assert receipt["commit"] == "8e7375bf2edfb33fb9c45809b9af6b428f0f4235"
    for relative, digest in receipt["assets"].items():
        assert hashlib.sha256(files[tmp_path / relative]).hexdigest() == digest
    assert len(receipt["assets"]) == 7
    for relative, source in receipt["adapted_assets"].items():
        delivered = files[tmp_path / relative]
        assert hashlib.sha256(delivered).hexdigest() == source["sha256"]
        original = original_asset(delivered, relative)
        assert hashlib.sha256(original).hexdigest() == source["source_sha256"]
    assert len(receipt["adapted_assets"]) == 7
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
        original = {
            "review": original_review_job,
            "merge": original_merge_job,
            "resolve": original_resolve_job,
        }[name]
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
        ("AGREEMENT_SOURCE", "ci_codex_review_agreement.py"),
        ("READER_SOURCE", "ci_codex_reviews.py"),
    ):
        embedded = command.split(variable + " = r'''\n", 1)[1].split("\n'''", 1)[0]
        assert embedded == files[tmp_path / "scripts" / filename].decode().rstrip()


def test_native_comment_boundary_loads_in_isolation_with_the_shared_error(tmp_path):
    import sys
    from types import ModuleType
    from unittest.mock import patch
    from test_ci_native_editor import comment, page, SHA, REPO, PR
    from test_ci_native_hold_lift import claude_row

    files = renderer.prepare_files(tmp_path, native_review=True)
    loaded = {}
    with patch.dict(sys.modules):
        for name in (
            "ci_codex_review_runtime",
            "ci_codex_review_comments",
            "ci_codex_review_agreement",
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
        runtime, comments, _, reader = loaded.values()
        assert comments.EvidenceError is runtime.EvidenceError
        rows = [comment(), claude_row(SHA)]  # Codex and Claude agree on the head.
        assert reader.review_evidence(rows, SHA, REPO, PR)["state"] == "success"
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
    action = next(s for s in job["steps"] if s.get("name") == "PR Review")
    assert "github_token" not in action["with"]
    assert job["steps"][0]["with"]["ref"] == "main"
    assert "head.repo.full_name == github.repository" in job["if"]
    assert "!github.event.pull_request.draft" in job["if"]
