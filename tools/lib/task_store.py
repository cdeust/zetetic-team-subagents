"""task_store.py -- the on-disk layer of the async-task module (docs/async-tasks.md).

The task record is the only contract between a producer (the detached worker)
and its consumers (hooks, gates, CLIs). This module owns the bytes: where the
records live, how they are written (never partially visible), how a process is
proven alive (an OS event, never a clock), and the failure inbox.

Nothing here waits, sleeps, polls or compares elapsed time. Timestamps in a
record (``created``, ``started``, ``finished``) are descriptions for humans and
are never read by a decision.

Stdlib only, Python >= 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone

SCHEMA = 1
ENV_DIR = "ZETETIC_TASKS_DIR"  # source: override of the state dir, used by tests and by non-default layouts
KIND_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")  # source: no hyphen, so an id parses as <kind>-<key>
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")  # source: filesystem-safe, <= NAME_MAX with the suffixes below
TERMINAL = ("done", "failed")
EXCERPT_BYTES = 2000  # source: result_excerpt is the tail of the output; the full output is always in output_path


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def task_id(kind: str, key: str) -> str:
    """Pre: kind matches KIND_RE, key matches KEY_RE. Post: ``<kind>-<key>``."""
    if not KIND_RE.match(kind):
        raise ValueError(f"task kind {kind!r} must match {KIND_RE.pattern}")
    if not KEY_RE.match(key):
        raise ValueError(f"task key {key!r} must match {KEY_RE.pattern}")
    return f"{kind}-{key}"


def kind_of(tid: str) -> str:
    return tid.split("-", 1)[0]


# -- locating the state directory ------------------------------------------------

def _git_common_dir(cwd: str) -> str | None:
    probe = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=cwd,
                           capture_output=True, text=True, check=False)
    if probe.returncode != 0:
        return None
    common = probe.stdout.strip()
    return common if os.path.isabs(common) else os.path.normpath(os.path.join(cwd, common))


def repo_slug(cwd: str) -> str:
    """Non-git scope: ``<basename>-<8 hex of the absolute path>``."""
    path = os.path.realpath(cwd)
    digest = hashlib.sha1(path.encode()).hexdigest()[:8]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(path) or "root")
    return f"{base}-{digest}"


def tasks_dir(cwd: str) -> str:
    """Post: the state directory for ``cwd`` exists and is returned.

    ``$ZETETIC_TASKS_DIR`` wins; else ``<git-common-dir>/zetetic-tasks`` (shared
    by every worktree of a repo); else ``~/.claude/fleet/tasks/<repo_slug>``.
    """
    override = os.environ.get(ENV_DIR)
    if override:
        directory = override
    else:
        common = _git_common_dir(cwd)
        if common:
            directory = os.path.join(common, "zetetic-tasks")
        else:
            directory = os.path.join(os.path.expanduser("~"), ".claude", "fleet", "tasks", repo_slug(cwd))
    os.makedirs(os.path.join(directory, "inbox"), exist_ok=True)
    return directory


def record_path(directory: str, tid: str) -> str:
    return os.path.join(directory, f"{tid}.json")


def output_path(directory: str, tid: str, attempt: int) -> str:
    return os.path.join(directory, f"{tid}.a{attempt}.out")


# -- records: never partially visible --------------------------------------------

def _dump(path_dir: str, tid: str, obj: dict) -> str:
    """Write ``obj`` to a private temp file in the same directory, fsynced."""
    tmp = os.path.join(path_dir, f".{tid}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return tmp


def atomic_write(path: str, obj: dict) -> None:
    """Pre: ``path`` is inside an existing directory. Post: ``path`` holds all of
    ``obj`` or all of its previous content; no reader ever sees a prefix
    (write temp in the same directory, then rename(2), which is atomic)."""
    tmp = _dump(os.path.dirname(path), os.path.basename(path), obj)
    try:
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def create_exclusive(path: str, obj: dict) -> bool:
    """Create ``path`` with ``obj`` only if it does not exist, atomically.

    Post: True if this call created it (and the content is complete from the
    first instant the name exists); False if it already existed. A plain
    O_EXCL create would expose an empty file between create and write; here the
    complete temp file is hard-linked into place and link(2) fails with EEXIST.
    """
    tmp = _dump(os.path.dirname(path), os.path.basename(path), obj)
    try:
        os.link(tmp, path)
        return True
    except FileExistsError:
        return False
    finally:
        os.unlink(tmp)


def read_record(path: str) -> dict | None:
    """The record at ``path``, or None if there is none. Never a partial one."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None


