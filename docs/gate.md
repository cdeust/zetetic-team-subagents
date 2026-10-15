# The commit and push gate

No commit or push of an unverified tree. Verification is an async task keyed by the kind of act, the tree hash
and the rules; the hook that guards `git commit` reads the task's state and never waits
(`docs/async-tasks.md`).

## Flow

```
git add ...            PostToolUse hooks/gate-start.py   starts the commit task for the staged tree if absent, returns at once
git commit ...         PreToolUse  hooks/gate-proof.py   reads gate-commit-<staged tree>-<rules>:
                                                           done and green  -> allow
                                                           failed          -> deny, names the output file
                                                           running/started -> deny, "retry when it finishes"
git push / gh pr create  PreToolUse same hook            reads gate-push-<tip tree>-<rules> for the tip of EVERY ref published
Stop                   Stop        hooks/stop-gate-ledger.py  an open failure blocks the stop while work is at risk
```

The task id is `gate-<kind>-<tree>-<rules>` (the cache key below); the state directory is
`<git-common-dir>/zetetic-tasks/`, so every worktree of a repository shares it and the repository is the
namespace. Asking never reruns a green key and never starts a second task for a key that has one.

Status of a verification: `tools/task.sh status gate-<kind>-<tree>-<rules> --repo <repo>` (the hook prints
the exact command). Retry after an infrastructure failure: `python3 hooks/lib/gate_task.py requeue --repo <repo>
--kind commit|push`. A worker that died without a result is requeued once, automatically, by the next attempt
(attempt N+1, counted in the record). Waiver: `python3 hooks/lib/gate_task.py waive --tree <tree> --reason
"..."` lifts the Stop block for that tree and is appended to `gate-waivers.jsonl`; it never lets a commit
through, only a green record does.

## Trusted repositories

A gate runs commands that the repository declares (`.zetetic/gate.json`, `scripts/gate.sh`, a stack's test
command), started by `git add` with no prompt. In a repository whose owner you do not trust that is code
execution. So the worker runs only for repositories you listed, one absolute path per line, in

```
~/.claude/zetetic/gate-trusted-repos
```

Blank lines are ignored, and so is any line that is not an absolute path (a `# comment`, a relative path).
Paths are compared by real path. Listing a checkout trusts the linked worktrees of that repository (the parent
of the git common dir); listing a worktree trusts that worktree only. A repository that declares a gate and is
not listed is DENIED at `git commit` and `git push`/`gh pr create`, with the exact line to add; `git add` starts
nothing in it, and the worker refuses to run if it is started by hand (`tools/task.sh`). No silent pass, nothing
is run. The hooks never write this file. `ZETETIC_GATE_TRUSTED_REPOS` replaces the path (tests); it is read from
your session's environment, never from a repository.

Example: the repositories of the fleet (adjust the prefix to where you keep them):

```
/Users/you/Developments/anthropic-partnership/zetetic-team-subagents
/Users/you/Developments/anthropic-partnership/Cortex
/Users/you/Developments/anthropic-partnership/ai-architect-mcp-codebase
/Users/you/Developments/anthropic-partnership/ai-architect-mcp-spec
/Users/you/Developments/anthropic-partnership/claude-mods
/Users/you/Developments/anthropic-partnership/cortex-viz
```

## The rules come from a trusted tree

A change must not choose the rules it is judged by: a staged `.zetetic/gate.json` with `"checks": [{"argv":
["true"], ...}]` or `"off": true` would approve itself. So the rules are read from git objects, never from the
working copy:

- The **trusted tree** is HEAD's tree. With no HEAD yet (a repository's first commit) there is nothing older to
  trust and the tree being judged is its own trusted tree.
- The **effective rules** are the rules of the trusted tree, plus the rules of the judged tree when they differ.
  Never fewer: a change can add checks, not remove or replace HEAD's. A change to the config is judged by the
  union. Each rule set is planned and run on its own, with its own `env` and `link`, so a staged config's
  environment never reaches HEAD's checks.
