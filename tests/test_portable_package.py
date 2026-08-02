"""Contract tests for the isolated Codex and Gemini evidence-synthesis slice."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "plugins" / "zetetic-reasoning"
SKILL = PACKAGE / "skills" / "evidence-synthesis"
REFERENCES = {
    "cochrane.md",
    "toulmin.md",
    "feynman.md",
    "darwin.md",
    "laplace.md",
    "gadamer.md",
    "strauss.md",
    "geertz.md",
}
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
HOST_COUPLING = re.compile(r"\b(?:claude|hooks?|mcp)\b", re.IGNORECASE)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _frontmatter_keys(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter = text.split("---\n", 2)[1]
    return {
        line.split(":", 1)[0]
        for line in frontmatter.splitlines()
        if line and not line.startswith((" ", "\t"))
    }


def test_required_portable_files_exist() -> None:
    required = {
        PACKAGE / ".codex-plugin" / "plugin.json",
        PACKAGE / "gemini-extension.json",
        PACKAGE / "README.md",
        SKILL / "SKILL.md",
        SKILL / "agents" / "openai.yaml",
    }
    assert all(path.is_file() for path in required)


def test_codex_manifest_declares_only_the_skill_surface() -> None:
    manifest = _json(PACKAGE / ".codex-plugin" / "plugin.json")
    assert manifest["name"] == "zetetic-reasoning"
    assert SEMVER.fullmatch(manifest["version"])
    assert manifest["skills"] == "./skills/"
    assert not ({"hooks", "mcpServers", "apps", "postInstall"} & manifest.keys())


def test_gemini_manifest_matches_codex_identity() -> None:
    codex = _json(PACKAGE / ".codex-plugin" / "plugin.json")
    gemini = _json(PACKAGE / "gemini-extension.json")
    assert set(gemini) == {"name", "version", "description"}
    assert gemini["name"] == codex["name"]
    assert gemini["version"] == codex["version"]
    assert SEMVER.fullmatch(gemini["version"])


def test_repo_marketplace_points_to_the_isolated_package() -> None:
    marketplace = _json(ROOT / ".agents" / "plugins" / "marketplace.json")
    assert marketplace["name"] == "zetetic-marketplace"
    assert len(marketplace["plugins"]) == 1
    entry = marketplace["plugins"][0]
    assert entry["name"] == "zetetic-reasoning"
    assert entry["source"] == {
        "source": "local",
        "path": "./plugins/zetetic-reasoning",
    }
    assert entry["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }
    assert entry["category"] == "Research"


def test_skill_frontmatter_is_portable() -> None:
    assert _frontmatter_keys(SKILL / "SKILL.md") == {"name", "description"}


def test_skill_links_exactly_the_vendored_references() -> None:
    reference_dir = SKILL / "references"
    assert {path.name for path in reference_dir.glob("*.md")} == REFERENCES
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    links = set(re.findall(r"\(references/([a-z-]+\.md)\)", skill_text))
    assert links == REFERENCES
    assert all((reference_dir / link).is_file() for link in links)


def test_every_reference_has_multiple_traceable_sources() -> None:
    for path in (SKILL / "references").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert "## Primary" in text
        assert text.count("\n- ") >= 2


def test_skill_requires_sources_uncertainty_blind_spots_and_refusal() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8").casefold()
    required_phrases = {
        "primary source",
        "independent",
        "counter-evidence",
        "uncertainty and blind spots",
        "refuse or stop",
        "i don't know",
        "do not invent",
    }
    assert all(phrase in text for phrase in required_phrases)


def test_portable_package_contains_no_host_specific_runtime_tokens() -> None:
    text_files = [
        path
        for path in PACKAGE.rglob("*")
        if path.is_file() and path.suffix in {".json", ".md", ".yaml", ".yml"}
    ]
    violations = {
        str(path.relative_to(PACKAGE)): HOST_COUPLING.findall(
            path.read_text(encoding="utf-8")
        )
        for path in text_files
        if HOST_COUPLING.search(path.read_text(encoding="utf-8"))
    }
    assert violations == {}


def test_release_bundle_includes_portable_marketplace_and_package() -> None:
    script = (ROOT / "tools" / "build-release-bundle.sh").read_text(
        encoding="utf-8"
    )
    assert ".agents/plugins/marketplace.json" in script
    assert "plugins/zetetic-reasoning" in script
