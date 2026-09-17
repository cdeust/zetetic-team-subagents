# Migration — adopting the gates in an existing (non-compliant) project

The shared host entry point defaults to `strict`; a repository `.zetetic.conf` can select a transition profile. For an existing codebase with historical magic constants, TODOs without trackers, and "always" / "never" comments, blocking on every commit would be painful. Use the transition profile.

## Step 1 — Scan once to measure the backlog

```bash
bash tools/zetetic-checker.sh --full
```

Paths are relative to the installed plugin root. Locate that root in your host plugin manager; cache paths differ between Claude Code and Codex.

Count the findings:

- **UNSOURCED** (errors) — absolute claims without citations; usually small, worth fixing
- **MAGIC_NUMBER** (warnings) — tuning constants without `// source:`; usually large
- **TODO_NO_REF** (warnings) — orphan TODOs; often fixable by linking to issues

## Step 2 — Set `ZETETIC_PROFILE=permissive` for the transition

`<repo-root>/.zetetic.conf`:

```bash
ZETETIC_PROFILE=permissive
```

Permissive mode makes the sourcing checker advisory. Secret, deletion, craftsmanship and prose checks keep their own enforcement settings. Keep the source findings visible while paying down the backlog.

## Step 3 — Burn down existing violations

```
For magic numbers:
  Add // source: annotations to constants you can verify from docs,
  benchmarks, or the standard library.

For orphan TODOs:
  # TODO: refactor later                    → bad
  # TODO(#264): extract shared validator    → good
```

You don't have to fix everything. Some constants are infrastructure (HTTP status codes, port numbers) — the default regex skips them.

## Step 4 — Graduate to `ZETETIC_PROFILE=standard`

When `--full` returns 0 UNSOURCED errors (or a manageable number you triage per PR):

```bash
ZETETIC_PROFILE=standard
```

UNSOURCED now blocks commits; MAGIC_NUMBER and TODO_NO_REF still warn.

## Step 5 — Lock in `strict` on high-stakes paths

For algorithms from papers, financial logic, crypto, and ML hyperparameters:

1. Directory-scoped `.zetetic.conf` in those subdirectories with `ZETETIC_PROFILE=strict`, OR
2. A pre-push hook that runs `ZETETIC_PROFILE=strict` on those paths, OR
3. An ADR formalizing the stricter threshold.

## Tuning the craftsmanship gate

Size limits (file/function/class/parameter/nesting) come from the coding-standards §4 numbers by default. Copy `.craftsmanship.conf.example` from the plugin root to `<repo-root>/.craftsmanship.conf` and adjust thresholds or per-rule severities (`block` / `advise` / `off`) for the transition — e.g. raise `TEST_FILE_MAX` for fixture-heavy test suites while keeping production files bound by `FILE_MAX=500`.
