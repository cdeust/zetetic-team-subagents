# zetetic-team-subagents

The plugin that defines the agents, skills, commands, hooks and rules every other
repository runs under. Python tooling, Markdown agent definitions.

Global rules are imported, not restated:

@~/.claude/rules/model-behavior.md
@~/.claude/rules/coding-standards.md

## Repo-specific constraints

- **Any `.md` under `agents/` is parsed as an agent definition.** Non-agent documentation goes in `rules/`, never in `agents/`.
- **The zetetic spine is generated, not hand-edited.** `scripts/generate-spine.py` injects the `<zetetic-spine>` block into every anchor-bearing agent, delimited by HTML comments and idempotent, with `--check` for CI. Edit the generator, never the 117 outputs.
- **This clone is live-mounted as the installed plugin** — edits take effect immediately in running sessions. Never edit `~/.claude/plugins/cache`; change it here.
- **Hooks are the enforcement layer**, instructions are advisory. `hooks/stop-acceptance-gate.py` gates turn-end: it resolves the repo's own `tools/acceptance-gate.sh` or falls back to this plugin's, and blocks everywhere when `ABL_STOP_BLOCK=on`. Gate definitions live in `memory/acceptance-gates*.yaml`; the universal set is `acceptance-gates.global.yaml`.
- **`/zetetic:engineering-loop` is the mandatory entry point** for any request that touches code (`commands/zetetic/engineering-loop.md`). It names the three contract violations — "pre-existing", a skip, and a red PR — as refusals.

## Etiquette

Conventional commits, staged file-by-file. One PR per concern. Do not merge your own PR
without the owner's go-ahead.
