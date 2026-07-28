"""Contract tests for tools/gen-bundle-sbom.py.

The SBOM is one of the three integrity artifacts the release attests
(docs/ASSURANCE-CASE.md §2.1), and it is what makes "what is in this bundle"
diffable across releases. It was at 0% coverage (issue #71).

The property that matters most is **determinism**: two runs over the same tree
must produce the same component list in the same order, or the diff between two
releases is noise and nobody reads it. That is asserted directly rather than
inferred from the `sorted()` call.

Loaded by path: the file name has hyphens and `tools/` has no dotted path for it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SBOM_PATH = REPO_ROOT / "tools" / "gen-bundle-sbom.py"


def _load():
    spec = importlib.util.spec_from_file_location("gen_bundle_sbom", SBOM_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sbom = _load()


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """A small tree: nested dirs, a top-level file, and an empty dir."""
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "a.sh").write_text("echo a\n")
    (tmp_path / "tools" / "nested").mkdir(parents=True)
    (tmp_path / "tools" / "nested" / "b.py").write_text("print('b')\n")
    (tmp_path / "README.md").write_text("readme\n")
    (tmp_path / "empty").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ── _sha256 ──────────────────────────────────────────────────────────────────

def test_sha256_matches_hashlib(tmp_path):
    target = tmp_path / "f"
    target.write_bytes(b"contents")
    assert sbom._sha256(target) == hashlib.sha256(b"contents").hexdigest()


def test_sha256_of_an_empty_file():
    """The empty-file digest is a known constant; a wrong chunk loop breaks it."""
    import tempfile

    with tempfile.NamedTemporaryFile() as handle:
        assert sbom._sha256(Path(handle.name)) == hashlib.sha256(b"").hexdigest()


def test_sha256_reads_files_larger_than_one_chunk(tmp_path, monkeypatch):
    """The chunked read must concatenate, not just hash the first chunk."""
    monkeypatch.setattr(sbom, "_CHUNK", 8)
    payload = b"x" * 100
    target = tmp_path / "big"
    target.write_bytes(payload)
    assert sbom._sha256(target) == hashlib.sha256(payload).hexdigest()


# ── _iter_files ──────────────────────────────────────────────────────────────

def test_iter_files_walks_directories_recursively(bundle):
    names = [str(p) for p in sbom._iter_files(["hooks", "tools"])]
    assert "hooks/a.sh" in names and "tools/nested/b.py" in names


def test_iter_files_includes_a_named_file_as_is(bundle):
    assert [str(p) for p in sbom._iter_files(["README.md"])] == ["README.md"]


def test_iter_files_excludes_directories_themselves(bundle):
    """Only regular files become components; a dir entry would have no digest."""
    assert all(Path(p).is_file() for p in sbom._iter_files(["tools", "empty"]))


def test_iter_files_ignores_a_path_that_does_not_exist(bundle):
    assert sbom._iter_files(["nope"]) == []


def test_iter_files_deduplicates_overlapping_roots(bundle):
    """A file named both directly and via its directory appears once."""
    out = sbom._iter_files(["hooks", "hooks/a.sh"])
    assert [str(p) for p in out] == ["hooks/a.sh"]


def test_iter_files_is_sorted_and_therefore_deterministic(bundle):
    first = sbom._iter_files(["hooks", "tools", "README.md"])
    second = sbom._iter_files(["README.md", "tools", "hooks"])
    assert first == second == sorted(first)


# ── build_sbom ───────────────────────────────────────────────────────────────

def test_build_sbom_is_cyclonedx_1_5(bundle):
    doc = sbom.build_sbom("2.36.0", ["hooks"])
    assert doc["bomFormat"] == "CycloneDX"
    assert doc["specVersion"] == "1.5"


def test_build_sbom_describes_the_plugin_in_metadata(bundle):
    component = sbom.build_sbom("2.36.0", ["hooks"])["metadata"]["component"]
    assert component == {
        "type": "application",
        "name": "zetetic-team-subagents",
        "version": "2.36.0",
    }


def test_every_component_is_a_file_with_a_sha256(bundle):
    for component in sbom.build_sbom("1.0", ["hooks", "tools"])["components"]:
        assert component["type"] == "file"
        assert component["hashes"][0]["alg"] == "SHA-256"
        assert len(component["hashes"][0]["content"]) == 64


def test_component_digest_matches_the_file_on_disk(bundle):
    component = sbom.build_sbom("1.0", ["README.md"])["components"][0]
    assert component["name"] == "README.md"
    assert component["hashes"][0]["content"] == hashlib.sha256(b"readme\n").hexdigest()


def test_build_sbom_component_order_is_stable(bundle):
    """The diffability property: same tree in, same order out."""
    a = sbom.build_sbom("1.0", ["hooks", "tools", "README.md"])["components"]
    b = sbom.build_sbom("1.0", ["README.md", "hooks", "tools"])["components"]
    assert [c["name"] for c in a] == [c["name"] for c in b]


def test_build_sbom_of_an_empty_bundle_has_no_components(bundle):
    assert sbom.build_sbom("1.0", ["empty"])["components"] == []


def test_timestamp_is_utc_iso8601(bundle):
    stamp = sbom.build_sbom("1.0", ["hooks"])["metadata"]["timestamp"]
    assert stamp.endswith("Z") and len(stamp) == 20


# ── main ─────────────────────────────────────────────────────────────────────

def test_main_writes_valid_json_and_reports_the_count(bundle, capsys):
    out = bundle / "sbom.json"
    rc = sbom.main(["--version", "2.36.0", "--output", str(out), "hooks", "tools"])
    assert rc == 0
    doc = json.loads(out.read_text())
    assert len(doc["components"]) == 2
    assert "2 file components" in capsys.readouterr().out


def test_main_output_ends_with_a_newline(bundle):
    out = bundle / "sbom.json"
    sbom.main(["--version", "1.0", "--output", str(out), "hooks"])
    assert out.read_text().endswith("\n")


def test_main_requires_version_and_output(bundle):
    with pytest.raises(SystemExit):
        sbom.main(["hooks"])


def test_main_requires_at_least_one_root(bundle):
    with pytest.raises(SystemExit):
        sbom.main(["--version", "1.0", "--output", "x.json"])
