# Assurance case

Why this project's security requirements are met, and precisely where they are
not. Four parts, in the order the OpenSSF `assurance_case` criterion asks for:
the threat model, the trust boundaries, the argument that secure design
principles were applied, and the argument that common implementation weaknesses
were countered.

Every claim below carries its limit, in the style
[`SECURITY.md`](../SECURITY.md) already uses for its "What this does NOT claim"
paragraph. A claim without a stated limit is a claim nobody has thought about
hard enough, and this project gates user code on exactly that principle.

---

## Part 1: Threat model

### What an attacker gains

Installing the full Claude Code plugin grants **session-execution rights**.
Its hooks and tools run with the user's own permissions, and there is no sandbox
between a modified executable file and the machine. `hooks/` run automatically
on session lifecycle events; `tools/*.sh` and `tools/*.py` run inside pre-commit
and pre-push gates; `agents/` define what the assistant is permitted to do.

The isolated `plugins/zetetic-reasoning` package for Codex and Gemini CLI has a
smaller boundary: it contains declarative manifests, one Markdown skill and
Markdown references. It declares no executable component or server. Its host
can still act on the skill's instructions, so source integrity and prompt
content remain trust concerns, but installing that package does not register
this repository's lifecycle code.

This is the ecosystem's shortest path from a compromised artifact to code
execution, because **the payload does not need to be compiled**. A one-line edit
to a hook is a working exploit on the victim's next session start.

### Who the adversaries are, and what each can reach

| Adversary | Capability assumed | What they are trying to reach |
|---|---|---|
| Supply-chain attacker | Can publish or tamper with a release artifact, or compromise the repository | Arbitrary code execution on every installing machine, at session start, with no user action beyond installing |
| Malicious or confused model output | Can choose tool names and tool arguments within a session | Reading credential files, writing outside its permitted memory scope, exfiltrating repository contents through a tool call |
| Hostile fetched content | Controls the bytes returned by a URL the user asked to ingest | Resource exhaustion, and content that later reaches the model as if it were trusted context |
| Curious local process | Can read files the user can read | Anything the plugin writes to disk, including memory contents |

### What is explicitly out of the model

- **An attacker who already controls the host process.** In-process
  supply-chain attacks are out of scope, as stated in `SECURITY.md`. Once
  arbitrary code runs in the session, no in-session mechanism this project ships
  is a control.
- **The user acting against themselves.** A user who runs `--no-verify`,
  disables a gate, or sets `MEMORY_NO_ACL=1` has made a decision, not
  encountered a vulnerability.
- **Third-party dependency vulnerabilities not yet patched upstream.**

### Limit of this part

The adversary capabilities above are asserted from the architecture, not derived
from an incident history: no vulnerability has been reported against this
project through the disclosure channel, so this model has never been corrected
by a real attack. It should be read as a design-time hypothesis.

---

## Part 2: Trust boundaries

Five places where data or control crosses from something less trusted into
something more trusted. Each names what crosses, what checks it, and what that
check does not cover.

### 2.1 Release bundle to install path

**Crossing:** a downloaded tarball becomes executable content on the machine.

**Control:** every release builds an attested bundle. The tarball, its
executable-content manifest and its SBOM each carry a Sigstore build-provenance
attestation, verifiable with
`gh attestation verify zetetic-team-subagents.tar.gz --repo cdeust/zetetic-team-subagents`.
`EXECUTABLE-MANIFEST.sha256` enumerates every `hooks/*` and `tools/*.sh|*.py`
that will run, with its SHA-256, so two releases can be diffed for exactly which
session-executing files changed. `tools/verify-release-bundle.sh` checks the
bundle checksum **before unpacking** and every executable against the manifest
**before execution**. The release workflow self-verifies with that same script
before publishing, so the verifier is exercised on the path it guards.

**Limit:** provenance proves who built the bundle and from which commit, not
that the scripts are free of defects. It is worth nothing to a user who never
runs the verification, and the verification is not automatic.

### 2.2 Marketplace installs

**Crossing:** `claude plugin install` copies agents, skills, hooks and tools into
the host's plugin directory, from which they execute.

**Control:** this path consumes the git tree directly rather than the release
bundle, so its integrity anchor is the tagged commit and that tag's attestation,
not the manifest above.

**Limit:** this is the weaker of the two install paths and is stated as such.
Release tags are annotated but **not cryptographically signed** (`git tag -v`
reports no signature), so a user installing from the marketplace has no
per-file manifest to verify and no signed tag to check. Closing this is a
roadmap item (`version_tags_signed` in [`ROADMAP.md`](ROADMAP.md)). Until then,
the honest statement is that marketplace installs rest on GitHub account
security.

