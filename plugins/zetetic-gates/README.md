# zetetic-gates

Shared source, craftsmanship, secret-read, prose and fail-before checks for Claude Code and
Codex. The full zetetic-team-subagents plugin includes the same controls.

## Install

Claude Code:

```sh
claude plugin marketplace add cdeust/zetetic-team-subagents
claude plugin install zetetic-gates
```

Codex, once this version is published:

```sh
codex plugin marketplace add cdeust/zetetic-team-subagents
codex plugin add zetetic-gates@zetetic-marketplace
```

Start a new session. In Codex, review and trust the hooks through `/hooks`;
installation alone does not grant execution trust. Install either this package
or the full plugin to avoid duplicate checks.

## Controls

- Agent-issued commits and pushes: source discipline, craftsmanship and staged
  prose. Source checking uses the declared project profile. Structural and prose checks read
  the index version, not a possibly different working file.
- Edits: source/layer hints and checks for removed definitions. Codex patches
  are translated before these checks, without writing their proposed content.
- Secret reads: the existing secret shield refuses recognized credential paths.
- Returned messages and outbound prose: detected writing patterns request a
  rewrite or refuse publication. Blocking mode is part of the package.

`.zetetic.conf` and `.craftsmanship.conf` retain their existing configuration
semantics. [Migration guidance](docs/MIGRATION.md) explains adoption in an
existing codebase. Repository tests and evidence review remain necessary.

These are mechanical checks with a defined scope. They cannot establish the
truth of a citation or guarantee prose has no stylistic flaws. Stop hooks keep
the existing continuation-loop protection. Opaque shell scripts and human
commits need native Git hooks for enforcement independent of the assistant.

Canonical checkers live in the parent repository. `scripts/sync-gates.py`
generates the bundled copies; tests reject drift. See
[shared-host design and verification](../../docs/shared-host-gates.md).

## The fail-before gate

`tools/fail-before-checker.sh` proves that a test the diff adds can fail: the
changed test files are copied over a throwaway checkout of the base and run
there. A new pytest node that passes against the old code is reported
`VACUOUS`, a warning under the standard profile and blocking under
`ZETETIC_PROFILE=strict`. A run that reaches no verdict is `INCONCLUSIVE`,
never a pass. `hooks/pre-push-fail-before.sh` runs it when Claude Code issues
`git push`. Rationale and limits: [docs/fail-before.md](docs/fail-before.md).

Outside Claude Code the same gate runs from a plain git hook:
`printf 'exec plugins/zetetic-gates/tools/fail-before-checker.sh\n' > .git/hooks/pre-push && chmod +x .git/hooks/pre-push`
(adjust the path to where the plugin is checked out).
