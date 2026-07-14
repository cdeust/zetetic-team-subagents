# dev-symlink-doctor regression suite

Covers the version-bridge mechanism added to `tools/dev-symlink-doctor.sh`
(incident 2026-07-14: a plugin auto-update purges the old version directory
under `~/.claude/plugins/cache/<mp>/<plugin>/<version>`, breaking every hook
invocation from an in-flight session whose `CLAUDE_PLUGIN_ROOT` still points
at the purged path).

Fixtures are synthetic and self-contained under a `mktemp -d` tree; the
suite never touches `~/.claude/dev-symlink.map`, `~/.claude/dev-symlink.versions`,
or any real plugin cache — every invocation overrides `DEV_SYMLINK_MAP` and
`DEV_SYMLINK_VERSIONS`.

Assertions:
- A purged version directory with a prior state-file record gets a symlink
  bridge to the current version (root-cause incident reproduction).
- A real (non-symlink) directory at an old-version path is NEVER touched,
  even when the state file lists that version as historical.
- A stale bridge (pointing at a version that was itself later replaced) is
  re-pointed at the new current version.
- `prune-bridges` removes bridge symlinks and forgets the corresponding
  version(s) from the state file, so a subsequent run does not silently
  recreate what was just retired.
- Pre-existing check/repair behavior (OK / BROKEN / repaired reporting,
  exit codes) is unchanged — non-regression on the original montage-doctor
  contract.
