# Migration: adopting in an existing (non-compliant) project

The plugin's defaults assume a greenfield project. For an existing codebase with historical magic constants, TODOs without trackers, and "always" / "never" comments, running `--staged` on every commit would be painful. Use the transition profile.

## Step 1: Scan once to measure the backlog

```bash
bash tools/zetetic-checker.sh --full
```

Count the findings:

- **UNSOURCED** (errors): absolute claims without citations; usually small, worth fixing
- **MAGIC_NUMBER** (warnings): tuning constants without `// source:`; usually large
- **TODO_NO_REF** (warnings): orphan TODOs; often fixable by linking to issues

## Step 2: Set `ZETETIC_PROFILE=permissive` for the transition

`<repo-root>/.zetetic.conf`:

```bash
ZETETIC_PROFILE=permissive
```

Permissive mode reports findings but never blocks. Commits go through. Keep the instrument visible while paying down the backlog.

## Step 3: Burn down existing violations

Use the included team agents incrementally:

```
For magic numbers:
  Ask the engineer or refactorer to add // source: annotations to constants
  they can verify from docs, benchmarks, or the standard library.

For orphan TODOs:
  # TODO: refactor later                    → bad
  # TODO(#264): extract shared validator    → good
```

You don't have to fix everything. Some constants are infrastructure (HTTP status codes, port numbers): the default regex skips them.

## Step 4: Graduate to `ZETETIC_PROFILE=standard`

When `--full` returns 0 UNSOURCED errors (or a manageable number you triage per PR):

```bash
ZETETIC_PROFILE=standard
```

UNSOURCED now blocks commits; MAGIC_NUMBER and TODO_NO_REF still warn.

## Step 5: Lock in `strict` on high-stakes paths

For algorithms from papers, financial logic, crypto, ML hyperparameters, and the components in [`rules/coding-standards.md`](../rules/coding-standards.md) §10 "High stakes":

1. Directory-scoped `.zetetic.conf` in those subdirectories with `ZETETIC_PROFILE=strict`, OR
2. A pre-push hook that runs `ZETETIC_PROFILE=strict` on those paths, OR
3. An ADR formalizing the stricter threshold.

## Customizing which team agents proactively fire

Eight agents auto-delegate by default (refactorer, code-reviewer, test-engineer, security-auditor, architect, Feynman, Curie, Dijkstra). To make them less aggressive on existing-project transition:

1. Edit the installed agent copy in `~/.claude/agents/` to remove the `Proactively` lead-in and scenario examples (survives plugin updates: `setup.sh` detects user-modified files and backs them up before overwriting).
2. Or set specific agents to `model: haiku` in `~/.claude/zetetic/agent-models.json` for cheaper evaluation during the transition.
