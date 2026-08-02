# Install: manual + advanced configuration

## Portable evidence-synthesis install

The portable package is intentionally smaller than the full distribution. It
contains the `evidence-synthesis` skill and its sourced references, with no
runtime enforcement or team-agent roster.

### Codex

```bash
codex plugin marketplace add cdeust/zetetic-team-subagents
codex plugin add zetetic-reasoning@zetetic-marketplace
```

### Gemini CLI

```bash
gemini skills install https://github.com/cdeust/zetetic-team-subagents.git \
  --path plugins/zetetic-reasoning/skills/evidence-synthesis
```

The package also carries `gemini-extension.json` for installation from a local
clone with `gemini extensions install ./plugins/zetetic-reasoning`.

## Full Claude Code plugin install (one-line, recommended)

```bash
claude plugin marketplace add cdeust/zetetic-team-subagents
claude plugin install zetetic-team-subagents
```

The plugin's `setup.sh` runs automatically and copies agents, skills, hooks, and tools into `~/.claude/`.

## Manual install (no plugin system)

```bash
git clone https://github.com/cdeust/zetetic-team-subagents.git
cd zetetic-team-subagents
bash scripts/setup.sh install
```

`setup.sh` sub-commands:

| Command | What it does |
|---|---|
| `install` | Install or re-install: copies tracked files to `~/.claude/` |
| `update` | Re-apply agent models, pull new assets, prune orphans |
| `configure` | Create `~/.claude/zetetic-agent-models.json` with calibrated defaults |
| `uninstall` | Remove tracked files; keeps user-modified copies |
| `--dry-run` | Preview any of the above |

## Skills-only install (no agents)

```bash
cp -r zetetic-team-subagents/skills/ ~/.claude/skills/
```

## Per-agent model + effort overrides

`~/.claude/zetetic-agent-models.json`: yours to keep, plugin updates never overwrite. Run `setup.sh configure` to seed with calibrated defaults.

```json
{
  "patterns": [
    { "glob": "genius/*", "model": "sonnet" }
  ],
  "agents": {
    "refactorer":       { "model": "haiku",  "effort": "low"    },
    "engineer":         { "model": "sonnet", "effort": "medium" },
    "architect":        { "model": "opus",   "effort": "high"   },
    "code-reviewer":    "sonnet",
    "test-engineer":    { "effort": "medium" }
  }
}
```

- **String value** (`"sonnet"`): model only. Effort kept from frontmatter.
- **Object value** (`{ model, effort }`): set either or both.
- **Precedence:** per-call parameter > this file > frontmatter default.

### Calibrated defaults shipped by `setup.sh configure`

| Agents | Model | Effort | Why |
|---|---|---|---|
| `refactorer`, `latex-engineer` | haiku | low | Mechanical (Fowler catalog / template) |
| `engineer`, `code-reviewer`, `test-engineer`, `frontend-engineer`, `dba`, `devops-engineer`, `data-scientist`, `experiment-runner`, `mlops`, `ux-designer`, `professor` | sonnet | medium | Procedural with decision points |
| `orchestrator` | opus | medium | Routing, not deep reasoning |
| `architect`, `security-auditor`, `research-scientist`, `paper-writer`, `reviewer-academic` | opus | high | Deep structural / evidence reasoning |
| 97 genius agents (default) | sonnet | medium-or-high (from frontmatter) | Procedural patterns at medium; deep-reasoning patterns (Feynman, Dijkstra, Lamport, Gödel, Einstein) at high |

Estimated token savings vs. all-opus default: **~2.5–3×** on typical sessions (measured against opus-only baseline; report your own measurements at [Discussions](https://github.com/cdeust/zetetic-team-subagents/discussions) if they differ).

Re-run `setup.sh update` after editing.

## Adaptive reasoning depth (stakes-driven)

Five team agents (`engineer`, `architect`, `code-reviewer`, `security-auditor`, `research-scientist`) adjust reasoning depth dynamically:

- **Low-stakes** change → reason one level below baseline (skip exploratory alternatives)
- **Medium-stakes** → baseline
- **High-stakes** → reason one level above baseline (enumerate alternatives, full verification loop)

Stakes classification is objective (see [`rules/coding-standards.md`](../rules/coding-standards.md) §10). No config: built into the agent's Moves.

## Project-local checker config: `<repo-root>/.zetetic.conf`

```bash
ZETETIC_PROFILE=standard           # strict | standard | permissive
ZETETIC_CHECK_DATA_FORMATS=false   # true to scan .json/.yaml/.toml/.sql/.csv
```

**Profiles:**

- `strict`: UNSOURCED, MAGIC_NUMBER, TODO_NO_REF all block commits
- `standard` (default): UNSOURCED blocks; MAGIC_NUMBER / TODO_NO_REF warn
- `permissive`: informational; never blocks (use during transition)

**You cannot disable rules via `.zetetic.conf`.** Directives like `DISABLE_UNSOURCED=true`, `SKIP_RULE`, `EXCLUDE_RULE` cause the checker to refuse to load the config. You can override the profile and file/path exclusions; you cannot silence the checks.

## Project-local extensions: `<repo-root>/.zetetic-check.sh`

Optional Bash script sourced by `zetetic-checker.sh` if present. Can add project-specific checks that increment `ERRORS` or `WARNINGS`. Cannot disable built-in checks.
