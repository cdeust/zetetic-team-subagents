"""Where the gate reads a repository's files from: a directory, or a tree object in the git database.

The rules that judge a change must not come from the change itself, so the gate reads them from a TREE
(HEAD's), never from the working copy. Both sources answer the same five questions; ``gate_config``
asks them and does not know which one it was given:

  read(rel)    text of the file at ``rel``, or None when there is no such regular file
  isfile(rel)  a regular file (a symlink is not one)        isdir(rel)  a directory
  isexec(rel)  a regular file with the executable bit       names()     the top-level entry names

What bounds each git call: ``ls-tree`` of one tree reads that tree object, ``cat-file blob`` reads one
blob. Neither touches the working tree, the network (GIT_NO_LAZY_FETCH, gate_git) or the index, and none
carries a timer. A missing object raises ``gate_git.Unavailable`` (callers refuse, closed by default).
"""
from __future__ import annotations

import os
import subprocess

import gate_git as gitq

_BLOB_MODES = ("100644", "100755")


class DirSource:
    """A directory on disk (the private checkout of a tree, or a test fixture)."""

    def __init__(self, root: str):
        self.root = root

    def read(self, rel: str) -> str | None:
        try:
            with open(os.path.join(self.root, rel), encoding="utf-8") as fh:
                return fh.read()
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as exc:
            raise gitq.Unavailable(f"{rel} is unreadable: {exc.__class__.__name__}") from exc

    def isfile(self, rel: str) -> bool:
        return os.path.isfile(os.path.join(self.root, rel))

    def isdir(self, rel: str) -> bool:
        return os.path.isdir(os.path.join(self.root, rel))

    def isexec(self, rel: str) -> bool:
        path = os.path.join(self.root, rel)
        return os.path.isfile(path) and os.access(path, os.X_OK)

    def names(self) -> list:
        return sorted(os.listdir(self.root))


class GitSource:
    """A tree object of the repository at ``top``: the files as committed (or staged), not as edited.

    ``probe`` lists the paths the caller is going to ask about; they are looked up with ONE ``ls-tree`` call
    (a hook runs on every Bash call, and a process per path adds up). A path outside ``probe`` costs a call.
    """

    def __init__(self, top: str, tree: str, env: dict | None = None, probe: tuple = ()):
        self.top, self.tree, self.env = top, tree, env
        self._entries: dict = {}
        if probe:
            self._load(tuple(probe))

    def _load(self, paths: tuple) -> None:
        out = gitq.git(self.top, "ls-tree", "-z", self.tree, "--", *paths, env=self.env)
        if out.returncode != 0:
            raise gitq.Unavailable(f"cannot read tree {self.tree[:12]}: {out.stderr.strip()[:200]}")
        found = {}
        for record in out.stdout.split("\0"):
            meta, _, name = record.partition("\t")
            parts = meta.split()
            if name and len(parts) == 3:
                found[name] = tuple(parts)
        for path in paths:
            self._entries[path] = found.get(path)

    def entry(self, rel: str) -> tuple[str, str, str] | None:
        """(mode, type, object id) of ``rel`` in the tree, or None when absent."""
        if rel not in self._entries:
            self._load((rel,))
        return self._entries[rel]

    def read(self, rel: str) -> str | None:
        found = self.entry(rel)
        if found is None or found[0] not in _BLOB_MODES:
            return None
        return _blob(self.top, found[2], rel, self.env)

    def isfile(self, rel: str) -> bool:
        found = self.entry(rel)
        return found is not None and found[0] in _BLOB_MODES

    def isdir(self, rel: str) -> bool:
        found = self.entry(rel)
        return found is not None and found[1] == "tree"

    def isexec(self, rel: str) -> bool:
        found = self.entry(rel)
        return found is not None and found[0] == "100755"

    def names(self) -> list:
        out = gitq.git(self.top, "ls-tree", "--name-only", "-z", self.tree, env=self.env)
        if out.returncode != 0:
            raise gitq.Unavailable(f"cannot list tree {self.tree[:12]}: {out.stderr.strip()[:200]}")
        return sorted(n for n in out.stdout.split("\0") if n)


def _blob(top: str, oid: str, rel: str, env: dict | None) -> str:
    out = subprocess.run(["git", "cat-file", "blob", oid], cwd=top, capture_output=True, check=False,
                         stdin=subprocess.DEVNULL, env={**(os.environ if env is None else env), **gitq.ENV})
    if out.returncode != 0:
        raise gitq.Unavailable(f"cannot read {rel} ({oid[:12]}): {out.stderr.decode(errors='replace').strip()[:200]}")
    return out.stdout.decode("utf-8", errors="replace")


def as_source(where: object) -> "DirSource | GitSource":
    """A directory path becomes a DirSource; a source is returned as is."""
    return DirSource(where) if isinstance(where, str) else where
