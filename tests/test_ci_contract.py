"""The ci.json contract validator (tools/ci_contract.py): five non-empty commands,
no other keys, a version file that exists. Design: docs/superpowers/specs/
2026-10-22-single-ci-design.md, "Repository contract: ci.json" and decision 9."""
from __future__ import annotations

import json

import pytest

from tools import ci_contract

VALID = {"unit": "pytest", "regression": "bash t.sh", "e2e": "bash e.sh",
         "environment": "bash env.sh", "install": "bash i.sh"}


@pytest.fixture
def repo(tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text('{"version": "1.0.0"}\n', encoding="utf-8")
    return tmp_path


def write(repo, data):
    (repo / "ci.json").write_text(json.dumps(data), encoding="utf-8")


def test_a_valid_file_prints_the_five_commands_and_the_version_file(repo, capsys):
    write(repo, VALID)
    assert ci_contract.main([str(repo)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [f"{k}: {v}" for k, v in VALID.items()] + ["version_file: .claude-plugin/plugin.json"]


def test_a_missing_file_is_one_fault(repo, capsys):
    assert ci_contract.main([str(repo)]) == 1
    assert capsys.readouterr().err.splitlines() == ["ci.json: missing"]


def test_malformed_json_is_one_fault(repo, capsys):
    (repo / "ci.json").write_text("{not json", encoding="utf-8")
    assert ci_contract.main([str(repo)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("ci.json: not valid JSON")


def test_a_non_object_document_is_one_fault(repo):
    (repo / "ci.json").write_text("[1]", encoding="utf-8")
    assert ci_contract.faults(repo) == ["ci.json: must be a JSON object"]


def test_a_missing_key_names_the_key(repo):
    data = dict(VALID)
    del data["e2e"]
    write(repo, data)
    assert ci_contract.faults(repo) == ["e2e: missing"]


@pytest.mark.parametrize("bad, reason", [("", "empty command"), ("   \n", "empty command"),
                                         (None, "not a string"), (["pytest"], "not a string")])
def test_an_empty_or_non_string_command_names_the_key(repo, bad, reason):
    write(repo, {**VALID, "install": bad})
    assert ci_contract.faults(repo) == [f"install: {reason}"]


def test_an_extra_key_is_a_fault(repo):
    write(repo, {**VALID, "lint": "ruff"})
    assert ci_contract.faults(repo) == ["lint: unknown key (allowed: unit, regression, e2e, environment, install, version_file, release_packages)"]


def test_every_fault_is_reported_at_once(repo):
    write(repo, {"unit": "", "lint": "x"})
    assert ci_contract.faults(repo) == [
        "unit: empty command", "regression: missing", "e2e: missing", "environment: missing",
        "install: missing", "lint: unknown key (allowed: unit, regression, e2e, environment, install, version_file, release_packages)"]


def test_the_default_version_file_must_exist(tmp_path):
    write(tmp_path, VALID)
    assert ci_contract.faults(tmp_path) == ["version_file: .claude-plugin/plugin.json does not exist"]


def test_an_explicit_version_file_is_checked_and_printed(repo, capsys):
    (repo / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    write(repo, {**VALID, "version_file": "pyproject.toml"})
    assert ci_contract.main([str(repo)]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "version_file: pyproject.toml"


@pytest.mark.parametrize("bad, reason", [("", "empty path"), (3, "not a string"),
                                         ("Cargo.toml", "Cargo.toml does not exist")])
def test_a_bad_version_file_is_a_fault(repo, bad, reason):
    write(repo, {**VALID, "version_file": bad})
    assert ci_contract.faults(repo) == [f"version_file: {reason}"]


def test_the_default_root_is_the_current_directory(repo, monkeypatch):
    write(repo, VALID)
    monkeypatch.chdir(repo)
    assert ci_contract.main([]) == 0
