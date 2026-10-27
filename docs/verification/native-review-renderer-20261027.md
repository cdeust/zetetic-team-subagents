# Native renderer local verification

Base: `84c44594af54fb2c42e780d484e595b6378dfda0`.
Copied source: Cortex `8e7375bf2edfb33fb9c45809b9af6b428f0f4235`.

Before implementation, the five native-render contracts failed: the renderer
rejected `native_review` and shell rendering produced no native assets. The
parent-symlink regression also failed before its preflight fix.

After implementation:

- The focused renderer/template suite passed 48 tests, including actionlint on
  all six generated workflows and native/default contract, test and tag parity
  with explicit native-only setup-python v7.1.0 and integrity-locked CLI installs.
- The shell renderer suite passed all seven checks, including byte parity with
  the existing checked-in default workflows and `ci.json` preservation.
- Source comparison verified 12 unchanged assets and three copied job blocks
  against the pinned Cortex commit. The two adapted Claude YAML assets retain original-source hashes: both add
  `--strict-mcp-config`; automatic review also uses native App authentication
  through the official PR event and OIDC permission, with no token override.
  `templates/ci/native/source.json` records original and adapted digests. All six
  command/reviewer files remain verbatim.
- Ruff, source discipline, craftsmanship, redaction, documented counts and
  documented command checks passed.

Before the final native-only setup-python, strict MCP, App auth and private CLI
install adjustments,
the full configured
Python coverage run passed 3255 tests in 606.87 seconds.
After combining subprocess measurements, `coverage xml` passed the existing
90 percent gate with 8517 of 9008 lines covered (94.55 percent). The final focused
subset ran after the reader-parity, actionlint and strict MCP regressions,
plus the setup-python, App auth and private CLI adjustments; it passed all 48
tests. The pin parity regression failed before that
adjustment, proving the previous native template would downgrade Spec's pin.
Both rendered strict MCP tests also failed before adding the flag. Coverage shards and disposable local coverage/cache outputs were removed.

No remote refs, PRs,
account settings or live generated workflows were changed by this worker.
Hosted Claude authentication and native review completion remain orchestrator
acceptance checks. Earlier target-event run40583904778 attributed a successful
Actions check to head6fec2753, but its explicit GitHub token selected the wrong
publication actor. The final native profile removes that override, grants OIDC
and uses the official PR trigger, while retaining its main checkout and strict
MCP discovery. Its PR-event and OIDC regressions failed before this correction.
Fresh hosted proof of `claude[bot]` publication belongs to the root orchestrator.

The CLI lock/install regressions failed before adding the private project and
replacing the two template install steps. The rendered direct and post-merge
workflows now each use `npm ci --prefix` in environment/install jobs and publish
the local bin directory through `GITHUB_PATH`. No global tool was changed.

A registered disposable installation of the exact private CLI lock completed
`npm ci` and returned `2.1.306 (Claude Code)` with exit 0 from `claude --version`
on macOS arm64, using a private HOME and config directory. The receipt is
`docs/verification/native-cli-integrity-20261028.json`. This establishes the local
host installation; Linux and Windows remain hosted CI checks.
