# Agent guidance for zetetic-team-subagents

This is the former body of `CLAUDE.md`, moved here on 2026-09-08 so that it is read on
demand instead of being re-sent to the model on every turn (owner correction: CLAUDE.md
stays nearly empty; the host loads what it needs when it needs it). Nothing was removed
except the dangling "Global rules are imported, not restated" sentence and the two `@`
import lines under it, since those files are already loaded on demand by the host's
skills and agents rather than by this repository.

# zetetic-team-subagents

The plugin that defines the agents, skills, commands, hooks and rules every other
repository runs under. Python tooling, Markdown agent definitions.

## Repo-specific constraints

- **Any `.md` under `agents/` is parsed as an agent definition.** Non-agent documentation goes in `rules/`, never in `agents/`.
- **The zetetic spine is generated, not hand-edited.** `scripts/generate-spine.py` injects the `<zetetic-spine>` block into every anchor-bearing agent, delimited by HTML comments and idempotent, with `--check` for CI. Edit the generator, never the 117 outputs.
- **This clone is live-mounted as the installed plugin** - edits take effect immediately in running sessions. Never edit `~/.claude/plugins/cache`; change it here.
- **Hooks are the enforcement layer**, instructions are advisory. `hooks/stop-acceptance-gate.py` gates turn-end: it resolves the repo's own `tools/acceptance-gate.sh` or falls back to this plugin's, and blocks everywhere when `ABL_STOP_BLOCK=on`. Gate definitions live in `memory/acceptance-gates*.yaml`; the universal set is `acceptance-gates.global.yaml`.
- **`/zetetic:engineering-loop` is the mandatory entry point** for any request that touches code (`commands/zetetic/engineering-loop.md`). It names the three contract violations - "pre-existing", a skip, and a red PR - as refusals.

## Etiquette

Conventional commits, staged file-by-file. One PR per concern. A pull request merges when
CI is green and a review verdict is posted on it; the owner does not gate merges by hand.
CI is the authority: it exists to catch regressions and enforce the engineering standards.
