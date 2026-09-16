# Zetetic Loop

A portable goal-driven iteration slice for Codex and Gemini CLI. It contains four
skills and no packaged scripts or assets. It does not execute commands on its own
or install background components; the skills ask the host to run the checks a
goal file names and to quote their output.

| Skill | Does |
|---|---|
| `goal` | compiles a request into `.zetetic/goals/<slug>.md`: end state, non-goals, criteria as commands with expected results, budget |
| `plan` | writes ordered steps with a check each, and verifies the plan against the criteria before any code |
| `verify-goal` | runs every criterion as a real command and ledgers exit code and output per criterion |
| `refine-goal` | turns the ledger into the next backlog, tightens loose criteria, records the lesson |

The goal file is the single source of truth. A host's native goal command, where
one exists, receives a one-line mirror of the end state so its own stop check and
the contract agree.

## Install in Codex

```bash
codex plugin marketplace add cdeust/zetetic-team-subagents
codex plugin add zetetic-loop@zetetic-marketplace
```

## Install in Gemini CLI

Install one skill directly from the repository:

```bash
gemini skills install https://github.com/cdeust/zetetic-team-subagents.git \
  --path plugins/zetetic-loop/skills/goal
```

From a local clone, the package can also be installed as an extension:

```bash
gemini extensions install ./plugins/zetetic-loop
```

## Scope

The package supports goal-driven iteration only: contract first, plan verified
against it, checks run as processes, refinement that narrows and never widens the
end state. It does not provide automated enforcement or the repository's larger
agent roster.
