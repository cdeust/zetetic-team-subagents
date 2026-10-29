# Diagnose the shared Review step

The shared Pipeline enables the official Claude Code Report for `Review` with
`display_report: true`. `show_full_output: false` keeps raw SDK JSON output off.
`Fix` retains its existing settings. This change uses the repository's existing
Claude authentication configuration; it requires no additional secret.

A successful bootstrap Pipeline does not prove that Claude reviewed the PR.
The Review guard skips the model steps when the PR changes
`.github/workflows/pipeline.yml`. Draft and Dependabot runs also do not establish
native Review acceptance. Inspect the `Review` step itself before claiming it ran.

Open **Actions → Pipeline → the exact run → Summary** to find the Claude Code
Report. The official action writes this Step Summary from its execution file,
including after a failure when that file exists. Record the PR head SHA and run
URL alongside the Review step's conclusion and relevant report excerpt. A later
Fix push creates a new head that needs its own checks.

The report formats conversation and tool content, then applies the action's
known-format secret redactor. Keep full output disabled and inspect excerpts
before sharing them. Redaction is not a guarantee that arbitrary sensitive text
is removed. The formatter displays the terminal `result` field but does not
display the SDK `errors` array. A missing report or empty terminal text therefore
does not identify the cause. Empty `modelUsage`, zero cost or a short execution
alone cannot distinguish authentication failure from quota or another startup
failure.

After the workflow update reaches `main`, validate it through a legitimate,
maintainer-authored PR in this repository that changes documentation or product
files and leaves the generated workflow unchanged. Use the normal ready PR
event and retain all guards. Acceptance requires the `Review` step to execute,
with report evidence that `/code-review:code-review` completed substantive review
of that PR; a skip or early SDK error does not qualify. Preserve the outcome
even when it fails. Do not bypass a guard or enable raw output to obtain a green
receipt.

Implementation references for the pinned action:

- [Report and full-output inputs](https://github.com/anthropics/claude-code-action/blob/a5a423f75c251dcbff8a74e99f83b2cb03c72bfa/action.yml#L152-L159)
- [Report writing after execution](https://github.com/anthropics/claude-code-action/blob/a5a423f75c251dcbff8a74e99f83b2cb03c72bfa/src/entrypoints/run.ts#L361-L367)
- [Terminal result formatting and redaction](https://github.com/anthropics/claude-code-action/blob/a5a423f75c251dcbff8a74e99f83b2cb03c72bfa/src/entrypoints/format-turns.ts#L411-L437)