def read_excerpt(path: str) -> tuple[str, int]:
    """(tail of the file as text, total size in bytes); ("", 0) if absent."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - EXCERPT_BYTES))
            return handle.read().decode("utf-8", errors="replace"), size
    except FileNotFoundError:
        return "", 0


# -- liveness: an OS fact, never a clock -----------------------------------------

def proc_info(pid: int) -> tuple[str, str] | None:
    """(start-time token, ps state) of ``pid``, or None if no such process.

    The token ('lstart' of ps) identifies the process incarnation, so a reused
    pid is not mistaken for the worker. Used for identity only.
    """
    probe = subprocess.run(["ps", "-o", "lstart=,stat=", "-p", str(pid)], capture_output=True,
                           text=True, check=False, env={**os.environ, "LC_ALL": "C"})
    parts = probe.stdout.split()
    if probe.returncode != 0 or len(parts) < 2:
        return None
    return " ".join(parts[:-1]), parts[-1]


def proc_token(pid: int) -> str | None:
    info = proc_info(pid)
    return info[0] if info else None


def is_alive(pid: int | None, token: str | None) -> bool:
    """True iff ``pid`` is a running (not zombie) process of the recorded incarnation."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # exists, owned by someone else: the ps check decides
    info = proc_info(pid)
    if info is None or info[1].startswith("Z"):
        return False
    return token is None or info[0] == token


def record_alive(rec: dict) -> bool:
    """Liveness of whoever is responsible for a queued/running record: the
    worker once its pid is recorded, else the starter that created it."""
    if rec.get("pid") is not None:
        return is_alive(rec["pid"], rec.get("pid_token"))
    return is_alive(rec.get("starter_pid"), rec.get("starter_token"))


# -- single-winner claims (no locks, no clocks) ----------------------------------

def claim(directory: str, name: str) -> bool:
    """Win ``<directory>/<name>`` exactly once. True iff this caller is the winner.

    A claim records its owner. If the owner died before finishing, the next
    claimer retires the dead claim (rename is atomic: one retirer wins) and
    competes again, so a crash cannot wedge a transition forever.
    """
    path = os.path.join(directory, name)
    me = {"pid": os.getpid(), "token": proc_token(os.getpid())}
    while True:
        if create_exclusive(path, me):
            return True
        owner = read_record(path)
        if owner is None or is_alive(owner.get("pid"), owner.get("token")):
            return False
        try:
            os.rename(path, f"{path}.dead.{uuid.uuid4().hex}")
        except FileNotFoundError:
            pass


# -- the failure inbox: one file per failure, at-least-once ----------------------

def inbox_put(directory: str, rec: dict) -> None:
    """Idempotent: the entry name is (id, attempt), so a repeat rewrites the same file."""
    entry = {k: rec.get(k) for k in ("id", "kind", "key", "state", "rc", "signal", "reason",
                                     "result_excerpt", "output_path", "attempt")}
    name = f"{rec['id']}.a{rec['attempt']}.json"
    atomic_write(os.path.join(directory, "inbox", name), entry)


def inbox_drain(directory: str) -> list[dict]:
    """Return every pending failure entry, then acknowledge (unlink) each.

    Post: a second call returns [] unless a new failure arrived. Delivery is
    at-least-once: a drainer killed between read and ack redelivers, and two
    concurrent drainers may both deliver; a failure is never lost.
    """
    inbox = os.path.join(directory, "inbox")
    entries = []
    for name in sorted(os.listdir(inbox)):
        if name.startswith("."):
            continue
        entry = read_record(os.path.join(inbox, name))
        if entry is not None:
            entries.append(entry)
        try:
            os.unlink(os.path.join(inbox, name))
        except FileNotFoundError:
            pass
    return entries
