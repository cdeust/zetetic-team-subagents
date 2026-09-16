# zetetic-gates

> **Commits with unsourced constants get BLOCKED.**
> Four mechanical enforcement gates, zero agents, zero prompts. The smallest useful slice of the [zetetic-team-subagents](https://github.com/cdeust/zetetic-team-subagents) system: just the checkers and the hooks that run them.

## 30-second install

```bash
claude plugin marketplace add cdeust/zetetic-team-subagents
claude plugin install zetetic-gates
```

That's it. No agents to configure, no skills to learn. The hooks activate on the next Claude Code session.

## What it blocks

### Before: this commit goes through everywhere else

```python
# retry.py
# It always works
DELAY = 2.741592
```

```
$ git commit -m "tune retry backoff"
[main 3f2c1a9] tune retry backoff
```

### After: with zetetic-gates installed

```
$ git commit -m "tune retry backoff"

UNSOURCED    (error)   retry.py:1: # It always works
MAGIC_NUMBER (error)   retry.py:2: DELAY = 2.741592

Profile: strict  (staged mode)
Errors:   2  (blocking)
FAILED: 2 blocking violation(s).

BLOCKED: Zetetic violations in staged files.
```

The commit re-runs once each flagged line carries a `# source:` comment, a benchmark reference, or a measured-on note:

```python
# retry.py
DELAY = 2.741592  # source: measured p50 backoff sweep 2026-06-14, data at bench/backoff.csv
```

## The four gates

| Gate | File | What it enforces |
|---|---|---|
| **Zetetic checker** | `tools/zetetic-checker.sh` | `UNSOURCED` absolute claims ("always works", "never fails") block at any profile. `MAGIC_NUMBER` floats (3+ decimals without `source:`) and `TODO_NO_REF` warn at default, block under `ZETETIC_PROFILE=strict`. |
| **Craftsmanship checker** | `tools/craftsmanship-checker.sh` | Size limits from Martin, *Clean Code* (2008) §4: 500-line files, 50-line functions, 300-line classes, 4 parameters, 3 nesting levels. Every threshold and severity tunable via `.craftsmanship.conf` (see `.craftsmanship.conf.example`). |
| **Fail-before checker** | `tools/fail-before-checker.sh` | A test the diff adds must fail against the code as it was. The changed test files are copied over a throwaway checkout of the base and run there; a new pytest node that passes is reported `VACUOUS`, a warning under the standard profile and blocking under `ZETETIC_PROFILE=strict`. A run that could not reach a verdict is `INCONCLUSIVE`, never a pass. Rationale and limits: `docs/fail-before.md`. |
| **Secret shield** | `hooks/pre-tool-secret-shield.py` | Blocks tool calls that would surface credentials: `.env*`, private keys, `.aws/credentials`, shell history, keychains: including reads embedded in Bash pipelines. |

Outside Claude Code the same gate runs from a plain git hook: `printf 'exec plugins/zetetic-gates/tools/fail-before-checker.sh\n' > .git/hooks/pre-push && chmod +x .git/hooks/pre-push` (adjust the path to where the plugin is checked out).

Wiring: `hooks/pre-commit-zetetic.sh` runs gates 1–2 on the staged diff whenever Claude Code issues `git commit`; `hooks/pre-push-fail-before.sh` runs gate 3 whenever it issues `git push`; the secret shield intercepts Read/Bash/Grep/Edit/Write/NotebookEdit calls.

## Enforcing on human commits too

The Claude Code hook only fires when Claude runs `git commit`. To gate direct CLI commits as well, add a native git hook in your repo:

```bash
# .git/hooks/pre-commit  (chmod +x)
#!/usr/bin/env bash
GATES="$HOME/.claude/plugins/zetetic-gates"
bash "$GATES/tools/zetetic-checker.sh" --staged || exit 1
bash "$GATES/tools/craftsmanship-checker.sh" --staged; rc=$?
[ "$rc" -eq 1 ] && exit 1
exit 0
```

## Adopting in an existing codebase

Legacy trees carry backlogs of unsourced constants. Don't turn the gate on cold: use the permissive→standard→strict ramp described in [`docs/MIGRATION.md`](docs/MIGRATION.md).

## Configuration

| File (repo root) | Controls |
|---|---|
| `.zetetic.conf` | `ZETETIC_PROFILE=permissive\|standard\|strict`, path/extension skip lists. Rule semantics cannot be disabled: only scoped. |
| `.craftsmanship.conf` | §4 thresholds (`FILE_MAX`, `FUNC_MAX`, `CLASS_MAX`, `PARAM_MAX`, `NEST_MAX`, `TEST_FILE_MAX`) and per-rule severity (`block`/`advise`/`off`). |

## Relationship to the full system

These files are verbatim copies of the enforcement layer in [zetetic-team-subagents](https://github.com/cdeust/zetetic-team-subagents) (kept in sync by that repo's CI). Install the full plugin instead if you also want the 97 sourced reasoning patterns, the problem-shape skills, and the research/memory tooling: the two plugins share the same gate semantics, so you can start here and upgrade without re-learning anything.

## License

MIT; see the repository [LICENSE](https://github.com/cdeust/zetetic-team-subagents/blob/main/LICENSE).
