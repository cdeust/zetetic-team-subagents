# The commit and push gate

No commit or push of an unverified tree. Verification is an async task keyed by the kind of act, the tree hash,
the rules and the runner; the hook that guards `git commit` reads the task's state and never waits
(`docs/async-tasks.md`).

## Flow

```
git add ...            PostToolUse hooks/gate-start.py   starts the commit task for the staged tree if absent, returns at once
git commit ...         PreToolUse  hooks/gate-proof.py   reads gate-commit-<staged tree>-<rules>-<runner>:
                                                           done and green  -> allow
                                                           failed          -> deny, names the output file and the runner
                                                           running/started -> deny, "retry when it finishes"
git push / gh pr create  PreToolUse same hook            reads gate-push-<tip tree>-<rules>-<runner> for the tip of EVERY ref published
Stop                   Stop        hooks/stop-gate-ledger.py  an open failure blocks the stop while work is at risk
```

The task id is `gate-<kind>-<tree>-<rules>-<runner>` (the cache key below); the state directory is `<git-common-dir>/zetetic-tasks/`, so every worktree of a repository shares
it and the repository is the namespace. Asking never reruns a green key and never starts a second task for a key
that has one.

Status of a verification: `tools/task.sh status <task id> --repo <repo>` (the hook prints the exact command).
Retry after an infrastructure failure: `python3 hooks/lib/gate_task.py requeue --repo <repo>
--id <task id>` (the failure names it). It relaunches the command the task recorded, whose runner (the hook's
interpreter, argv[0], and the checks' environment, `--env`) travels with it: a requeue from a shell whose environment
is not the hook's still retries the verification the hook keyed. A worker that died without a result is requeued
once, automatically, by the next attempt (attempt N+1, counted in the record). Waiver: `python3 hooks/lib/gate_task.py waive --tree <tree> --reason
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
is run. The hooks never write this file. `ZETETIC_GATE_TRUSTED_REPOS` replaces the path (tests). A repository's
project settings can set session environment variables, so an **override** that points inside the repository being
judged (its working tree or its git directory) is ignored: a repository cannot list itself. A path to some other
file that already lists the repository's exact real path would still be honoured.

The **default** location is not an override. A repository whose root contains `~/.claude/zetetic` (a dotfiles
repository at `$HOME`) is still trustable: the two files themselves, `gate-trusted-repos` and
`gate-rule-changes`, are exempt from the in-repository rule, and only they. The exemption holds only while
`$HOME` is the account's home directory (the one the account database gives); a session whose `HOME` was
redirected into the repository gets no exemption, so the redirected default counts as an override and is ignored.

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

## Rule changes: rules may only grow without the owner

The union above lags one commit. Commit A deletes `.zetetic/gate.json` (or replaces it by one check, `["true"]`);
it passes, because HEAD's old checks still pass on it. Commit B is then judged by a HEAD with no rules and a
failing file is allowed. HEAD alone is not a floor either, because commands the gate does not judge move it:
after `git checkout --orphan x` (the index is kept) or `git reset --soft <a commit before the gate>`, HEAD has no
rules, so dropping the config weakened nothing and `git push -f origin x:main` published a failing tree.

**The invariant.** No `git commit` and no `git push` the hook judges is allowed when the rules it would leave in
force (in the new commit, or on a destination ref) are weaker than one of its **anchors**, unless the owner's
acknowledgement file holds the exact `<repository> <hash>` line for that end state. The anchors:

| Anchor | For | What it is |
|---|---|---|
| HEAD's rules | a commit | the rules of HEAD's tree |
| the floor | a commit and a push | the strongest rules the hooks have seen in force for this repository, kept by the user outside every repository (below) |
| each destination | a push | the rules of `refs/remotes/<remote>/<branch>` for each branch the push updates (the `dst` of a refspec, `HEAD` meaning the current branch; a refspec-less push adds the current branch's upstream), as of the last fetch |

Each anchor is compared on its own (`hooks/lib/gate_superset.py`): rule states are only partially ordered, two
branches may each add a check the other lacks, so there is no single "strongest" state to compare with. One
acknowledgement line, the hash of the end state, covers every anchor at once.

A denied commit or push lists every weakened rule, with the anchor it comes from:

```
GATE-PROOF: this commit weakens the gate rules of <repo>; rules may only grow without you. Nothing was run.
  - check "no-bad" was removed
  - env changed (a variable can disarm a check)
If you intend this, add this line to ~/.claude/zetetic/gate-rule-changes (create the file if it is absent):
<absolute repository path> <hash of the new rules state>
It covers this one rules state only. Then retry.
```

The denial names each rule being weakened; a rule weakened against the floor ends with `(the floor recorded for
this repository in <file>)`, one weakened against a destination with `(the rules of refs/remotes/origin/main, as
of the last fetch)`. The line is `<absolute repository path> <32 hex>`: the hash is of the rules state the commit
or the pushed tip would LEAVE BEHIND (kind, rules, and for a legacy script its object id), so it covers that one
state in that one repository; the next, different weakening is denied again. Listing the main checkout covers its
worktrees. The hooks never write the file and never offer to; `ZETETIC_GATE_RULE_CHANGES` replaces the path
(tests), under the same rule as the trusted list (an override inside the repository is ignored).

**The floor** (`hooks/lib/gate_floor.py`) is one file per repository, in a directory no repository controls:

```
~/.claude/zetetic/gate-rule-floor/<32 hex>.jsonl     the hex: sha256 of the real path of the main checkout
{"repo": "<main checkout>", "op": "raise", "states": [<rule state>, ...]}
{"repo": "<main checkout>", "op": "set", "states": [<rule state>, ...]}
```

The identity of a repository is the real path of its main checkout, as for the acknowledgement file, so the
worktrees of a checkout share its floor. Each line is one change, appended in one write (concurrent hooks
neither interleave lines nor lose one), and the floor is the replay of the file in line order: `raise` keeps
the maximal states of the floor and the line's states, `set` keeps the maximal states of the line's states. A
rule state is `{"kind", "cfg", "scripts", "script"}`, what `state_hash` hashes. The file is created 0600 in a
0700 directory.

- When every verdict of a call allows it, the hook records what the call leaves in force: the new commit's rules,
  or each pushed tip's rules and HEAD's (a push leaves HEAD in force). The line is `raise`, unless an end state
  passed only by an acknowledgement: then the owner lowered the floor and the line is `set`.
- When a call is denied, HEAD's rules are recorded (`raise`): they are in force whatever the verdict. This goes
  further than "record only what is allowed" on purpose: the first judged commit attempt in a gated repository
  seeds the floor even when it is denied (a verification just started, say).
- Nothing is written when the floor would not change; the head-start hook (`gate-start.py`) never writes.

**How the owner lowers the floor:** with the same acknowledgement line. The weakened commit or push is then
allowed, and the floor becomes what that call leaves in force, so a later growth from the lowered state needs no
second line. Pushing an acknowledged branch without rules together with `main` keeps `main`'s rules in the floor.

**Closed by default.** A floor file that exists but cannot be read or parsed (a line that is not of the form
above, a line naming another repository, a state whose rules are invalid) denies every commit and push in that
repository, with the file and the line; it is never read as empty. `ZETETIC_GATE_RULE_FLOOR` names another
directory (tests); the default directory is read as well, so an override pointing at an empty directory cannot
hide a floor already kept, and an override (or a redirected HOME) inside the repository is refused. Where only
the floor holds (an orphan branch that declares nothing), a crash of the hook and an unreadable payload refuse,
as they do where a gate is declared.

**Where the floor starts.** A repository whose rules no judged call has seen in force has no floor file, and is
judged by HEAD's rules and the destinations alone, as before. So `git checkout --orphan` as the very first act in
a repository, before any `git commit` or `git push` the hook judged there, still drops the rules of that orphan
(`git push -f origin x:main` is refused by the destination anchor; a push to a new branch is not). One judged
commit attempt in the repository, allowed or denied, closes it. Tests: `tests/test_gate_floor_user.py` (the
attacks, against the real hooks) and `tests/test_gate_floor_record.py` (the file and the destinations).

**Consequence for branches.** The floor is the repository's, not a branch's: a check added on one branch and
committed there is kept on every branch. Committing on a branch that lacks it is denied until that branch has the
check, or the owner acknowledges the branch's state (which lowers the floor to it).

**Superset, precisely** (`hooks/lib/gate_superset.py`; sound, deliberately conservative: everything it calls
growth is growth; a spelling it cannot prove is reported and acknowledged once). With `old` = an anchor's rules
and `new` = the rules the commit or the pushed tip leaves behind:

| Part | `new` is no weaker when |
|---|---|
| `checks[]` | every check of `old` has a check of `new` with the **same `argv`** whose path selection covers it. `old` has no `paths` (runs for any change, deletions too): `new` has none. Otherwise `new` has none, or holds `**`, or holds every pattern of `old` literally (patterns are compared as strings). A `new` with `"scope": "added"` keeps only an `old` with the same scope (it judges fewer files); dropping the scope is growth. Names do not matter. Added checks are growth; a removed, replaced or narrowed check (different `argv`, narrowed or dropped `paths`, a scope added) is not |
| `tests` | if `old` has a tests block, `new` has one with equal `argv`, `files` and `same_name` (either one changed changes which tests a change selects, and an empty selection falls back to the whole suite); `fast` equal, or non-empty in `old` and a superset in `new`; `map`: the same set of path patterns, and for each pattern `new` runs every test `old` ran (a pattern may gain tests; a new pattern would take paths away from the fallback, a removed one gives them up) |
| `full_on` | `new` has every entry of `old` |
| `env` | equal (an added variable such as `PYTEST_ADDOPTS=--co` can disarm a check) |
| declaration | `off: true`, a deleted config, or no declaration at all is a weakening when the anchor declares rules. A stack default (no config, `package.json`, `Cargo.toml`, ...) is compared as the config it generates, so a config that replaces it must keep its checks |
| legacy `scripts/gate.sh` | with no config, deleting it, making it non-executable, replacing it by another script or by a config is a weakening: a script's content cannot be compared, so the object id of the script itself is the rule (other files of `scripts/` do not count) |

An anchor with no rules has nothing to weaken: a repository with no rules at HEAD, no floor and no destination
with rules is not floored at all. What a check RUNS (a script it calls, a test file) is not a rule and is not
compared: the set of declared commands is the floor,
and CI is the check that sees what they do.

## Kind, and the cache key

A verification is keyed by **kind + tree + digest of the effective rules + digest of the runner**:
`commit-<tree>-<12 hex>-<12 hex>` or `push-<tree>-<12 hex>-<12 hex>`.

- **Kind.** A push needs a green record of kind `push`; a commit's record never stands in for it. A
  repository whose gate has push-only checks (`scripts/gate.sh push` adding `test bench oracle`) keeps them.
- **Rules.** A verdict is never reused under other rules.
- **Runner.** A verdict is never reused under another runner (The verdict is a function of the tree, below): a
  failure under an interpreter without pytest does not follow the tree to an interpreter that has it.
- **Affected-only selection is valid only when the base tree has a green record on the same basis** (kind,
  rules, runner); the base is HEAD's tree for a commit, the tip's parent for a push or an amend. Otherwise the
  full configured gate runs: every check over every file (a ratchet check over the files the change adds), and
  the whole suite. A push of a branch whose parent was never pushed is therefore verified in full, and so is the
  first commit after a change to the rules or the runner.

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
| `refs/tags/t:refs/heads/main`, `refs/tags/*:refs/heads/*`, `t:refs/heads/x` | the commit behind each tag: `src` is resolved whatever `dst` is, tags included |
| `--tags`, `refs/tags/t`, `tag t`, `feat:refs/tags/t` | the commit behind each tag, unless the remote already has it (below) |
| `--follow-tags`, or `push.followTags=true` without `--no-follow-tags` | the pushed tips, and the annotated tags whose commit is an ancestor of one of them and not on the remote |
| `:feat`, `--delete`, `--dry-run` | no commit: not gated |

**Tags.** A tag publishes the commit behind it (the peeled commit of an annotated tag), so each tagged commit that
is not already on the remote needs a green push record, and the denial names the tag (`[tag v1] GATE-PROOF: ...`).
"Already on the remote" means a remote-tracking ref of the remote the push names reaches the commit
(`git rev-list <commit> --not --remotes=<remote>` is empty), as of the last fetch; a tag that points at a blob
or a tree publishes no commit. `git push --tags` pushes tags only, as git does (no current-branch default).

**Options are parsed the way git parses them** (`hooks/lib/gate_pushargs.py`). A short cluster is read letter by
letter and `-o` takes the REST of the cluster as its value: `-odebug` and `-on` are the option `-o` with a
value, not the flags `d` and `n`; `-vodebug` is `-v` then `-o debug`. A long option may be abbreviated to any
unambiguous prefix (`--dry`, `--dele`) and negated (`--no-tags`); `--repo`, `--receive-pack`, `--exec`,
`--push-option` and `--recurse-submodules` take the next word when written without `=`. The table of valued
options is compared by `tests/test_gate_publish_attacks.py` with what `git push -h` documents (git 2.50.1), so a
git that grows a valued option fails a test instead of mis-parsing silently.

A ref that does not resolve to a commit (a name that does not exist, a detached HEAD with no ref named, a branch
that exists only on the remote) is **denied with the reason**: the hook never judges a tree it was not asked
about. Each tip with no green push record starts its verification; the denial lists the tips by name.

## What the hooks do, and what bounds them

A commit costs a fixed number of git calls; a push costs a fixed number per published tip, and a push that
publishes tags costs a number of calls proportional to the tags. `--tags` lists every local tag in one call, then
makes up to five calls per tag (its commit, whether the remote has it, and for a tag the remote lacks, its tree
and its parent's tree); `--follow-tags` makes, for each annotated tag, one call for its commit and one ancestry
check per pushed tip, then the same up to five calls for each tag it follows. There is no timer and no cap on that number: a repository with ten thousand tags pays ten
thousand times the cost of one, and the push is judged on all of them. Each call reads refs and a few small
objects: `git rev-parse --show-toplevel --git-common-dir` reads refs and config, `git write-tree` reads the index
file and writes tree objects, `git ls-tree` / `git cat-file blob` read the rules out of one tree, `git rev-parse
--verify <ref>^{commit}` reads one ref and one commit. No call touches the network (`GIT_NO_LAZY_FETCH=1` forbids a partial clone from fetching) or
stats the working tree, and none carries a timer: a test (`tests/test_gate_async.py`) fails if any hook module
bounds a call by time. The changed-file list, the checkout of the tree and the checks run in the task, never in
a hook. The Stop hook is the one exception to "never stats the working tree": the baseline's question "are
tracked changes still uncommitted" needs `git diff --quiet HEAD`, which stats tracked files only.

**Every git call reads the objects that are really there.** git substitutes objects when told to: a replace ref
(`git replace <object> <substitute>`, kept in `refs/replace/` or in any namespace `GIT_REPLACE_REF_BASE` names)
makes one object read as another, and a graft (`.git/info/grafts`, or the file `GIT_GRAFT_FILE` names) gives a
commit other parents. One ungated `git replace` of the blob of HEAD's `.zetetic/gate.json` by `{"off": true}`
made the rules read as off; a replace of a checked file's blob made the worker check the substitute; a graft
moves the base a change is measured from. So the gate starts every git process through one runner
(`hooks/lib/gate_git.run`, the worker's calls included) that sets `GIT_NO_REPLACE_OBJECTS=1` and
`GIT_GRAFT_FILE` to the null device and removes `GIT_REPLACE_REF_BASE` from the environment (measured on git
2.50.1: `GIT_NO_REPLACE_OBJECTS=1` disables replace refs in every namespace and leaves grafts in force; the null
graft file removes them). Tests: `tests/test_gate_git_objects.py`.

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
raised and is not the guarantee.) Measured on Claude Code 2.1.301 with a throwaway session and a marker file
written by the guarded Bash call: a PreToolUse hook that exits 1, is killed by SIGKILL, exceeds its timeout, or
names a script that does not exist lets the call run when `onFailure` is absent, and does not let it run with
`"onFailure": "block"`; the result is the same whether the hook comes from a settings file, from a plugin's
`hooks/hooks.json` or from the `hooks` of `.claude-plugin/plugin.json`. `hooks/run-python.sh` fails closed for `gate-proof.py` only when no Python 3
is found: it refuses a call whose payload has `git` or `gh` as a **command word**, and lets any other call through so a
host without Python can still install one. The payload is first dequoted: the JSON escapes `\n`, `\r` and `\t`
become spaces, then every backslash, double quote and single quote is removed, so `"git" push`, `'git' commit`,
`\git push`, `git"" push` and `/usr/bin/"git" push` all read `git push`, as the Python hook reads them (it also
refuses `git\ push`, which the Python hook does not read as git: closed, not open). A command word is then
`git`/`gh` preceded by the start of the command (the colon of the JSON key), a space, one of `; & | ( {`, a
backtick or `/` (a path slash: the basename of `/usr/bin/git`), and followed by a space: `echo highlights`,
`ghost`, `github`, and a working directory under `github` or ending in `/git` are not refused, while
`/usr/bin/git push`, `a && git commit`, `(gh pr create)` and a command after a newline are. The test is a shell
`case` on the payload read with the `read` builtin and dequoted by parameter expansion: it needs no `grep`, no
`sed` and no other tool on the `PATH`. A JSON `\uXXXX` escape is not decoded. Every other hook keeps failing open
there.

## The verdict is a function of the tree

A verdict is a function of (tree, rules, runner), and nothing an agent can change in its working copy or its
session decides it. The worker (`hooks/lib/gate_run.py`) checks the tree out into a private directory through a
private index and runs the checks there. Editing the working tree while a verification runs cannot change its
verdict. The previous gate achieved this by refusing to run when tracked files were modified but unstaged; an
async gate cannot, because the author keeps working.

**The runner** (`hooks/lib/gate_runner.py`) is what a check runs with besides the tree and the rules, and it is
the third component of the key:

- The environment is an allowlist of the hook's variables (`PATH`, `HOME`, `USER`, `LOGNAME`, `SHELL`, `TMPDIR`,
  `TMP`, `TEMP`, `LANG`, `LC_ALL`, `LC_CTYPE`, `LC_MESSAGES`, `TZ`, `TERM`, and the Windows ones a process needs),
  plus `PYTHONDONTWRITEBYTECODE=1`, plus the rule set's own `env`. Everything else is dropped:
  `PYTEST_ADDOPTS=--collect-only` in the session's environment no longer turns a failing suite green, and
  `CLAUDE_PLUGIN_ROOT`, which Claude Code exports to plugin hooks, no longer reaches a repository's tests. `PATH`
  keeps only absolute entries outside the repository (its working tree, its main checkout, its git directory), so
  an untracked `node_modules/.bin` or `.venv/bin` cannot stand in for a command a check runs.
- `{python}` is the interpreter that runs the gate itself (`sys.executable`, the one `hooks/run-python.sh`
  found), never the repository's `.venv`, whose content is the working copy's. Its identity is what a check sees
  when it starts it: the executable, its real path, its version, its prefixes, its import path, and the name and
  version of every distribution in its site directories (user site included), measured once with the check
  environment. A `pip install` into it changes the key. An interpreter that would import from the repository (it
  lives there, or an editable install of the working copy is on its path) is refused, closed, with the reason.
  So a verification under a python3 without pytest fails with that interpreter named in the denial, and the same
  tree asked under an interpreter that has pytest is verified again under its own key. A runner built from the
  tree (a venv provisioned from a hash-pinned lock) is not implemented: the interpreter is the host's, named.
- Dependencies never come from the working copy: `link` is gone. The npm stack default installs from the
  tree's `package-lock.json` (`npm ci`, its first check) into the private checkout. The Cargo stack default sets
  `CARGO_TARGET_DIR={common}/zetetic-gate-target`, shared by every verification: cargo locks that directory and
  keys a workspace crate's artifacts by its source path, a fresh private directory each time.

The task records its runner: the interpreter is the command's argv[0] and the checks' environment is its `--env`
argument, so the record says what a verdict was reached with, and a requeue launched from any shell runs the same
runner. The worker re-derives the rules digest and the runner digest (filtering `--env` through the allowlist again
and measuring the interpreter now) and refuses to run when either differs from the ones it was started with (a task
started by hand with another variable, or an interpreter that changed since). Each worker creates its own
private directory (`mkdtemp`: the checkout, its private index and a legacy script's exported copy) and removes
only that directory, on every exit it can observe. Two verifications of one tree under two keys (a commit and
another runner, two worktrees) therefore never share or delete each other's checkout. A worker killed with
SIGKILL (which cannot be handled) leaves its uniquely named directory under the system temp directory; no later
worker removes it.

**This repository's own gate.** The CI job `gate-self-verification` (`.github/workflows/ci.yml`) runs
`python hooks/lib/gate_task.py verify --repo . --base <PR base>` on HEAD's tree, with `CLAUDE_PLUGIN_ROOT` set as
Claude Code sets it and the trusted list, the floor and the task state in the runner's temp directory: the hook's
own planning, then the full configured gate (no earlier record exists there). Its craftsmanship check is a ratchet
(`"scope": "added"`), the policy of CI's own craftsmanship job: every file a change adds must comply, legacy files
are reported by CI's informational sweep, not blocked. Round 5 of the review measured that without the ratchet and
the allowlist no tree of this repository could ever pass its gate.

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
| `checks[]` | `name`, `argv`, optional `paths`, optional `"scope": "added"`: a ratchet, whose `{files}` are only the files the change ADDS, in full mode too (it runs only when one matches its `paths`); legacy files are left to CI's informational sweep |
| `tests` | optional; `argv` must contain the element `{tests}` |
| `env` | extra environment for the checks, added to the runner's allowlist; values may use `{top}` (the private checkout of the tree) and `{common}` (the git common dir) |

`link` is refused (a config that has it is invalid): it brought an untracked working-copy directory into the
checkout, so a shim there decided the verdict. Install dependencies with a check instead (`npm ci`, as the npm
stack default does from the tree's lock).

Placeholders are whole argv elements: `{python}` the interpreter the runner names, `{files}` the changed files
this check applies to, `{tests}` the selected test paths.

The selection rule, which is the only rule (`gate_config.plan`):

- Input: the paths that differ between the tree being verified and its base (deletions included). The base is
  HEAD's tree for a commit, the parent's tree for a push or an amend, the empty tree for a first commit.
- **The base has no green record on the same basis** (see Kind, and the cache key): every check over every file
  (a ratchet check over the added files) and the whole suite, whatever changed.
- No changed path: no step.
- A check runs when a changed file that still exists matches one of its `paths` globs (no `paths`: whenever
  something changed). `{files}` expands to those files. A ratchet check (`"scope": "added"`) considers only the
  files the change adds.
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
on T, and only when the base itself has a green record under the same rules and runner; otherwise the
full configured gate runs. CI runs the whole suite on the pull request and is the check that does not rely on
any of this. The map in `.zetetic/gate.json` is only as good as its author: `tests/test_gate_repo_config.py` pins
the mappings that once missed a dependency (the files copied into `plugins/zetetic-gates`, the documented counts).

## What the gate does not see (known limits)

The gate parses the Bash command it is shown and the git state of the repository the command runs in. It does
not see:

- A wrapped or disguised command: `bash -c '...'`, `sh -c`, `eval`, quoted words such as `g''it`, a variable
  holding the program (`G=git; $G push`), an alias. A command substitution is seen wherever it is written,
  double quotes included (`out="$(git commit ...)"`, backticks, `<(...)`): bash runs it, so the gate judges it,
  and a `cd` inside a subshell, a substitution or a pipeline element does not move what follows. A refspec computed
  by a substitution (`git push origin "$(git branch --show-current)"`) is not evaluated: it names no ref, and the
  push is refused with the reason. A `)` in a `case` pattern inside a substitution ends it early.
- Another index or repository: `GIT_INDEX_FILE=`, `--git-dir`, `--work-tree`.
- Commits that no `git commit` makes: `git merge`, `git cherry-pick`, `git rebase`.
- What a check runs: a rule is the declared command (`argv`, `paths`, the test map); the content of a script a
  check calls is not compared by the rule floor (Rule changes).
- The start of the floor: a repository's floor holds only what a judged call saw in force (Rule changes, "Where the
  floor starts"); the identity is the main checkout's path, so a renamed checkout or a fresh clone starts with an
  empty floor.
- A destination is known only through its remote-tracking ref, as of the last fetch: a push to a URL, or to a
  branch never fetched (or whose remote-tracking ref was deleted), adds no destination anchor.
- The floor file and the acknowledgement file are the owner's: an ungated `rm` of the floor file is the same
  kind of act as an ungated edit of the acknowledgement file, and the gate cannot tell either from the owner.
- A legacy script's siblings: only `scripts/gate.sh` itself is compared.

These are limits of reading a command line and of comparing declared rules, not of the verification; CI is the
check that sees every tree that reaches the remote.

The Stop ledger keeps its behaviour: a later green of the same verb lifts the failures of OTHER trees (the
ledger is ordered by line, and "an open failure" is one with no later green line of the same verb); the Stop
block means "no failure is open", not "every failed tree was fixed".

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
