# Roadmap

What this project intends to do, and what it intends not to do, over the twelve
months from **2026-07-28 to 2027-07-28**.

Written so that a reader can tell later whether it happened. Every item names
the artifact that would exist, or the number that would move, if it did. Items
without that are opinions, not plans, and are not listed.

This is a single-maintainer project, so this page is one person's intent. It
carries no delivery dates, because a date nobody is accountable to is
decoration. It is revised when something lands or when an intent changes, and
the change says which.

---

## What this project will do

### 1. Finish OpenSSF silver, then start on gold's prerequisites

Silver is the near-term target and most of it is already answered in
[`.bestpractices.json`](../.bestpractices.json). The remaining work is
enumerated there rather than here, because that file is the one a machine reads.

**Done when:** every silver criterion in `.bestpractices.json` reads `Met` or
`N/A` with a justification that points at a URL or quotes a command, and the
badge at [bestpractices.dev/projects/13847](https://www.bestpractices.dev/projects/13847)
shows silver.

Then the criteria that silver does not require but that are unmet and fixable:

| Criterion | What has to change |
|---|---|
| `crypto_used_network` | `tools/web_ingest.py` accepts a caller-supplied URL without restricting the scheme. Needs an https allowlist applied at that boundary and re-applied after each redirect hop, with plain HTTP available only behind an explicit opt-in. |
| `input_validation` | The same boundary. Validation is present nearly everywhere and wrong in shape at exactly one place. |
| `version_tags_signed` | Release tags are annotated but unsigned; `git tag -v` reports no signature. The artifacts are already Sigstore-attested, so this adds a second independent anchor. |
| `dynamic_analysis` | No tool that varies its own inputs is applied. The checkers and the PII classifier are the natural targets: both consume adversarial text and both are currently tested against fixed fixtures. |

**Gold is not promised in this window.** Its three blockers (`bus_factor`,
`two_person_review`, `contributors_unassociated`) all reduce to one fact: there
is one maintainer. A second maintainer is a stated intent, not a deliverable,
because it depends on another person's willingness. If it happens, required
reviews and branch protection get enabled in the same week and
[`docs/SCORECARD.md`](SCORECARD.md) is updated to say so.

### 2. Get Python coverage to the 80% gate, hold it, then measure strength by mutation

Statement coverage over the shipped Python surface (`hooks/` plus `tools/`) is
measured at 30% today, and the pytest suite does not run in CI at all, so a
change that breaks its 334 tests lands green (issue #71). First get pytest into
CI as a hard gate with `coverage.py` at `fail_under = 80` over that surface;
then keep it there as the surface grows; then stop treating coverage as the
measure of a suite's strength, because a high-coverage suite that kills no
mutants tests nothing.

**Done when:**

- The pytest suite runs in CI on push and pull request as a hard gate, and
  `coverage.py` fails the build below 80% over `hooks/` plus `tools/`, with the
  source set and every exclusion declared in `pyproject.toml`.

- Mutation testing runs per-commit on changed Python via
  `tools/mutation_check.sh`, blocking, with zero surviving non-equivalent
  mutants on changed lines (`rules/coding-standards.md` §12.5, tier 1).
- The critical-zone sweep (`tools/mutation-sweep.sh`) runs on a schedule and
  reports per zone, non-blocking, with at least one zone ratcheted from backlog
  to clean and its survivors triaged with written evidence.
- The cross-backend discipline of §12.3 has a regression test: the incident that
  motivated it (a handler returning `numpy.float32` that passed on SQLite and
  failed on PostgreSQL) is pinned by a test that asserts the backend-agnostic
  contract rather than one backend's representative shape.

### 3. Close the autonomous build loop on a repository that is not this one

The `autonomous-build-loop` skill drafts and iterates a candidate on an isolated
branch under acceptance checks, and it already runs against an arbitrary target
repository. What it does not yet have is a recorded end-to-end proof.

**Done when:** a documented run exists in which the loop takes a non-trivial
task on a target repository that does not contain this tooling, converges a
candidate under its gate runner, and a human or CI re-runs that gate runner
outside the loop and reads a real exit code before merging. The write-up names
the task, the repository, the number of iterations, and what the external gate
said.

**The external gate stays authoritative and outside the loop.** Making the loop
self-certifying is explicitly not a goal; see the next section.

### 4. Grow the agent and skill roster without letting its own numbers rot

New sourced reasoning patterns and problem-shaped skills, each meeting the
existing bar: a primary citation in the body, documented refusal conditions, and
a pass from the structural auditor.

**Done when:** each addition ships with its citation and its `docs/COUNTING.md`
numbers regenerated, with `tools/doc-count-check.sh` green. The gate makes this
automatic rather than aspirational: an agent added without updating the counts
turns CI red.

Grooming counts as roster work. `memory/scope-coverage.md` and the wiki carry
entries that have drifted from the tree, and the same measure-it-or-it-rots
treatment applies.

---

## What this project will not do

Each of these is a decision, not a backlog item. If one changes, this section
changes first and says why.

### Sandbox agent execution, or enforce refusal conditions at runtime

Everything this plugin ships executes in the user's own session with the user's
own permissions, and there is no sandbox between a modified file and the
machine. An agent's documented refusal conditions are prompt-level intent, not a
runtime guarantee: an agent can name a blind spot in its own description and
exhibit it anyway.

This will not change in this window. Building a sandbox is not a plugin-shaped
problem, and claiming enforcement the code does not provide would be exactly the
overclaiming the whole project exists to gate against. The limit is already
stated in [`README.md`](../README.md) and [`SECURITY.md`](../SECURITY.md) and
will keep being stated.

### Support hosts other than Claude Code

The hook lifecycle this depends on is Claude Code's: hooks fire inside its
invocation path, and direct terminal commits, CI scripts and other editors
bypass them. Porting to another IDE, CLI or agent runtime would mean either
reimplementing that lifecycle or shipping a version whose gates silently do not
fire, and a gate that silently does not fire is worse than no gate.

### Run a hosted service, collect telemetry, or hold user accounts

No server, no SaaS, no analytics, no accounts, no phoning home. The project
performs no inbound authentication and stores no credentials, which is why a
whole class of OpenSSF criteria is `N/A` rather than argued. Adding any of them
would turn an offline local plugin into something with a threat model it does
not currently have.

### Localize the interface

Checker findings, hook notices, setup output and the agent and skill prose stay
English. `internationalization` is reported unmet in `.bestpractices.json`
rather than claimed, and this section is why: it is a decision about scope, not
an oversight waiting to be corrected.

---

## How this page stays honest

It is linked from [`README.md`](../README.md), and the commands and files it
names are covered by `tools/doc-command-check.sh`, so a pointer that goes stale
fails the build.

The dates at the top are the window this revision describes. A reader arriving
after 2027-07-28 should treat an unrevised page as evidence that the roadmap was
not maintained, which is itself information.
