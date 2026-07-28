# Governance

How decisions get made here, who makes them, and what happens if that person
stops. Written to be refutable: every claim below is either checkable in this
repository or is a statement about a single person's access, marked as such.

This is a **single-maintainer project**. Saying so plainly is the point of this
document. A governance page that describes committees this project does not have
would be worse than none.

---

## Decision model

**Who merges.** The maintainer, and only the maintainer. There is no second
account with write access to `main`.

**What a change needs to land.** Two things, in this order:

1. **Every CI gate green on the exact pushed tree.** The gates are hard, not
   advisory: agent-definition auditor, craftsmanship checker on newly-added
   files, redaction sweep, documented-commands check, documented-counts check,
   the tools regression suites, the memory and worktree suites, shellcheck at
   error and warning severity, and CodeQL. A red gate is not overridable by
   opinion; the fix is to fix the change.
2. **A completion ledger in the pull request**, per
   [`rules/coding-standards.md`](rules/coding-standards.md) §13: every code path
   the diff introduces mapped to the test or command that proves it. A PR whose
   ledger is missing or incomplete is refused rather than reviewed.

**Why there is no second-reviewer requirement.** GitHub does not permit
self-approval, so requiring reviews on a single-maintainer repository would
deadlock every merge. That trade-off, and what would change if a second
maintainer joined, is documented in
[`docs/SCORECARD.md`](docs/SCORECARD.md#codereviewid-declined). The gates carry
the load that a second reviewer would otherwise carry. This is a weaker
guarantee than human review, and it is stated as weaker rather than presented as
equivalent.

**How disagreements resolve.** Technical disagreement is settled on evidence, in
the open, in the issue or PR thread: the standard the agents enforce on user
code is the standard the project applies to itself, so a position is expected to
name its source, its measurement, or its reproduction. Where evidence does not
settle it, the maintainer decides and records the reasoning in the thread or in
an ADR under the wiki. A decision made without a stated reason is a defect in
the decision, not a prerogative.

**What is not decided unilaterally.** Nothing, currently. That is a description
of the project's size, not an assertion that it is desirable.

---

## Roles and responsibilities

| Role | Holder | Responsibilities |
|---|---|---|
| Maintainer | Clement Deust ([@cdeust](https://github.com/cdeust)), `admin@ai-architect.tools` | Triages and closes issues, reviews and merges pull requests, cuts releases, owns the security disclosure channel and the response SLA in [`SECURITY.md`](SECURITY.md), enforces [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md), and sets the roadmap in [`docs/ROADMAP.md`](docs/ROADMAP.md). |
| Contributor | Anyone who opens an issue or pull request | Follows [`CONTRIBUTING.md`](CONTRIBUTING.md), holds their change to [`rules/coding-standards.md`](rules/coding-standards.md), and supplies the completion ledger. Contributors hold no repository permissions. |
| Security reporter | Anyone reporting privately | Uses the channel in [`SECURITY.md`](SECURITY.md). Reports are acknowledged on the published SLA and credited in the release notes for the patched version unless anonymity is requested. |

**The bus factor is 1.** Every role above that requires a permission is held by
one person. This is recorded the same way in
[`.bestpractices.json`](.bestpractices.json) and
[`docs/SCORECARD.md`](docs/SCORECARD.md) rather than being softened in one place
and admitted in another.

---

## Continuity of access

The honest answer, split into what survives the maintainer becoming unavailable
and what does not.

### What survives, with no action by anyone

- **The source.** MIT licensed, public, and complete: the plugin is Markdown
  definitions plus bash and Python that run directly from source. There is no
  build step and no private component, so a fork is a working copy on the first
  clone, not a partial one.
- **The history.** Every release is a git tag on a public repository. Anyone can
  fork the full history without asking permission.
- **The verifiability of past releases.** Each release bundle carries a SHA-256
  companion and a Sigstore build-provenance attestation bound to this
  repository's workflow identity. Those remain verifiable with
  `gh attestation verify` after the maintainer is gone, because the trust anchor
  is Sigstore's public transparency log, not a key held by one person.
- **The standard.** [`rules/coding-standards.md`](rules/coding-standards.md) and
  the gates that enforce it are in the tree. A fork inherits a working quality
  bar rather than a description of one.

### What stops, because it is single-owner

Stated in the terms the OpenSSF `access_continuity` criterion asks about
(creating and closing issues, accepting changes, publishing releases within a
week):

| Capability | Status if the maintainer is unavailable |
|---|---|
| Creating and closing issues on this repository | **Stops.** Anyone can open an issue; nobody else can triage, label or close one. |
| Accepting changes into `main` | **Stops.** One account holds write access. Pull requests would accumulate unmerged. |
| Publishing a release | **Stops.** The release workflow signs through the OIDC identity of this repository, which only a push by the maintainer initiates. |
| The marketplace entry | **Stops.** `claude plugin marketplace add cdeust/zetetic-team-subagents` resolves to a single-owner namespace. Existing installs keep working; updates stop. |
| The `ai-architect.tools` domain in the maintainer address | **Stops.** Single-owner registration, so `admin@ai-architect.tools` would eventually stop resolving, including as a conduct and security reporting channel. |

**There is no succession arrangement.** No second person holds credentials, and
no handover is escrowed. The recovery path available to users is to fork and
continue, which the MIT license, the public history and the Sigstore-anchored
attestations make genuinely available. That is a real continuity property and it
is a weaker one than a second maintainer, so it is written down as what it is
rather than argued into sufficiency.

**What would change this.** A second maintainer with write access. That single
change would satisfy this section on substance, and would simultaneously make
the OpenSSF `bus_factor`, `two_person_review` and `contributors_unassociated`
criteria and the Scorecard `Code-Review` and `Branch-Protection` checks
reachable, all of which are currently blocked by the same fact. It is listed in
[`docs/ROADMAP.md`](docs/ROADMAP.md) as a stated intent, not as a commitment
with a date, because it depends on someone else's willingness rather than on
the maintainer's effort.

---

## Changing this document

By pull request, like anything else. Changes to the decision model or to the
continuity statement should say what became true, since the value of this page
is that it describes the project as it actually is on the day it is read.
