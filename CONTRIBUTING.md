# Contributing to zetetic-team-subagents

Thanks for considering a contribution. This project ships **97 reasoning
patterns + 21 team agents + 64 skills + 18 lifecycle hooks**, with
commit-time enforcement of source discipline. Every change is held to the
same standard the agents enforce on user code.

---

## What this project is

A Claude Code plugin: agents (markdown files with frontmatter), skills
(slash commands), hooks (bash scripts that fire on git events), and tools
(bash utilities the agents call). The pre-commit hook
(`hooks/pre-commit-zetetic.sh`) blocks magic numbers, unsourced absolute
claims, and ticket-less TODOs. See [README](README.md) for the full
architecture.

---

## Dev setup

**Prerequisites:** bash 4+, GNU coreutils, ripgrep (`rg`), python3 (for
some tooling utilities).

```bash
git clone https://github.com/cdeust/zetetic-team-subagents.git
cd zetetic-team-subagents

# Run the test suite (functional, ACL, concurrency, stale-lock, MCP, PII)
bash tests/run-all.sh

# Try the zetetic-checker on a sample file
ZETETIC_PROFILE=strict bash tools/zetetic-checker.sh --staged
```

Install the plugin into your local Claude Code instance:

```bash
claude plugin marketplace add cdeust/zetetic-team-subagents
claude plugin install zetetic-team-subagents
```

---

## Branching + workflow

- `main` is the integration branch. PRs land here.
- Branch naming: `feature/<short-slug>`, `fix/<short-slug>`, `docs/<short-slug>`, `agent/<name>` (for new agent definitions).
- One agent per PR (when adding new genius agents). The genius INDEX update goes in the same commit.
- Pre-commit hook runs on every commit. If it blocks, fix the violation
  rather than bypassing — bypassing requires explicit human reviewer
  approval.

---

## Adding a genius agent

A genius agent is a reasoning *method*, not a personality. The agent's
markdown body must answer:

1. **Primary source.** What published academic work is this method drawn
   from? Cite the paper, the canonical work, or the documented body of
   practice.
2. **Refusal conditions.** Under what conditions does this agent stop and
   say "I don't know"? List them explicitly.
3. **Canonical moves.** What are the steps this method actually takes?
   Numbered, named, observable.
4. **Documented blind spots.** What does this method fail to see? Where
   does it need to hand off to another agent?
5. **Routing triggers.** What problem shapes activate this agent? (Goes
   into `agents/genius/INDEX.md`.)

An agent definition that says "be like Einstein" without these five
sections does not pass review. The standard is **Einstein's method, not
Einstein's persona**.

Test the new agent's routing by spawning it on a problem matching its
trigger pattern. Verify it cites sources, surfaces blind spots, and
declares what it could not verify.

---

## Adding a skill (slash command)

Skills are multi-step pipelines composed of agent calls. Each skill must:

1. Have a frontmatter `name`, `description`, `allowed-tools`, and optional
   `argument-hint`.
2. Be a *procedure*, not a single prompt. Step 1, Step 2, ..., with named
   intermediate artifacts.
3. Surface what the procedure could not verify in its own output.
4. Refuse to ship if a step fails (e.g., a required citation is missing).

Look at `commands/incident-investigation.md` and `commands/deep-research.md`
for reference patterns.

---

## Modifying a hook

Hooks (`hooks/*.sh`) fire on Claude Code lifecycle events. Two rules:

1. **Hooks must be idempotent.** Re-running the same hook on the same input
   produces the same result.
2. **Hooks must not silently mutate.** If a hook changes anything (commit
   message, staged files, config), it logs what it changed and why.

The pre-commit-zetetic hook is the most critical: it runs `tools/zetetic-checker.sh
--staged` and blocks the commit if violations are found. Changes to that
hook need a corresponding test in `tests/`.

---

## Coding standards (excerpt)

Full text in [`rules/coding-standards.md`](rules/coding-standards.md). Key load-bearing rules:

- **§8 Source discipline.** Every numeric constant ≥3 significant digits
  in code files requires a `# source:` annotation (citation, benchmark,
  measured, or "provisional heuristic"). The pre-commit hook enforces
  this at commit time.
- **§9 No `// TODO`** without an issue reference. The hook blocks ticket-less
  TODOs at `ZETETIC_PROFILE=strict`.
- **No absolute claims.** Words like "always", "never", "obviously", "clearly"
  in comments require sourcing. The hook flags `UNSOURCED` keywords.
- **Refusal conditions are first-class.** Every agent's body documents
  conditions under which it refuses. These are intent statements; the
  hook does not enforce them at runtime, but reviewers do at code review.

---

## Testing

```bash
bash tests/run-all.sh          # full suite
bash tests/test-functional.sh  # agent invocation paths
bash tests/test-acl.sh         # memory-tool ACL boundaries
bash tests/test-concurrency.sh # stale-lock + concurrent-write
bash tests/test-pii.sh         # secret-shield hook coverage
```

Tests are bash-driven and require no network access. A failing test
must be fixed before merge.

---

## What NOT to do

- Don't add an agent without a primary academic citation in its body.
- Don't paper over a hook failure with `--no-verify`. If the hook is
  wrong, fix the hook in the same PR.
- Don't claim a constant is "from research" without naming the paper.
  `# source:` is enforced; "trust me" is not.
- Don't ship a skill that has no documented refusal condition.

---

## Code of Conduct

This project follows [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Same
standard applies to issues, PRs, and review discussion as to the agents'
own outputs: cite, disagree on merits, and acknowledge what you can't
verify.

---

## Reporting security issues

See [`SECURITY.md`](SECURITY.md). The `pre-tool-secret-shield` hook is
load-bearing — security-sensitive changes to it warrant private
disclosure first.

---

## License

MIT. Contributions are licensed under the same. See [`LICENSE`](LICENSE).
The reasoning patterns themselves remain attributable to the cited
academic sources; the MIT license covers their encoding as agents and
tooling.
