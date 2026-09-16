# The fail-before gate

`tools/fail-before-checker.sh` runs the tests a change adds against the code as
it was, and reports every one that still passes.

## Why it exists

`rules/coding-standards.md` §12 already states the principle: coverage proves
code ran, not that a test would fail if the code were wrong. Until this gate,
nothing enforced it outside a reviewer's diligence, and a reviewer reading a
test cannot see that it passes on the old code. Reading is not measuring.

The gate was written after a measured instance. On 2026-09-16, in the Cortex
repository, a test meant to pin "this script imports without the MCP SDK"
installed a meta-path finder using the pre-PEP 451 `find_module`/`load_module`
protocol. CPython ignores a finder that lacks `find_spec`, so the blocker
blocked nothing and the test passed against the very commit whose module-scope
import had broken CI minutes earlier. The author, the CI run and a first review
pass all missed it; the second review pass caught it by copying the committed
test into a worktree at the broken commit and watching it pass.

That procedure is mechanical, so it does not need a reviewer.

## What it does

1. Resolves a base: `git merge-base HEAD @{upstream}`, or `HEAD` when the
   branch has no upstream. A repository with no commit yet has no old tree;
   the gate says so and exits clean.
2. Lists changed test files: committed since the base, staged, unstaged, and
   untracked (a brand-new test file is the common case).
3. Checks the base out in a throwaway worktree under `.claude/worktrees/`,
   the only place this project puts a worktree.
4. Copies the current test files over that old tree: new tests, old code.
5. Runs them there, scoped to those files, under a wall-clock budget.

At least one must fail. A test that errors at import in the old tree counts:
the bar is that it can tell the two trees apart, not how it tells them apart.

## What it reports

| Finding | Meaning | Severity |
|---|---|---|
| `VACUOUS` | A test the diff adds passed against the old code | warning under `standard`; blocking under `ZETETIC_PROFILE=strict` |
| `INCONCLUSIVE` | No runner detected, or the run hit its budget | warning, never blocking, and it says which |

`INCONCLUSIVE` is deliberately not a pass. A gate that cannot reach its subject
reports that it did not, rather than a clean bill.

## Configuration

Both settings live in `.zetetic.conf`, committed and auditable, never in the
environment:

```
ZETETIC_PROFILE=strict
ZETETIC_FAIL_BEFORE_TIMEOUT=120
```

The default budget is 120 seconds for the whole base-tree run. A pre-push gate
that outruns the push it guards gets disabled by whoever it annoys, and a run
scoped to the changed test files sits far under that. The value must be a
whole number of seconds; anything else is a usage error (exit 2). The budget
is enforced through `timeout` or `gtimeout`; macOS ships neither, so without
`brew install coreutils` the run is unbounded there.

## Runners

Detected from the first changed test file: `pytest` (through `uv run --no-sync`
when the tree has a `uv.lock` and `uv` is on PATH), `go test`, `cargo test`,
and the `test` script of a `package.json`. Anything else reports
`INCONCLUSIVE` rather than guessing.

## What it does not prove

New pytest nodes are found by diffing module-level `def test_*` and
`async def test_*` names between the base and the current file. A new test
method inside a class, a renamed test, or a test moved from another file is
not seen as new, so the gate does not run it against the base. For the other
runners the whole changed file is the unit and the verdict is per file.

That the tests are good, only that they are not empty. A test can fail on the
old tree for a reason unrelated to what it claims to check; mutation testing,
not this gate, measures whether a suite pins behaviour. This is the cheap
check that runs on every push, and it catches the failure mode above.
