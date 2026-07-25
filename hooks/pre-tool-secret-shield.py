#!/usr/bin/env python3
"""PreToolUse hook — block reads of credential-bearing files & commands.

Reads the Claude Code tool-event JSON from stdin:
    {"tool_name": "Read"|"Bash"|"Grep"|..., "tool_input": {...}}

Exits with code 2 (blocking) when the call would surface credentials,
emitting a one-line reason to stderr that Claude sees. Allows everything
else with exit 0 — so this hook adds zero friction for non-secret paths.

Threat model
------------
The agent must never have any reason to *read* the contents of:
- `.env*` files anywhere in the tree
- shell-credential files (`.aws/credentials`, `.netrc`, `.git-credentials`,
  `gh/hosts.yml`)
- private keys (`*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, `*.p12`, `*.pfx`)
- explicit secret directories (`secrets/`, `secret/`, `vault/`)
- known-bait fixtures (`pii-fixtures/tp-*`)
- shell history (`.bash_history`, `.zsh_history`)
- keychain / keyring files

If you legitimately need to inspect one of these, override per-call via the
permissions allow-list, or relocate the file to a non-matched path.

Why blocking READS is enough
----------------------------
Writing/Editing a credential file (e.g. setting up a fresh `.env`) does not
require reading existing contents — the content the agent writes is from the
prompt, not from the file. So Edit/Write to these paths is allowed but
flagged with a stderr note. The agent is asked to confirm intent.

Tools intercepted: Read, Bash, Grep, Edit, Write, NotebookEdit.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

BLOCKED_PATH_PATTERNS: list[str] = [
    # A real `.env` (or `.env.production`, `.env.local`) holds live secrets and
    # blocks. Committed placeholders `.env.example|sample|template|dist` carry
    # no real secret — the negative lookahead exempts only those suffixes.
    r"(^|/)\.env(\.(?!example$|sample$|template$|dist$)[^/]+)?$",
    r"(^|/)credentials(\.[^/]+)?$",
    r"(^|/)\.aws/credentials$",
    r"(^|/)\.aws/config$",
    r"(^|/)\.netrc$",
    r"(^|/)\.git-credentials$",
    r"(^|/)\.config/gh/hosts\.yml$",
    r"(^|/)\.docker/config\.json$",
    r"(^|/)\.npmrc$",
    r"(^|/)\.pypirc$",
    r"(^|/)\.gem/credentials$",
    r"(^|/)id_(rsa|ed25519|ecdsa|dsa)(\.[^/]+)?$",
    r"(^|/)\.ssh/.*$",
    r"(^|/)\.gnupg/.*$",
    # Unambiguous key/cert *container* formats — always block.
    r"\.(pem|p12|pfx|jks)$",
    # `.key`/`.keystore` are ambiguous (i18n `de.key`, `config.key`,
    # `data.keystore`). Block only inside a credential/PKI location or when
    # the stem itself names a key/cert (server.key, tls.key, private.key).
    r"(^|/)(ssl|tls|certs?|keys?|pki|private|secrets?|vault|\.ssh)/" +
    r"[^/]*\.(key|keystore)$",
    r"(^|/)(server|client|tls|ssl|private|priv|ca|cert|rsa|ed25519|" +
    r"id_[a-z0-9]+)\.(key|keystore)$",
    # Secret/vault *stores* — but not documentation *about* secrets. A
    # `docs/`/`documentation/`/`doc/` ancestor marks prose, not a store.
    r"(^|/)secrets?/(?!.*\.(md|markdown|rst|txt|adoc|html?)$)",
    r"(^|/)vault/(?!.*\.(md|markdown|rst|txt|adoc|html?)$)",
    r"(^|/)pii-fixtures/tp-[^/]*$",
    r"(^|/)tp-known-secrets",
    r"(^|/)\.(bash|zsh|fish)_history$",
    r"(^|/)\.python_history$",
    r"(^|/)\.psql_history$",
    r"(^|/)\.mysql_history$",
    r"(^|/)\.node_repl_history$",
    # The real macOS credential artifact. Bare `keychain`/`keyring` substrings
    # were dropped: they false-blocked source/test/doc files merely named after
    # the concept (keyring_backend.py, test_keychain.py, how-keychain.md).
    r"(^|/)login\.keychain-db$",
]

BLOCKED_PATH_RE = re.compile("|".join(BLOCKED_PATH_PATTERNS), re.IGNORECASE)

# Verbs that *read/consume* a file's contents (a credential SOURCE).
# `cat foo` exfiltrates foo; matching a credential arg here is a true block.
BASH_READ_VERBS = re.compile(
    r"\b(cat|less|more|head|tail|bat|grep|rg|ag|awk|sed|cut|sort|uniq|wc|"
    r"file|base64|xxd|od|strings|jq|yq|"
    r"python3?|node|ruby|perl|sh|bash|zsh|fish|printenv|"
    r"openssl|gpg|ssh-keygen)\b",
    re.IGNORECASE,
)

# Verbs that *relocate or write* a file without surfacing its contents into
# the agent's view. The threat model (see module docstring) is about READING
# credential contents; a local copy/move/write reveals nothing, so neither
# the source nor the destination of these verbs is a hard block. Writing a
# credential file (e.g. seeding a fresh .env) is allowed-with-warning.
BASH_COPY_VERBS = frozenset({"cp", "mv", "tee", "install", "dd"})

# Verbs whose *destination* may be remote (exfiltration channel). The final
# positional is a write destination, but a credential SOURCE argument is
# still a real read+transmit and stays blocked.
BASH_TRANSFER_VERBS = frozenset({"scp", "rsync"})

# All verbs that take a write/transfer destination as their final positional.
BASH_WRITE_VERBS = BASH_COPY_VERBS | BASH_TRANSFER_VERBS

# Network-fetch verbs whose URL arguments are remote locations, not local
# credential paths. A public URL containing the literal segment "/vault/"
# or "secrets/" must not be mistaken for a local credential directory.
BASH_FETCH_VERBS = frozenset({"curl", "wget"})

# Verbs that read a *named* environment variable. `printenv NAME` and the
# leading bare `NAME` tokens of `env NAME` print that variable's value, so a
# sensitive NAME is a credential read. Bare `printenv`/`env` (whole-env dump)
# is covered separately by BASH_ENV_DUMP.
BASH_ENV_READ_VERBS = frozenset({"printenv", "env"})

# Shape of a shell variable-name token (so `env FOO=bar cmd` assignments and
# the command word after them are not mistaken for variable reads).
VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Env-var *dump* commands: enumerate the whole environment. These must sit at
# a command position (start, or after a shell separator) so that a literal
# path ending in ".env" does not trip the bare-`env` alternative.
BASH_ENV_DUMP = re.compile(
    r"(?:^|[;|&]|\b(?:and|or|then|do)\s)\s*"
    r"(printenv|env|export\s+-p|set)\s*(?:[;|&]|$)",
    re.IGNORECASE,
)

# A *sensitive* shell variable name. The name is split on underscores; a
# component must be exactly one of the high-confidence credential words, OR
# the name must end with one of the credential suffixes. Substring matches
# inside a component (APITUDE→API, AUTHOR→AUTH, PASSWORDLESS→PASSWORD,
# PASSTHROUGH→PASS) are rejected. Real cases such as AWS_SECRET_ACCESS_KEY
# (component SECRET + suffix _KEY) and GITHUB_TOKEN (suffix _TOKEN) match.
SENSITIVE_VAR_WORDS = frozenset(
    {"KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "CREDENTIALS",
     "APIKEY", "PRIVKEY"}
)
SENSITIVE_VAR_SUFFIXES = (
    "_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIAL", "_CREDENTIALS",
)

# Captures the variable name printed by `echo`/`printf` so it can be checked
# against SENSITIVE_VAR_WORDS / SENSITIVE_VAR_SUFFIXES instead of a blind
# substring match.
ECHO_VAR_RE = re.compile(
    r"\b(?:echo|printf)\b[^|;&]*?\$\{?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def _is_sensitive_var(name: str) -> bool:
    """True only for high-confidence credential variable names."""
    upper = name.upper()
    if any(upper.endswith(sfx) for sfx in SENSITIVE_VAR_SUFFIXES):
        return True
    return any(part in SENSITIVE_VAR_WORDS for part in upper.split("_"))


BLOCKED_PATTERNS_EMBEDDED = re.compile(
    r"(?<![A-Za-z0-9])("
    # `.env` and real suffixes block; template placeholders are exempted by
    # the negative lookahead (mirrors the BLOCKED_PATH_PATTERNS `.env` rule).
    # The lookahead guards immediately after `.env` so a template suffix
    # cannot fall back to a bare-`.env` match (the suffix group is optional).
    r"\.env(?!\.(?:example|sample|template|dist)(?![A-Za-z0-9]))"
    r"(\.[A-Za-z0-9_-]+)?"
    r"|\.aws/(credentials|config)"
    r"|\.(netrc|git-credentials|npmrc|pypirc)"
    r"|\.config/gh/hosts\.yml"
    r"|\.ssh/[A-Za-z0-9._/-]+"
    r"|\.gnupg/[A-Za-z0-9._/-]+"
    r"|id_(rsa|ed25519|ecdsa|dsa)(\.[A-Za-z0-9]+)?"
    r"|credentials(\.[A-Za-z0-9_-]+)?"
    # Secret/vault stores, but not prose *about* secrets (doc extensions).
    r"|(secrets?|vault)/(?![A-Za-z0-9._/-]*\."
    r"(md|markdown|rst|txt|adoc|html?)(?![A-Za-z0-9]))[A-Za-z0-9._/-]*"
    r"|tp-known-secrets[A-Za-z0-9._-]*"
    r"|\.(bash|zsh|fish|python|psql|mysql|node_repl)_history"
    # Unambiguous key/cert containers.
    r"|[A-Za-z0-9_-]+\.(pem|p12|pfx|jks)"
    # `.key`/`.keystore` only in a PKI/credential dir or with a key-ish stem.
    r"|(ssl|tls|certs?|keys?|pki|private|secrets?|vault)/[^/\s]*"
    r"\.(key|keystore)"
    r"|(server|client|tls|ssl|private|priv|ca|cert|rsa|ed25519)"
    r"\.(key|keystore)"
    r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def is_blocked_path(p: str) -> tuple[bool, str | None]:
    if not p:
        return False, None
    m = BLOCKED_PATH_RE.search(p)
    return (bool(m), m.group(0) if m else None)


def _split_pipeline(cmd: str) -> list[str]:
    """Split a command line into simple commands on shell separators.

    Best-effort: separators inside quotes are tolerated (we err toward more
    segments, never fewer reads escaping inspection). Each segment is then
    classified independently so a write destination in one segment cannot
    suppress a credential read in another.
    """
    return [seg for seg in re.split(r"[;|&\n]+|&&|\|\|", cmd) if seg.strip()]


def _segment_tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _verb_of(tokens: list[str]) -> str | None:
    """The command verb of a segment, skipping leading env-var assignments.

    e.g. `FOO=1 cp a b` -> 'cp'. Returns the bare program name, lowercased.
    """
    for tok in tokens:
        if "=" in tok and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            continue
        return Path(tok.lstrip("@-+")).name.lower()
    return None


def _is_url(arg: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9+.-]*://", arg, re.IGNORECASE))


def _scan_arguments(verb: str, tokens: list[str]) -> tuple[bool, str | None]:
    """Inspect a segment's positional args for a credential SOURCE read.

    - COPY verbs (cp/mv/tee/install/dd): local relocation/write surfaces no
      contents to the agent; neither source nor destination is a block.
    - TRANSFER verbs (scp/rsync): destination may be remote; the source is
      still a read+transmit, so the final positional (destination) is dropped
      and remaining args are scanned as sources.
    - FETCH verbs (curl/wget): URL args are remote and never local credential
      paths, so they are skipped entirely.
    """
    if verb in BASH_COPY_VERBS:
        return False, None
    positional = [t for t in tokens[1:] if not t.startswith("-")]
    if verb in BASH_TRANSFER_VERBS and positional:
        # Last positional is the destination; everything before is a source.
        positional = positional[:-1]
    for arg in positional:
        if verb in BASH_FETCH_VERBS and _is_url(arg):
            continue
        candidate = arg.lstrip("@-+")
        is_b, pattern = is_blocked_path(candidate)
        if is_b:
            return True, (
                f"read of credential-bearing path '{candidate}' "
                f"(pattern '{pattern}')"
            )
    return False, None


def _scan_env_read(tokens: list[str]) -> tuple[bool, str | None]:
    """Inspect `printenv NAME` / `env NAME ...` reads for a sensitive variable.

    Only the leading bare variable-name tokens are reads: `printenv X` and the
    `env X Y` form print those variables. A `NAME=val` assignment configures
    the environment and the first non-assignment, non-name token is the command
    `env` runs (`env FOO=bar somecmd`) — neither is a read, so scanning stops
    at the first token that is not a bare variable name.
    """
    for tok in tokens[1:]:
        if tok.startswith("-"):
            continue
        if not VAR_NAME_RE.match(tok):
            break
        if _is_sensitive_var(tok):
            return True, f"read of sensitive environment variable {tok}"
    return False, None


def bash_blocked(cmd: str) -> tuple[bool, str | None]:
    if not cmd:
        return False, None

    # 1) Whole-environment dump commands (command-positioned so a literal
    #    path ending in ".env" does not trip the bare-`env` alternative).
    if BASH_ENV_DUMP.search(cmd):
        return True, "env-var dump (printenv / env / export -p / set)"

    # 2) `echo`/`printf` of a *sensitive* variable. Names are matched on
    #    underscore components + a suffix allowlist — never blind substring.
    for var in ECHO_VAR_RE.findall(cmd):
        if _is_sensitive_var(var):
            return True, f"echo of sensitive variable ${var}"

    # 3) Per-segment credential SOURCE reads, distinguishing read verbs from
    #    write/copy destinations and skipping curl/wget URLs.
    for segment in _split_pipeline(cmd):
        tokens = _segment_tokens(segment)
        if not tokens:
            continue
        verb = _verb_of(tokens)
        if verb is None:
            continue
        if verb in BASH_ENV_READ_VERBS:
            blocked, reason = _scan_env_read(tokens)
            if blocked:
                return True, reason
        is_read = bool(BASH_READ_VERBS.search(segment))
        is_write = verb in BASH_WRITE_VERBS
        is_fetch = verb in BASH_FETCH_VERBS
        if not (is_read or is_write or is_fetch):
            continue
        blocked, reason = _scan_arguments(verb, tokens)
        if blocked:
            return True, reason

    # 4) Embedded credential path appearing anywhere in a read/copy/fetch
    #    command (catches paths not cleanly tokenized). Write destinations and
    #    fetch URLs are stripped first so they cannot trip a false block.
    scannable = _strip_write_dest_and_urls(cmd)
    m = BLOCKED_PATTERNS_EMBEDDED.search(scannable)
    if m:
        return True, f"credential path embedded in command: '{m.group(0)}'"
    return False, None


def _strip_write_dest_and_urls(cmd: str) -> str:
    """Remove non-source paths before the embedded credential-path scan.

    Keeps read sources intact so the embedded regex sees only exfiltration
    sources, never a legitimate destination or remote URL:
    - COPY verbs (cp/mv/tee/install/dd): drop ALL their path args (local
      relocation/write reveals no contents).
    - TRANSFER verbs (scp/rsync): drop only the final destination.
    - FETCH verbs (curl/wget): drop URL args.
    """
    parts: list[str] = []
    for segment in _split_pipeline(cmd):
        tokens = _segment_tokens(segment)
        verb = _verb_of(tokens) if tokens else None
        if verb in BASH_COPY_VERBS:
            # Keep only the verb token; all path args are non-source.
            parts.append(tokens[0] if tokens else "")
            continue
        kept = list(tokens)
        if verb in BASH_TRANSFER_VERBS:
            kept = _drop_transfer_destination(kept)
        if verb in BASH_FETCH_VERBS:
            kept = [t for t in kept if not _is_url(t)]
        parts.append(" ".join(kept))
    return " ".join(parts)


def _drop_transfer_destination(tokens: list[str]) -> list[str]:
    """Drop the final positional arg (the transfer destination) from tokens.

    scp/rsync read their sources and write their last positional argument;
    only that destination occurrence is removed (rightmost match), so every
    read source stays visible to the embedded credential-path scan.
    """
    positional = [t for t in tokens[1:] if not t.startswith("-")]
    if not positional:
        return tokens
    dest = positional[-1]
    kept = list(tokens)
    for i in range(len(kept) - 1, -1, -1):
        if kept[i] == dest:
            del kept[i]
            break
    return kept


def _field(tin: dict, key: str) -> str:
    """Extract a string field, coercing non-strings to "".

    A non-string value (e.g. a numeric `command`) carries no path/command to
    inspect; returning "" makes the matchers fail open instead of crashing.
    """
    val = tin.get(key, "")
    return val if isinstance(val, str) else ""


def _evaluate(tool: str, tin: dict) -> str | None:
    """Return a block reason for an exfiltrating call, else None.

    Edit/Write/NotebookEdit to a credential path is a warning, not a block
    (writing reveals no contents), so it returns None after the stderr note.
    """
    if tool == "Read":
        path = _field(tin, "file_path")
        is_blocked, pattern = is_blocked_path(path)
        if is_blocked:
            return f"Read blocked: {path} matches credential pattern '{pattern}'"
    elif tool == "Bash":
        cmd = _field(tin, "command")
        is_blocked, reason = bash_blocked(cmd)
        if is_blocked:
            return (
                f"Bash blocked: {reason}. Command: {cmd[:160]}"
                + ("…" if len(cmd) > 160 else "")
            )
    elif tool == "Grep":
        for key in ("path", "include"):
            v = _field(tin, key)
            is_blocked, pattern = is_blocked_path(v) if v else (False, None)
            if is_blocked:
                return f"Grep blocked: {key}={v} matches credential pattern '{pattern}'"
    elif tool in ("Edit", "Write", "NotebookEdit"):
        path = _field(tin, "file_path")
        is_blocked, pattern = is_blocked_path(path)
        if is_blocked:
            print(
                f"[secret-shield] WARNING: writing to credential path {path} "
                f"(matched '{pattern}'). Read of this path will remain blocked.",
                file=sys.stderr,
            )
    return None


def main() -> int:
    # Fail-open on any input failure: an unreadable stdin (OSError), invalid
    # JSON (JSONDecodeError/ValueError), or valid-but-non-object JSON
    # (`[]`, `42`, `"x"`, `true`, `null`) must NOT block or traceback — the
    # contract is exit 0. Only a JSON object carries a tool event.
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError, OSError):
        return 0

    if not isinstance(event, dict):
        return 0

    tool = event.get("tool_name", "")
    tin = event.get("tool_input", {}) or {}
    if not isinstance(tin, dict):
        return 0

    blocked_reason = _evaluate(tool, tin)
    if blocked_reason:
        print(f"[secret-shield] {blocked_reason}", file=sys.stderr)
        print(
            "[secret-shield] If this is a false positive, override per-call "
            "via the user's permissions allow-list, or relocate the file to "
            "a non-matched path. To extend the allow-list permanently, edit "
            f"{Path(__file__).resolve()} BLOCKED_PATH_PATTERNS.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
