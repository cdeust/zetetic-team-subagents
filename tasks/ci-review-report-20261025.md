# Native Review failure reporting

Base: 23b5fd8378dab653a31052e9832a013ac913e2ba (remote main verified).
Branch: fix/ci-review-report. Publication awaits root review.

Codebase PR462 native Review job121141543313 returned is_error=true with
modelUsage={} and zero cost. Console output omitted the terminal result.
No retained artifact exposed it, so authentication/quota/model cause is unknown.

The pinned official [summary formatter](https://github.com/anthropics/claude-code-action/blob/a5a423f75c251dcbff8a74e99f83b2cb03c72bfa/src/entrypoints/format-turns.ts#L415)
includes terminal data.result and runs its known-format secret redactor. It does
not render data.errors; this adds diagnostic evidence without guaranteeing that
every SDK error field becomes visible. Its [entrypoint finally block](https://github.com/anthropics/claude-code-action/blob/a5a423f75c251dcbff8a74e99f83b2cb03c72bfa/src/entrypoints/run.ts#L361)
writes the report after failure when the execution file exists.

Enable display_report=true and explicitly keep show_full_output=false only on
Review. Fix defaults, guards, permissions, action pin and prompts are unchanged.
The generated post-merge engine changes only its source-hash comment; root
approved that provenance update. Its body and the complete caller are unchanged.

Focused regression before the change: 2 failed, 2 passed. After the final render:
95 passed across test_ci_pr_safety, test_ci_template, test_ci_renderer and
test_ci_event_separation, using python3 -m pytest -q -p no:cacheprovider with
PYTHONDONTWRITEBYTECODE=1. Independent reviewer repeated all four new cases.

Actionlint on all three rendered workflows, Ruff check/format on the changed
Python test and git diff --check passed. Structured comparison against HEAD
proved only the two Review inputs changed in canonical and direct workflow.
Staged strict zetetic and craftsmanship gates report zero errors/warnings.
Doc checks verified 32 count claims and 14 commands with zero problems.

Native acceptance remains pending: publish the reviewed workflow to trusted
main, then trigger Review on a non-workflow PR commit. Preserve the Step Summary,
terminal result and usage/tool receipts. Bootstrap/OIDC checks remain required.

Exact Git blobs:

- Canonical: c8ea135099f4b1db686872769874c93492576c4a
- Direct: 2f46c0b1aa88bac7cd70314856f6f3e38cf5a009
- Post-merge: f18182505ece0201527ec4f24f0d8d3b7741eb0c
- Caller unchanged: b23071bec38110c30cc7d7d0dc9d80d326f6b0ab
