# Security Policy

## What this plugin installs and executes

Installing the full Claude Code plugin grants **session-execution rights**.
Its executable source runs with your permissions. There is no sandbox between
a modified executable file and your machine:

- **`hooks/`** run automatically on Claude Code session-lifecycle events
  (session start/end, pre/post tool use, pre-commit, pre-push). A modified hook
  is a shell or python script that runs on your next session start.
- **`tools/*.sh` and `tools/*.py`** run as part of pre-commit and pre-push
  gates (the zetetic checker, redaction checker, craftsmanship checker,
  mutation gates).
- **`agents/`** define what your assistant is permitted to do.

This is the ecosystem's shortest path from a compromised artifact to code
execution, because the payload does not even need to be compiled. That is the
threat model the assurance below is built for.

The isolated `plugins/zetetic-reasoning` package for Codex and Gemini CLI has a
narrower trust boundary. It contains declarative manifests, one Markdown skill
and Markdown references; it registers no repository executable or server. The
host may still act on its instructions, so review the source and repository
commit before installation. The portable-package contract test mechanically
checks this static boundary.

The full assurance case is [`docs/ASSURANCE-CASE.md`](docs/ASSURANCE-CASE.md):
the threat model with its adversaries, the five trust boundaries this project
has, the argument that secure design principles were applied, and the argument
that common implementation weaknesses are countered. Every claim there carries
its limit, including the boundaries where a control is weaker than it looks.

## Supply-chain assurance

As of issue #53, every release (`.github/workflows/release.yml`) builds and
attests a bundle of exactly what it delivers:

- **Signed provenance.** The release bundle
  (`zetetic-team-subagents.tar.gz`), its executable-content manifest and its
  SBOM each carry a Sigstore-backed build-provenance attestation. Because this
  is a source-only plugin there is no binary to sign, so signed releases and
  tags over the bundle are the achievable attestation. Verify a download:

  ```bash
  gh attestation verify zetetic-team-subagents.tar.gz --repo cdeust/zetetic-team-subagents
  ```

- **Enumerate what you grant.** `EXECUTABLE-MANIFEST.sha256` lists every
  `hooks/*` and `tools/*.sh|*.py` that will run on your machine, with its
  SHA-256. You can diff it against the previous release to see exactly which
  session-executing files changed.

- **Verify before it runs.** `tools/verify-release-bundle.sh` checks the
  bundle's checksum **before unpacking** and every executable against the
  manifest **before execution**, rejecting a tampered bundle. Attestation
  nobody checks changes nothing; this is the check.

  ```bash
  tools/verify-release-bundle.sh zetetic-team-subagents.tar.gz \
    zetetic-team-subagents.tar.gz.sha256 EXECUTABLE-MANIFEST.sha256
  ```

- **SBOM.** `zetetic-team-subagents.cdx.json` (CycloneDX) inventories every
  bundled file with its hash, including vendored third-party skill material and
  the isolated portable package.

- **Continuous analysis.** shellcheck over `hooks/` and `tools/`
  (`shellcheck.yml`, error-severity hard gate), CodeQL for the python
  hooks/tools (`codeql.yml`), and OpenSSF Scorecard (`scorecard.yml`), all on a
  schedule. The Scorecard number is a recorded baseline, not a badge.

**Relationship to #52.** #52 answers "am I running the version I think I am?"
(visibility); this answers "is the artifact I am running the one that was
published?" (integrity). Both are required.

**What this does NOT claim.** Provenance proves *who built the bundle and from
which commit*, not that the scripts are free of defects; and it is worth
nothing to a user who does not run the verification. The marketplace install
path consumes the git tree directly, so its integrity is the tagged commit plus
its attestation.

## Reporting a Vulnerability

If you discover a security issue in this project, **do not** open a public
issue. Instead, send a private report to the maintainer.

**Disclosure channel:** open a [private security advisory on GitHub](https://github.com/cdeust/zetetic-team-subagents/security/advisories/new).

Include:

- Affected version (or commit SHA)
- Reproduction steps or proof of concept
- Impact assessment (what does an exploit accomplish?)
- Suggested fix, if you have one

## Response SLA

| Severity | First response | Patch / mitigation |
|---|---|---|
| Critical (RCE, data exfiltration, auth bypass) | 24 hours | 7 days |
| High | 3 days | 14 days |
| Medium / Low | 7 days | Best effort |

## Supported Versions

Only the latest minor release on `main` receives security patches.

## Disclosure Timeline

1. Reporter sends private advisory.
2. Maintainer acknowledges receipt within the first-response SLA.
3. Maintainer + reporter agree on a coordinated disclosure date (default
   30 days from the patched release).
4. Patched release ships; reporter is credited unless they prefer
   anonymity.
5. Public advisory published on the agreed date.

## Out of Scope

- Vulnerabilities in third-party dependencies that have not been patched
  upstream: please report those upstream first.
- Issues that require an attacker to already have control of the host
  process (in-process supply-chain attacks).
- Self-inflicted misconfigurations of your own MCP server registration.

## Recognition

Reporters who follow this disclosure process are credited in the release
notes for the patched version, unless they explicitly request anonymity.