- Whether a repository is gated at all is decided the same way (HEAD's `"off": true` switches it off; a staged
  one does not). The working copy is read only as a last resort, when git itself cannot answer.
- A legacy `scripts/gate.sh` is run from the trusted tree's copy of `scripts/`, exported from the git object
  database into a private directory; an edited script in the working copy does not judge itself.

## Kind, and the cache key

A verification is keyed by **kind + tree + digest of the effective rules**: `commit-<tree>-<12 hex>` or
`push-<tree>-<12 hex>`.

- **Kind.** A push needs a green record of kind `push`; a commit's record never stands in for it. A
  repository whose gate has push-only checks (`scripts/gate.sh push` adding `test bench oracle`) keeps them.
- **Rules.** A verdict is never reused under other rules.
- **Affected-only selection is valid only when the base tree has a green record of the same kind** under the
  same rules (the base is HEAD's tree for a commit, the tip's parent for a push or an amend). Otherwise the full
  configured gate runs: every check over every file, and the whole suite. A push of a branch whose parent was
  never pushed is therefore verified in full, and so is the first commit after a change to the rules (the
  base's record was made under the previous rules).

## What a push publishes

A push is judged by the tip tree of every ref it publishes, not by HEAD's tree:

| Command | Refs judged |
|---|---|
| `git push origin feat`, `feat:main`, `+feat:x`, `HEAD`, `HEAD~2`, a sha | the commit the local side names |
| `git push origin 'refs/heads/*:refs/heads/*'` | every ref the glob matches |
| `git push --all` / `--branches` | every local branch |
| `git push --mirror` | every local branch and remote-tracking ref |
| `git push` / `git push origin` | `remote.<remote>.push` when set; with `push.default=matching`, every local branch (a superset of what matching pushes); else the current branch |
| `gh pr create --head [owner:]feat` | branch `feat`; without `--head`, the current branch |
| `:feat`, `--delete`, `--tags`, `refs/tags/*`, `--dry-run` | no commit: not gated |

A ref that does not resolve to a commit (a name that does not exist, a detached HEAD with no ref named, a branch
that exists only on the remote) is **denied with the reason**: the hook never judges a tree it was not asked
about. Each tip with no green push record starts its verification; the denial lists the tips by name.

## What the hooks do, and what bounds them

The hooks make a handful of git calls and read a few small objects. `git rev-parse --show-toplevel
--git-common-dir` reads refs and config, `git write-tree` reads the index file and writes tree objects, `git
ls-tree` / `git cat-file blob` read the rules out of one tree, `git rev-parse --verify <ref>^{commit}` reads one
ref and one commit. No call touches the network (`GIT_NO_LAZY_FETCH=1` forbids a partial clone from fetching) or
stats the working tree, and none carries a timer: a test (`tests/test_gate_async.py`) fails if any hook module
bounds a call by time. The changed-file list, the checkout of the tree and the checks run in the task, never in
a hook. The Stop hook is the one exception to "never stats the working tree": the baseline's question "are
tracked changes still uncommitted" needs `git diff --quiet HEAD`, which stats tracked files only.

## A hook that is killed or cannot finish

By default a Claude Code hook that fails does not stop the call. The hook schema of Claude Code 2.1.301
(`onFailure`, read from the shipped binary) says: *"What a failure of this hook
does: it could not start (a missing script or plugin directory), timed out, exited with a code other than 0 or
2, or printed JSON that is invalid or fails validation. 'continue' (default): the failure is reported and the
action goes ahead. 'block': the failure counts as exit code 2, so the action the event guards (a tool call, a
permission request, a prompt) is blocked. Ignored for async hooks and on Stop, SubagentStop, TaskCompleted and
TeammateIdle."* So a gate-proof that is killed, crashes before `main`, or exceeds its timeout would let the
commit through. `hooks/hooks.json` and `.claude-plugin/plugin.json` register `gate-proof.py` with
`"onFailure": "block"`; that, not a timeout, is what makes it fail closed. (The existing `timeout` is not
raised and is not the guarantee.) `hooks/run-python.sh` fails closed for `gate-proof.py` only when no Python 3
is found: it refuses a call whose payload mentions `git` or `gh`, and lets any other call through so a host
without Python can still install one. Every other hook keeps failing open there.

## The verdict is a function of the tree

The worker (`hooks/lib/gate_run.py`) checks the tree out into a private directory through a private index and
runs the checks there, then removes it. Editing the working tree while a verification runs cannot change its
verdict. The previous gate achieved this by refusing to run when tracked files were modified but unstaged; an
async gate cannot, because the author keeps working.

Checks that need an untracked or ignored file get it through the config: `link` symlinks a directory such as
`node_modules` from the checkout, `env` points a build at a shared location (the stack default for Cargo sets
`CARGO_TARGET_DIR={common}/zetetic-gate-target`, so builds are incremental across verifications). The venv
python is found in the checkout, then in the main checkout (`{python}` below). A killed worker (SIGKILL cannot
be handled) leaves its private checkout under the system temp directory; the next attempt for the same tree
replaces it.

## The Stop hook: the todo

Owner rule: errors are added to your todo and you stop when the todo is empty. Each verification that ends
appends one line `{verb, tree, key, rc}` to `gate-results.jsonl` in the task state directory. **Line order is
the order of events; no clock decides.** An open failure is a line with `rc != 0` with no later green line of
the same verb and no waiver for its tree. The stop is blocked while there is an open failure **and** work is
at risk: tracked changes remain uncommitted (staged or not, so a failed tree that was unstaged with its edits
left in the working copy still blocks), or HEAD is ahead of its upstream. A running verification never blocks.
A worker killed before it could append leaves no line: that is an infrastructure failure, which the commit hook
reports, not a gate failure.

## `.zetetic/gate.json`

A repository declares its gate with this file (version 1). Without it the declaration order is:

1. `"off": true` in `.zetetic/gate.json`, or in the older `.zetetic-gate.json`: not gated.
2. `.zetetic/gate.json`: its checks.
3. An executable `scripts/gate.sh` (legacy): the task runs `sh <trusted copy of scripts/gate.sh> commit|push`
   in the real checkout, so the repository's own script keeps judging, per kind. It refuses when tracked files
   are modified but unstaged, which makes a verification started by `git add` fail if the author edits again
   before it ends. The script judges the index as it is when it runs, so the task is green only if the script
   also left its proof file for exactly the tree being verified (`<git-common-dir>/zetetic-gates/<kind>-<tree>.json`,
   green, naming that tree); a script that proved another tree because the index moved fails the task.
   Migrate to `.zetetic/gate.json`.
4. A recognised stack: `Cargo.toml` (fmt, clippy, test), `package.json` with a `lint` or a real `test` script,
   a pytest project (a `pyproject.toml`, `pytest.ini`, `setup.cfg` or `tox.ini` plus a `tests/` directory or a
   `test_*.py` at the root), `go.mod` (vet, test). The whole suite, whenever the tree differs from its base.
5. Otherwise the repository is not gated.

`scripts/gate.sh` is no longer generated by a hook (a read-only hook should not write into a repository).

```json
{
  "version": 1,
  "full_on": ["pyproject.toml"],
  "checks": [
    {"name": "lint", "paths": ["**/*.py"], "argv": ["{python}", "-m", "ruff", "check", "{files}"]}
  ],
  "tests": {
    "argv": ["{python}", "-m", "pytest", "-q", "{tests}"],
    "files": ["tests/test_*.py"],
    "same_name": "tests/test_{stem}.py",
    "map": [{"paths": ["hooks/**"], "tests": ["tests/test_hooks_*.py"]}],
    "fast": ["tests/test_smoke.py"]
  }
}
```

| Key | Meaning |
|---|---|
| `version` | must be 1 |
| `off` | true: the repository is not gated (HEAD's value decides) |
| `full_on` | globs; a change to a matching path runs every check over every file and the whole suite. `.zetetic/gate.json` is always in the list: a change to the rules is judged by all of the rules |
| `checks[]` | `name`, `argv`, optional `paths` |
| `tests` | optional; `argv` must contain the element `{tests}` |
| `env` | extra environment for the checks; values may use `{top}` (the checkout) and `{common}` (the git common dir) |
| `link` | repository-relative paths that are not tracked (`node_modules`) and are symlinked into the private checkout from the checkout when present |

Placeholders are whole argv elements: `{python}` the resolved interpreter, `{files}` the changed files this
check applies to, `{tests}` the selected test paths.

The selection rule, which is the only rule (`gate_config.plan`):

- Input: the paths that differ between the tree being verified and its base (deletions included). The base is
  HEAD's tree for a commit, the parent's tree for a push or an amend, the empty tree for a first commit.
- **The base has no green record of this kind under these rules** (see Kind, and the cache key): every check
  over every file and the whole suite, whatever changed.
- No changed path: no step.
- A check runs when a changed file that still exists matches one of its `paths` globs (no `paths`: whenever
  something changed). `{files}` expands to those files.
- Tests are the union of: the `tests` of each `map` entry whose `paths` match a changed path, the
  `same_name` test of each changed file (`{stem}` is its name without extension, `-` read as `_`) when that
  file exists, and each changed file that itself matches `files`. A glob in `tests` expands against the tree.
- Nothing selected: the `fast` list. No `fast` list: the whole suite (`argv` without `{tests}`).

Globs: `**/` any directories or none, `**` anything, `*` inside one path segment, `?` one character, matched
against the whole repository-relative path.

An invalid config (in HEAD's tree or in the judged tree) is refused, closed: the hook denies and names the
problem. A config with no `checks` and no `tests` is invalid (it would verify nothing); write `"off": true`
instead.

## What an affected-only gate does and does not prove

A verification of tree T selected by the diff from its base proves that the checks which cover that diff pass
on T, and only when the base itself has a green record of the same kind under the same rules; otherwise the
full configured gate runs. CI runs the whole suite on the pull request and is the check that does not rely on
any of this. The map in `.zetetic/gate.json` is only as good as its author: `tests/test_gate_repo_config.py` pins
the mappings that once missed a dependency (the files copied into `plugins/zetetic-gates`, the documented counts).

## What the gate does not see

The gate parses the Bash command it is shown and the git state of the repository the command runs in. It does
not see: a command wrapped in `bash -c '...'` or `eval`, `GIT_INDEX_FILE=` or `--git-dir`/`--work-tree` pointing
at another index or repository, and commits made by `git merge`, `git cherry-pick` or `git rebase` (no
`git commit` runs). These are limits of reading a command line, not of the verification; CI is the check that
sees every tree that reaches the remote.

## Settings to remove after installing the plugin

Before this plugin version the same hooks ran from `~/.claude/hooks` through `~/.claude/settings.json`.
After installing it, remove these entries so the gate is not registered twice:

- `PreToolUse`, the entry with `"matcher": "Bash"`: only the hook object whose command is
  `python3 -B /Users/<you>/.claude/hooks/gate-proof.py` (timeout 30). The sibling `merge-gate.py` object stays.
- `Stop`: the whole entry whose hook command is `python3 -B /Users/<you>/.claude/hooks/stop-gate-ledger.py`
  (timeout 30).

Old proofs in `<git-common-dir>/zetetic-gates/` are not read (except the proof file a legacy script leaves for
its own task). Files in `~/.claude/hooks` (`gate-proof.py`, `_gate_resolve.py`, `stop-gate-ledger.py`,
`wire_gate_hooks.py`, their tests) are deleted by the owner once the settings entries are gone.
