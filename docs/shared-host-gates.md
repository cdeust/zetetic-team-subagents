# Shared Claude Code and Codex gates

## Decision and scope

The full plugin and standalone zetetic-gates share a gate entry point, policy,
and checker implementation. User-level installation makes the gates available
across projects. Codex still requires review and trust of new or changed hook
definitions; installation does not grant trust automatically.

`scripts/sync-gates.py` copies the canonical runtime closure under hooks/, tools/
and rules/ into the standalone package. Tests reject drift. The full Claude
manifest is checked against hooks/hooks.json so the actual loader stays wired.

| Event | Control |
| --- | --- |
| SessionStart | Shared policy and path to detailed coding standards. |
| PreToolUse | Secret reads, source/layer edit hints, removed definitions, commit/push source and structural checks, outbound prose. |
| PostToolUse | Removed definitions in the affected repository after shell or file operations. |
| Stop / SubagentStop | Returned prose; findings request a rewrite. |

Source checking defaults to strict at the shared entry point; repository
configuration remains authoritative. Craftsmanship retains configured limits
and severities. Prose hooks receive blocking mode automatically. Existing Stop
continuation-loop protection remains in effect.

Edit hints are advisory. Commit checks enforce mechanical rules. Neither a
source marker nor a prose scan establishes scientific validity or authorship;
project tests, source review and editorial judgment remain required.

## Host adaptation

Claude Edit/Write fields and Codex apply_patch become per-file events before
checking. Reconstruction happens in memory. Ambiguous or unsupported patches
are refused instead of silently approved. Post-tool checks inspect the affected
repositories without reconstructing preimages after modification.

Shell aliases and workdir fields normalize to Bash. Git -C and simple cd lists
identify commit targets; affected paths identify post-edit roots. Quoted Git
commands are tokenized before dispatch, and argument text is not treated as a
commit command. Explicit unsupported Git repository selectors are refused. This is not
a shell interpreter. Opaque scripts, dynamic shell construction and human
commits need native Git hooks for enforcement independent of the assistant.
Post-tool checks can detect a completed removal but cannot undo it.

Structural and staged-prose checks read frozen index blobs and indexed policy
files. An unstaged clean replacement cannot hide a staged violation. Symlinks
are not dereferenced and policy symlinks are rejected. The live checkout and
index remain unchanged.

## Codex installation

After this version reaches the repository marketplace:

```sh
codex plugin marketplace add cdeust/zetetic-team-subagents
codex plugin add zetetic-gates@zetetic-marketplace
```

Alternatively install zetetic-team-subagents from that marketplace. Choose one
package: hooks from installed sources are additive. The full Codex package
exposes the shared gates and portable reasoning skills. It does not claim to
port every Claude agent or research lifecycle hook. Claude agents are preserved.

Open `/hooks` in a new Codex session and review the commands before trusting
them. A stored hash for an old plugin does not prove it is loaded today. The
loose file ~/.codex/hooks/hooks.json is not a standard user-level hook source.

## Verification

Tests exercise real checker processes in disposable consumer repositories and
a detached standalone package. Both clean and violating inputs are required:
source/craftsmanship, secret reads, outbound/returned prose, host edit parity,
malformed patches, alternate repositories, and index/worktree disagreement.
The native Codex CLI also accepts the local package and reports it installed
and enabled. Host-level execution after trust is a separate acceptance step.

The bundled older OpenAI validator rejects a hooks manifest field now supported
by the official runtime documentation. Native CLI installation is the packaging
check for this change; the old validator result is not reported as passing.

## Sources

- [Codex hooks](https://developers.openai.com/codex/hooks): event schema, aliases,
  discovery, blocking outputs and trust.
- [Plugin packaging](https://developers.openai.com/plugins/build/plugins):
  supported manifests, including .codex-plugin compatibility.
- rules/coding-standards.md, skills/writing/redaction.md and existing checker
  tests supply policy semantics. No new scientific threshold is introduced.
