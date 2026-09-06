# Zetetic Design

A portable UX/UI design and accessibility-audit slice for Codex and Gemini
CLI. It contains one skill and no packaged scripts or assets. It does not
execute commands or install background components.

## Install in Codex

```bash
codex plugin marketplace add cdeust/zetetic-team-subagents
codex plugin add zetetic-design@zetetic-marketplace
```

## Install in Gemini CLI

Install the skill directly from the repository:

```bash
gemini skills install https://github.com/cdeust/zetetic-team-subagents.git \
  --path plugins/zetetic-design/skills/design
```

From a local clone, the package can also be installed as an extension:

```bash
gemini extensions install ./plugins/zetetic-design
```

## Scope

The package supports UX/UI design and accessibility audits only. It asks the
host to name the user, task, and success criterion before any layout
decision, enforce WCAG 2.2 AA as a constraint from the first sketch, walk the
10 Nielsen heuristics, and refuse patterns that defeat usability or research
integrity. It does not provide automated enforcement or the repository's
larger agent roster.
