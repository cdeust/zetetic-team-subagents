# Zetetic Loop

A portable goal-driven iteration slice for Codex and Gemini CLI. It contains five
skills and no packaged scripts or assets. It does not execute commands on its own
or install background components; the skills ask the host to run the checks a
goal file names and to quote their output.

| Skill | Does |
|---|---|
| `goal` | compiles a request into `.zetetic/goals/<slug>.md`: end state, non-goals, criteria as commands with expected results, budget |
| `plan` | writes ordered steps with a check each, and verifies the plan against the criteria before any code |
| `verify-goal` | runs every criterion as a real command and ledgers exit code and output per criterion |
| `refine-goal` | turns the ledger into the next backlog, tightens loose criteria, records the lesson |
| `advisor-model` | consults a separate model at a selected plan, fork, or completion decision; the executor retains ownership |

The goal file is the single source of truth. A host's native goal command, where
one exists, receives a one-line mirror of the end state so its own stop check and
the contract agree.

An iteration is counted when a plan verdict is recorded, including an unsound
verdict. Its execution and verification may finish at the last allowed iteration.
Unspecified limits are `null` and unbounded. A finite token limit requires usage
accounting; missing accounting blocks the goal. Budget checks happen between
operations, and a hard token cap depends on host support. Repair preserves counters.

To add advice to a goal, invoke `$advisor-model` with its goal file and the
decision to review. The skill records the selection for later ticks. Native
advisor access depends on the host; a delegated advisor sees only supplied
context. Consultation is advisory and its usage belongs to the goal budget.

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

The package supports standalone advisor consultation and goal-driven iteration:
contract first, plan verified
against it, checks run as processes, refinement that narrows and never widens the
end state. It does not provide automated enforcement or the repository's larger
agent roster.
