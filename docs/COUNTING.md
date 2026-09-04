# Counting convention

Every quantity this project states about itself is defined here, once, with the
exact command that produces it. `tools/doc-count-check.sh` runs those commands in
CI and fails the build if any document disagrees.

## Why this file exists

Four files gave four different totals and none matched the tree (issue #72):
README's badge said 119 agents while its footer said 118, CONTRIBUTING said 22
team agents and 64 skills, and `marketplace.json` said 78 skills and 23 team
agents. `memory/scope-coverage.md` had already recorded a 118-vs-119
discrepancy, which shows the drift was noticed once and then re-accumulated,
because nothing measured it.

The root cause was not carelessness. It was that "how many skills are there?"
had no answer: is a category `_index.md` a skill, is `agents/genius/INDEX.md` an
agent, is a hook a registration in `hooks.json` or a file in `hooks/`? Different
people answered differently and every answer was defensible. So the convention
is decided here, and the numbers are derived from it rather than remembered.

## The quantities

Run every command from the repository root. Each is a claim key used by the
gate; the value in the last column was measured on 2026-08-04.

| key | quantity | command | value |
|---|---|---|---|
| `genius_agents` | genius agents | `grep -l '^name:' agents/genius/*.md \| wc -l` | 97 |
| `team_agents` | team-role agents | `grep -l '^name:' agents/*.md \| wc -l` | 23 |
| `agents_total` | agents, all kinds | `genius_agents + team_agents` | 120 |
| `problem_skills` | problem-shaped skills | `find skills -name 'SKILL.md' \| wc -l` | 15 |
| `category_skills` | category skills | `skills_total - problem_skills` | 65 |
| `skills_total` | skill documents | `find skills -name '*.md' ! -name '_index.md' ! -name '_template.md' \| wc -l` | 80 |
| `hook_registrations` | lifecycle hook registrations | `jq '[.hooks[][].hooks[]] \| length' hooks/hooks.json` | 21 |
| `hook_scripts` | hook scripts on disk | `ls hooks/*.sh hooks/*.py \| wc -l` | 22 |
| `commands` | slash commands | `find commands -name '*.md' \| wc -l` | 27 |
| `tools` | tool scripts | `ls tools/*.sh tools/*.py \| wc -l` | 53 |
| `suites` | test suites | `bash tests/run-all.sh --list \| wc -l` | 35 |
| `memory_suites` | memory tool suites | `ls scripts/test-memory-*.sh \| wc -l` | 6 |

## The judgement calls, and why

**An agent is a file with a `name:` frontmatter field.** That excludes
`agents/genius/INDEX.md`, which is a routing table from problem shapes to
agents, not an agent: it has no `name:`, no `<identity>`, and the structural
auditor does not audit it. The definition is mechanical rather than
path-based, so a non-agent document added under `agents/` is excluded by
construction rather than by remembering to exclude it.

**`agents_total` is the sum of two populations, not a third measurement.**
Genius agents and team agents live in different directories and are counted
separately; the total is arithmetic. A single `find agents -name '*.md'` would
silently re-include `INDEX.md` and any future non-agent document.

**Skills are counted in two populations, and the total is one measurement.**
`problem_skills` are the directories holding a `SKILL.md`: the fifteen
problem-shaped entry points a user actually invokes. `category_skills` is
everything else, the individual procedures those entry points route to.
`skills_total` measures all skill documents in one pass, and `category_skills`
is derived by subtraction, so the two populations cannot drift apart from
their total.

`_index.md` and `_template.md` are excluded: an index is navigation and a
template is a form to fill in. Neither is a skill a user can invoke.

**Hooks are two different quantities and both are stated.** A *registration* is
an entry in `hooks/hooks.json`, which is what the Claude Code lifecycle
actually fires: 19. A *script* is a file in `hooks/`: 20. They differ because
not every script on disk is registered. Conflating them is how README came to
say `hooks-19_lifecycle` while `marketplace.json` said 20 hooks, with both
being right about different things and neither saying which.

**Test counts are stated as suites, not as assertions.** The badge used to
claim 288 tests and README's memory section claimed 241, and neither was
reproducible: the bash suites report their own tallies in incompatible formats
(some print `N passed`, the PII suites print a verdict), so no command produces
a defensible total. `suites` is exactly what `tests/run-all.sh --list` reports,
which is the number this project can stand behind. The Python suite's own count
is printed by `python3 -m pytest` and is not restated in prose, so it cannot
drift.

## Adding a claim

Adding a number to README, CONTRIBUTING or `marketplace.json` means adding a
row to the registry at the top of `tools/doc-count-check.sh`: the file, the
quantity key, and a regex with one capture group around the digits.

The gate fails if a registered claim's pattern matches **zero** times, not only
when the number is wrong. Rewording copy so the pattern no longer matches
breaks the build loudly, rather than silently leaving the claim unchecked,
which is the failure mode this whole file exists to close.
