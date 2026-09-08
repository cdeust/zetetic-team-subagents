# zetetic-team-subagents

The plugin that defines the agents, skills, commands, hooks and rules every other
repository runs under. Python tooling, Markdown agent definitions.

This file is deliberately short: the host loads what it needs on demand. Everything that
used to be here is in `docs/agent-guidance.md` (repo-specific constraints, etiquette).
Read it before any non-trivial change.

## Commands

```bash
bash tests/run-all.sh                                   # full test suite
ZETETIC_PROFILE=strict bash tools/zetetic-checker.sh --staged
bash tools/doc-count-check.sh
bash tools/doc-command-check.sh
```

## Non-negotiables

- Any `.md` under `agents/` is parsed as an agent definition. Non-agent documentation
  goes in `rules/`, never in `agents/`.
- The zetetic spine is generated, not hand-edited: `scripts/generate-spine.py` injects
  the `<zetetic-spine>` block into every anchor-bearing agent. Edit the generator, never
  the outputs.
- This clone is live-mounted as the installed plugin: edits take effect immediately in
  running sessions. Never edit `~/.claude/plugins/cache`; change it here.