The Codex marketplace and Gemini CLI install paths select only
`plugins/zetetic-reasoning`. Their integrity anchor is likewise the repository
commit, but their payload is static skill content and carries no executable
entry point. The contract test rejects host-specific runtime declarations from
that package. This does not prove the instructions are correct; it proves the
declared package boundary is static and reviewable.

### 2.3 Hook invocation from the Claude Code lifecycle

**Crossing:** the host serialises a session event to JSON and pipes it to a hook
on stdin. The hook's exit code can block the user's action.

**Control:** 19 registrations in `hooks/hooks.json`. Hooks bound their stdin
reads and treat the event as untrusted input: a malformed payload, a
non-object JSON document, or an unreadable stdin returns exit 0 rather than
blocking or raising.

**Limit, and it is a real one:** `hooks/pre-tool-secret-shield.py` is
deliberately **fail-open** on input failure. If stdin is unreadable or the JSON
does not parse, it returns 0 and the tool call proceeds unshielded. That choice
is documented at the function and is the correct trade-off for a hook that would
otherwise brick every session on a host-format change, but it means the shield
is not a control against an adversary who can corrupt the event stream. The
opposite choice was made for the pre-commit gates, which fail closed. The two
are inconsistent on purpose, because blocking a commit is recoverable and
bricking every session is not.

Hooks fire only inside Claude Code's invocation path. Direct terminal commits,
CI scripts and other editors bypass every hook this project ships.

### 2.4 Tool invocation with model-supplied arguments

**Crossing:** the model chooses a tool name and its arguments. Those arguments
reach the filesystem and the shell.

**Control:** `hooks/pre-tool-secret-shield.py` denies reads of credential-bearing
paths the agent can never legitimately need: `.env` (with a negative lookahead
exempting only `.example`, `.sample`, `.template`, `.dist`), `.aws/credentials`,
`.netrc`, `.git-credentials`, `.ssh/*`, `.gnupg/*`, `*.pem|p12|pfx|jks`, private
keys, and registry authentication files. Matching is anchored to path segments
and pairs the path with a set of read verbs, rather than a blind substring test,
so `cat` of a key file is blocked while a file merely mentioning the word is
not.

**Limit:** it is a **denylist**, so a credential shape not on the list passes.
It is also a coarse control on argument *content*: it recognises paths, not
intent. The enforced list is the one in the file, which is the honest statement
of coverage. This document's own drafting tripped the shield twice on prose
containing a denylisted word, which is the false-positive cost of anchoring on
path shape.

### 2.5 Memory scope ACL

**Crossing:** an agent reads and writes `/memories/<scope>/<file>`, and scopes
belong to different agents.

**Control:** every access is checked against a registry (`acl_check` in
`tools/memory-tool.sh`) that resolves the calling `MEMORY_AGENT_ID` against a
scope's owners, readers and curator agents. Enforcement is exercised by
dedicated suites for ACL boundaries, concurrency, stale locks and PII.

**Limit, stated plainly:** the ACL is **permissive by default in two ways**.
With no registry file present it returns `allow` for first-run convenience, and
`MEMORY_NO_ACL` bypasses it entirely. Unknown scopes fall back to defaults
unless `strict_unknown_scope` is set. So the ACL is a control over a *configured*
deployment, not an invariant of the code. It is a separation mechanism between
cooperating agents, and it is not a security boundary against an agent that can
set its own environment, because `MEMORY_AGENT_ID` is self-asserted.

---

## Part 3: Secure design principles were applied

Each principle names where it holds and where it does not.

### Fail closed where failure is recoverable

The gates return non-zero and block: the zetetic checker, the craftsmanship
checker, the redaction sweep, the documented-command and documented-count gates,
the agent-definition auditor. Several go further and treat *finding nothing* as
failure rather than success: the auditor exits 2 when it matches 0 files, and
`tests/run-all.sh` exits 2 when it discovers 0 suites, on the reasoning that an
audit which audits nothing is not a passing audit. This closes the specific
failure mode where a path bug turns a gate into a silent no-op that reports
green.

**Limit:** as noted in 2.3, the secret-shield hook deliberately fails open. The
principle is applied where blocking is recoverable, not everywhere.

### Least privilege on what an agent may read

The shield denies a category of file the agent can never need, rather than
relying on the agent's judgement not to read it. Agent definitions enumerate
their permitted tools explicitly, and an unresolvable tool name is dropped by
the host rather than silently granted.

**Limit:** least privilege here is a denylist over reads, not a capability
system. The plugin cannot restrict what the host ultimately permits.

### Defence in depth on the artifact path

Integrity is checked at three independent points: the attestation binds the
bundle to the building workflow, the checksum is verified before unpacking, and
each executable is verified against the manifest before execution. Compromising
one does not carry the others.

