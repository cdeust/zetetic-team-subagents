"""Verify the historical PR #174 archive using inert metadata in any checkout."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


DIRECTORY = "tasks/evidence/pr-174-review"
ARCHIVE = Path(__file__).resolve().parents[1] / DIRECTORY
SOURCE_COMMIT = "986aa55c27ffcba3cfa42d2b4a1728bb5ae0bebc"
# git rev-parse 986aa55c27ffcba3cfa42d2b4a1728bb5ae0bebc:tasks/evidence/pr-174-review
SOURCE_TREE = "280d04ca19fd64ea598700bdcac41e97670855e0"
# Measured from the original Git blobs, sorted by path. Each UTF-8 row is
# path, NUL, decimal byte length, NUL, lowercase SHA-256, LF.
SOURCE_BYTE_FINGERPRINT = "26e16942e4e3cc2018607d2417d04a9001291885a01e714883fa1ebf514506cd"


class ReviewEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads((ARCHIVE / "provenance.json").read_bytes())

    def test_paths_modes_and_blob_ids_rebuild_the_original_tree(self):
        self.assertEqual(self.inventory["source_commit"], SOURCE_COMMIT)
        self.assertEqual(self.inventory["source_directory"], DIRECTORY)
        self.assertEqual(self.inventory["source_tree"], SOURCE_TREE)
        entries = self.inventory["files"]
        paths = [entry["path"] for entry in entries]
        self.assertEqual(paths, sorted(set(paths)))

        # Git only receives index metadata. Missing historical blobs are expected
        # in shallow CI checkouts. Build the index in a new, isolated repository.
        index = b"".join(
            f'{entry["mode"]} {entry["git_blob"]}\t{entry["path"]}\0'.encode()
            for entry in entries
        )
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        with tempfile.TemporaryDirectory() as scratch:
            def git(*args, data=None):
                return subprocess.run(
                    ["git", "-C", scratch, *args], input=data, check=True,
                    stdout=subprocess.PIPE, env=env,
                ).stdout

            git("init", "--quiet", "--template=", "--object-format=sha1")
            git("update-index", "-z", "--index-info", data=index)
            tree = git("write-tree", "--missing-ok").decode().strip()
        self.assertEqual(tree, SOURCE_TREE)

    def test_byte_metadata_matches_the_source_measurement(self):
        digest = hashlib.sha256()
        for entry in self.inventory["files"]:
            digest.update(f'{entry["path"]}\0{entry["bytes"]}\0{entry["sha256"]}\n'.encode())
        self.assertEqual(digest.hexdigest(), SOURCE_BYTE_FINGERPRINT)

    def test_only_the_original_reports_and_archive_metadata_are_present(self):
        reports = {
            entry["path"]: entry for entry in self.inventory["files"]
            if entry["path"].endswith(".txt")
        }
        archived_files = {
            path.relative_to(ARCHIVE).as_posix()
            for path in ARCHIVE.rglob("*") if path.is_file() or path.is_symlink()
        }
        self.assertEqual(archived_files, set(reports) | {"README.md", "provenance.json"})
        for name, entry in reports.items():
            with self.subTest(path=name):
                report = ARCHIVE / name
                self.assertFalse(report.is_symlink())
                self.assertFalse(report.stat().st_mode & 0o111)
                data = report.read_bytes()
                self.assertEqual(len(data), entry["bytes"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])
