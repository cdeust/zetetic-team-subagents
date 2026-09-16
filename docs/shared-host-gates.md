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

Source checking keeps the checker's standard default. Declare
`ZETETIC_PROFILE=strict` in `.zetetic.conf` to make source warnings blocking.
The shared entry point does not inject a strict profile. Staged prose follows
the declared profile, replacing the old hook's unconditional warning mode.
Craftsmanship retains configured limits and severities.

Two blocking-policy changes are deliberate: checker execution/configuration
errors refuse commit/push because validation did not complete; returned and
outbound prose hooks receive blocking mode automatically. The latter replaces
the legacy opt-in behavior for calls through the shared entry point, including
when `REDACTION_STOP_BLOCK=off` is inherited. Standalone legacy hook invocation
retains its opt-in contract. Stop continuation-loop protection remains in effect.

Commit and push retain their actual verbs during dispatch. Both run staged
checks, as the previous full-plugin hook already did. These checks do not prove
that the commits being pushed passed validation. Existing Claude push-specific
review and provenance hooks remain separate.

Unchanged Claude hooks retain their previous explicit timeouts. Shared hooks
use the host's default timeout; that default is host-dependent. Tool matchers
limit pre-tool execution to supported secret/edit/shell and MCP actions, and
post-tool execution to supported file/shell actions.

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
commit command. Explicit unsupported Git repository selectors are refused only
for commit/push. Other verbs pass without guessing a selected repository. This is not
a shell interpreter. Opaque scripts, dynamic shell construction and human
commits need native Git hooks for enforcement independent of the assistant.
Post-tool checks can detect a completed removal but cannot undo it. Malformed
shell quoting leaves post-tool inspection at the known event directory rather
than raising a parsing error or guessing additional targets.

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
