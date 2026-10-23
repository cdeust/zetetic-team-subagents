# Explicit package release tags

Source: claude-mods main c4f5878, Pipeline39905709255 tag KeyError version.
Marketplace has no aggregate version; all historical catalog revisions have none.
Implementation convention: <plugin-name>/v<manifest-version>, including Codex,
using each package identity and version declared by its manifest.

- [x] Keep version_file and its default, generating v<version> for one package.
- [x] Add mutually exclusive nonempty release_packages entries with exact keys
  version_file and tag_prefix. Validate every manifest before any output/write.
- [x] Confine files to repository, reject missing versions and invalid Git refs,
  duplicate canonical manifest paths, duplicate prefixes and duplicate final tags.
- [x] Export a validated list of tags from the contract; preserve five test gates,
  SSH checkout at the contract-tested SHA, and explicit checkout verification.
- [x] Revalidate the complete tag list before writing; preserve existing tags;
  push missing refs atomically without force or branch updates.
- [x] Test old-contract failure, resolver success and refusal cases, actual local
  tag publication against disposable Git remotes; no hosted mutation in tests.
- [x] Render source repo and claude-mods only; preserve product versions.

Sources for ref grammar and atomic remote updates:
https://git-scm.com/docs/git-check-ref-format
https://git-scm.com/docs/git-push (atomic: all requested refs update or none).

Cortex is frozen during its full run. No other repository is edited or published.
Root independently reviews before any commit or push.

## Configuration

A single package keeps `version_file` (or its default) and tags `v<version>`.
A monorepo declares `release_packages` instead:

```json
{"release_packages": [
  {"version_file": "mods/engine/.claude-plugin/plugin.json", "tag_prefix": "engine/v"},
  {"version_file": "codex/.codex-plugin/plugin.json", "tag_prefix": "claude-mods/v"}
]}
```

JSON uses its top-level version; TOML uses project.version or package.version.
Paths may contain spaces but must resolve inside the repository. Duplicate
resolved files, prefixes or tag refs fail. External marketplace dependencies are
not repository release packages. No version is inferred from a repository name.

## Final validation

The new contract tests failed on the old implementation (8 failed, 20 passed).
The review regression cases also failed before correction (3 failed): collision
of an output delimiter, JSON import without tomllib, and TOML error reporting.
On the final candidate, all 274 affected CI tests passed in 7.29 seconds.
Official render-ci shell tests passed 7/7 and ci-template shell tests passed 4/4.
Actionlint 1.7.12 accepted the final template and both rendered workflows;
Ruff accepted the new source/tests, and git diff --check passed.

Real disposable bare remotes verified preservation of an older version tag,
atomic rejection without any remote refs, and overlapping two-clone publication.
The overlap case publishes one set in the second clone's pre-push hook, rejects
that clone's first atomic push, then succeeds with only its remaining tag.
There is no delay or attempt limit. A rejection without a strictly smaller set
fails visibly. Existing remote tags are never rewritten.

Release concurrency uses a SHA256 of the sorted versioned tag names. Different
version sets cannot replace each other's pending jobs; identical sets are
interchangeable. GitHub documents queue:max, but actionlint 1.7.12 and the inspected
official upstream parser do not support it, so no unsupported key is emitted.
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
The publisher reports success only after a successful atomic push or confirmed
existing refs. The workflow records failure explicitly when publication fails.

The repository has no global minimum Python declaration. Its separate async
helper documents Python 3.9+. render-ci itself is shell and does not import the
contract. The contract's JSON path remains usable without tomllib; a TOML
manifest requires Python 3.11+ and reports that requirement explicitly if the
stdlib parser is unavailable. No optional parser is silently installed.
https://docs.python.org/3/library/tomllib.html
Multiline outputs use UUID delimiters, regenerating while a complete value line
matches the delimiter. The regression forces a collision and verifies all lines.
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#multiline-strings

The workflow_run resolver is authored and independently tested by adapters_python:
113 tests passed; 114/115 source lines measured covered (entry point excluded).
The combined 274-test run above includes those tests and inline byte-parity tests.
A separate privileged resolve job validates the completed PR run and synchronously
merges its unchanged head through the protected API. Contract and all five test
categories then use the returned merge SHA. Ordinary pushes retain their test
path. No consumer depends on absent tools files: every helper is embedded exactly.

Reviewed pre-refactor template blob: 6a48a24e2c29d72b5ab629b38fd8b6e6e6f9934f.
Reviewed pre-refactor rendered blob: e7f4f7f45f6faa4ebb7e12ab734e65386e7d5f59.
All five claude-mods commands remain byte-identical; no product manifest changed.
No hosted run of this candidate has occurred. No commit or push was performed.
Worktrees remain registered for root review and publication.

## Commit-gate refactor

The normal commit hook rejected a 101-line resolve function and two depth-four
comprehensions. No gate was bypassed. Source helpers now separate source-run
validation (_source_run), PR resolution (_pull_request), exact push matching
(_push_covers_commit), single API observation (_has_push_pipeline), and protected
merge (_merge_open_pr). resolve composes those steps in 21 lines. The test jobs
fixture moved outside the response mapping with identical data.

All 113 resolver tests still pass (0.37s); craftsmanship reports zero errors and
warnings, and Ruff passes. After exact inline embedding and rendering both repos,
135 resolver/template tests pass (0.32s); actionlint accepts all three YAML files.
Final template blob: 36f80c58283c7a5ca48653e23a122ccafd52f6c4.
Both final rendered blobs: 24d72421a37579ff12a12dd3609dd32f1711714f.
The preceding 274-test evidence remains the behavior baseline before extraction.
