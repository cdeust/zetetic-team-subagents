"""Exercise portable generation against a disposable canonical-source tree."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sync(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "portable_reference_sync", ROOT / "tools/sync-portable-references.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "AGENTS", tmp_path / "agents/genius")
    return module


def skill(root, slug, frontmatter, filename="SKILL.md"):
    path = root / "skills" / slug / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\nSkill body\n")
    return path


def agent(sync, name="curie"):
    sync.AGENTS.mkdir(parents=True, exist_ok=True)
    path = sync.AGENTS / f"{name}.md"
    path.write_text(
        "\n".join(f"<{tag}>Evidence for {tag}.</{tag}>" for tag, _ in sync.SECTIONS)
    )
    return path


def invoke(sync, monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["sync-portable-references.py", *args])
    sync.main()


def test_discovery_is_opt_in_sorted_and_ignores_templates(sync, monkeypatch, capsys):
    skill(sync.ROOT, "zeta", "portable:\n  package: alpha\n  references: [curie]")
    skill(sync.ROOT, "alpha", "portable:\n  package: beta")
    skill(sync.ROOT, "unpackaged", "name: unpackaged")
    skill(sync.ROOT, "template", "portable:\n  package: ignored", "_template.md")
    skill(sync.ROOT, "index", "portable:\n  package: ignored", "_index.md")
    raw = sync.ROOT / "skills/unpackaged/raw.md"
    raw.write_text("No frontmatter\n")
    invoke(sync, monkeypatch, "--list")
    assert json.loads(capsys.readouterr().out) == [
        {"package": "alpha", "slug": "zeta", "references": ["curie"]},
        {"package": "beta", "slug": "alpha", "references": []},
    ]
    assert not (sync.ROOT / "plugins").exists()


def test_generate_check_and_repair_drift_preserve_canonical_sources(
    sync, monkeypatch, capsys
):
    source = skill(
        sync.ROOT, "reason", "portable:\n  package: packaged\n  references: [curie]"
    )
    skill(sync.ROOT, "self-contained", "portable:\n  package: packaged")
    canonical = agent(sync)
    original = canonical.read_bytes(), source.read_bytes()
    invoke(sync, monkeypatch)
    target = sync.ROOT / "plugins/packaged/skills/reason/references/curie.md"
    generated = target.read_text()
    assert generated.startswith("# Curie evidence method\n")
    for tag, heading in sync.SECTIONS:
        assert f"## {heading}\n\nEvidence for {tag}." in generated
    assert not (sync.ROOT / "plugins/packaged/skills/self-contained").exists()
    invoke(sync, monkeypatch, "--check")
    assert "match their canonical agents for 2 skill(s)" in capsys.readouterr().out
    target.write_text("manual stale edit\n")
    with pytest.raises(SystemExit, match="packaged/reason:curie"):
        invoke(sync, monkeypatch, "--check")
    assert (
        target.read_text() == "manual stale edit\n"
    )  # checking never repairs silently
    invoke(sync, monkeypatch)
    assert target.read_text() == generated
    assert (canonical.read_bytes(), source.read_bytes()) == original
    target.unlink()
    with pytest.raises(SystemExit, match="packaged/reason:curie"):
        invoke(sync, monkeypatch, "--check")


def test_incomplete_agent_is_rejected_before_writing_a_reference(sync, monkeypatch):
    skill(sync.ROOT, "reason", "portable:\n  package: packaged\n  references: [curie]")
    source = agent(sync)
    source.write_text("<identity>Only the identity is present.</identity>\n")
    with pytest.raises(ValueError, match="missing <routing> section"):
        invoke(sync, monkeypatch)
    assert not list((sync.ROOT / "plugins").rglob("*.md"))


def test_empty_discovery_is_an_error_not_a_successful_noop(sync, monkeypatch):
    with pytest.raises(SystemExit, match="no skill declares"):
        invoke(sync, monkeypatch, "--check")