**Limit:** all three are on the release path (2.1). The marketplace path (2.2)
has one anchor, not three.

### Bounded consumption of untrusted input

Every ingress from outside is bounded rather than trusted to terminate: response
bodies are capped at 5 MB, redirect chains at 10 hops (matching urllib's own
default, with the RFC 9110 §15.4 citation at the constant), child-sitemap
fan-out at 10, and hook stdin reads are bounded. The caps are named constants
with sourced justifications, because the same rule this project enforces on user
code applies to its own.

**Limit:** the fetch path does **not** restrict the URL scheme. A caller-supplied
`http://` URL is accepted on the same footing as `https://`, so transport
confidentiality is not enforced at that boundary. This is the project's most
concrete known weakness, is recorded as `crypto_used_network` and
`input_validation` in `.bestpractices.json`, and is a named roadmap item. It is
listed here rather than omitted because an assurance case that only argues its
strengths is advocacy.

### Validate at boundaries, trust internal contracts

Validation sits at the crossings enumerated in Part 2 and not on every internal
call, per `rules/coding-standards.md` §3.2. The memory tool checks every scope
write, `tools/manifest_gate.py` rejects an ungrounded source with a non-zero
exit rather than passing it through, and the hooks bound their stdin.

**Limit:** "trust internal contracts" is only sound where the contracts are
enforced. They are enforced by tests, not by types, in the bash surface.

### No ambient authority the project grants itself

The project operates no server, holds no accounts, stores no user passwords,
generates no security-relevant random values, and selects no cryptographic
algorithm of its own: signing is delegated to Sigstore with short-lived
certificates issued against the workflow's OIDC identity, so there is no
long-lived private key anywhere in this project to steal or rotate.

**Limit:** this is a property of the project's small scope. It is a real
reduction in attack surface and not a control the project engineered.

---

## Part 4: Common implementation weaknesses are countered

| Weakness class | Counter | Limit |
|---|---|---|
| Shell injection and quoting defects | shellcheck over all of `hooks/` and `tools/`, hard-gated at **both error and warning severity**, with the linter pinned to a checksum-verified 0.11.0 so the finding set cannot move under the gate | Static analysis. It does not prove absence, and it has no view into `eval` indirection, which this codebase uses in two documented places |
| Injection and unsafe patterns in Python | CodeQL on every push and pull request | Same limit; CodeQL has no shell support, which is why shellcheck carries that half |
| Credential exposure through agent reads | The path denylist of 2.4, plus a PII corpus scored for false-positive and false-negative rate | Denylist coverage only |
| Secrets committed to the repository | The redaction sweep runs as a hard gate over all reader-facing copy, at zero | Prose-level; it is not a secret scanner over code |
| Tampered artifacts | Attestation, checksum and manifest verification (2.1) | Release path only |
| Unbounded resource consumption | The named caps in Part 3 | Fetch and hook paths; not a general limit |
| Silent no-op gates | Gates that treat an empty match set as failure, and a documented-command gate that fails when a registered pattern matches nothing | Covers the gates that have it; not a repo-wide invariant |
| Untested error paths | `rules/coding-standards.md` §13.1 A3 requires every failure arm to map to a test asserting its observable effect, including the emission of the signal itself | A process control enforced at review, not a mechanical one |
| Weak tests that execute without asserting | Mutation testing wired via `tools/mutation_check.sh`, with the standard set at zero surviving non-equivalent mutants on changed code | Per-commit tier is wired for Python; the wide sweep is report-only by design |
| Dependency drift in CI | GitHub Actions pinned by commit SHA, with Dependabot raising updates | Does not cover tools installed inside a step |
| Unknown posture drift over time | OpenSSF Scorecard on a schedule, with the result recorded and its declined checks explained in [`SCORECARD.md`](SCORECARD.md) rather than presented as a badge | A baseline, not a guarantee |

---

## What this assurance case does not claim

- **It does not claim the code is free of defects.** It claims specific
  mechanisms exist at specific boundaries, each with a stated limit.
- **It does not claim the controls are independent of the user.** The two most
  load-bearing ones, bundle verification and gate enforcement, are skippable by
  the person they protect.
- **It has never been tested by a real attack.** No vulnerability has been
  reported through the disclosure channel, so nothing here has been corrected by
  contact with an adversary.
- **It is written by the same person who wrote the code**, on a project whose
  bus factor is 1 ([`GOVERNANCE.md`](../GOVERNANCE.md)). It has had no
  independent security review. That is the largest limit on this document and it
  belongs at the end rather than buried.

Reports that would refute anything above are welcome through the channel in
[`SECURITY.md`](../SECURITY.md).
