"""Per-package release identities and refusal before exporting commands.

Source: claude-mods Pipeline39905709255; owner-approved package tag contract.
"""

import json

import pytest

from tools import ci_contract

COMMANDS = {key: "true" for key in ci_contract.KEYS}


def manifest(root, name="plugin.json", content='{"version":"1.2.3"}'):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return name


def configure(root, **settings):
    data = {**COMMANDS, **settings}
    (root / "ci.json").write_text(json.dumps(data))
    return data


def package(path="plugin.json", prefix="engine/v"):
    return {"version_file": path, "tag_prefix": prefix}


def test_package_versions_remain_independent_and_ordered(tmp_path):
    a = manifest(tmp_path, "mods/engine/plugin.json")
    b = manifest(tmp_path, "codex/plugin.json", '{"version":"0.1.2"}')
    data = configure(tmp_path, release_packages=[package(a), package(b, "codex/v")])
    assert ci_contract.faults(tmp_path) == []
    assert ci_contract.release_tags(data, tmp_path) == ["engine/v1.2.3", "codex/v0.1.2"]


@pytest.mark.parametrize(
    "name,body",
    [
        ("plugin.json", '{"version":"1.2.3"}'),
        ("pyproject.toml", '[project]\nversion="1.2.3"\n'),
        ("Cargo.toml", '[package]\nversion="1.2.3"\n'),
    ],
)
def test_single_package_version_file_keeps_existing_tag_format(tmp_path, name, body):
    data = configure(tmp_path, version_file=manifest(tmp_path, name, body))
    assert ci_contract.faults(tmp_path) == []
    assert ci_contract.release_tags(data, tmp_path) == ["v1.2.3"]


@pytest.mark.parametrize(
    "body",
    [
        "{}",
        '{"version":null}',
        '{"version":2}',
        '{"version":""}',
        '{"version":"a b"}',
        '{"version":"1\\n2"}',
        "[]",
        "{broken",
    ],
)
def test_bad_manifest_never_exports_partial_outputs(tmp_path, monkeypatch, body):
    manifest(tmp_path, "good.json")
    manifest(tmp_path, "bad.json", body)
    configure(
        tmp_path, release_packages=[package("good.json"), package("bad.json", "bad/v")]
    )
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert ci_contract.main([str(tmp_path), "--github-output"]) == 1
    assert not output.exists()


@pytest.mark.parametrize(
    "entries",
    [
        [],
        "plugin.json",
        [None],
        [{}],
        [package(), package()],
        [package(), package("other.json")],
        [package(prefix="bad../v")],
        [package(prefix="")],
        [{**package(), "unexpected": True}],
    ],
)
def test_invalid_package_declarations_are_rejected(tmp_path, entries):
    manifest(tmp_path)
    manifest(tmp_path, "other.json")
    configure(tmp_path, release_packages=entries)
    assert ci_contract.faults(tmp_path)


def test_package_and_single_version_declarations_cannot_be_mixed(tmp_path):
    manifest(tmp_path)
    configure(tmp_path, version_file="plugin.json", release_packages=[package()])
    assert ci_contract.faults(tmp_path)


@pytest.mark.parametrize("kind", ["absolute", "parent", "symlink"])
def test_manifest_cannot_escape_repository(tmp_path, kind):
    root = tmp_path / "repo"
    root.mkdir()
    manifest(tmp_path, "outside.json")
    paths = {"absolute": str(tmp_path / "outside.json"), "parent": "../outside.json"}
    (root / "link.json").symlink_to(tmp_path / "outside.json")
    paths["symlink"] = "link.json"
    configure(root, version_file=paths[kind])
    assert ci_contract.faults(root)


def test_aliases_cannot_declare_same_manifest_twice(tmp_path):
    manifest(tmp_path)
    (tmp_path / "alias.json").symlink_to(tmp_path / "plugin.json")
    configure(tmp_path, release_packages=[package(), package("alias.json", "other/v")])
    assert ci_contract.faults(tmp_path)


def test_missing_later_manifest_does_not_export_valid_earlier_package(
    tmp_path, monkeypatch
):
    manifest(tmp_path)
    configure(
        tmp_path, release_packages=[package(), package("missing.json", "missing/v")]
    )
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert ci_contract.main([str(tmp_path), "--github-output"]) == 1
    assert not output.exists()


def test_paths_with_spaces_and_pre_release_versions_are_preserved(tmp_path):
    path = manifest(
        tmp_path, "package one/plugin.json", '{"version":"1.2.3-rc.1+build.2"}'
    )
    data = configure(tmp_path, release_packages=[package(path)])
    assert ci_contract.faults(tmp_path) == []
    assert ci_contract.release_tags(data, tmp_path) == ["engine/v1.2.3-rc.1+build.2"]


def test_two_distinct_prefixes_cannot_resolve_to_same_tag(tmp_path):
    manifest(tmp_path, "one.json", '{"version":"1.2"}')
    manifest(tmp_path, "two.json", '{"version":"2"}')
    configure(
        tmp_path,
        release_packages=[package("one.json", "pkg/v"), package("two.json", "pkg/v1.")],
    )
    assert ci_contract.faults(tmp_path)


def test_unreadable_manifest_is_a_contract_failure(tmp_path, monkeypatch):
    path = manifest(tmp_path)
    configure(tmp_path, version_file=path)
    original = type(tmp_path).read_text

    def read(target, *args, **kwargs):
        if target.name == "plugin.json":
            raise PermissionError("fixture denied read")
        return original(target, *args, **kwargs)

    monkeypatch.setattr(type(tmp_path), "read_text", read)
    assert "fixture denied read" in ci_contract.faults(tmp_path)[0]


def test_validated_export_keeps_multiline_commands_and_package_tags(
    tmp_path, monkeypatch
):
    manifest(tmp_path)
    configure(tmp_path, unit="first\nsecond", release_packages=[package()])
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert ci_contract.main([str(tmp_path), "--github-output"]) == 0
    lines = iter(output.read_text().splitlines())
    values = {}
    for line in lines:
        key, delimiter = line.split("<<")
        body = []
        for value in lines:
            if value == delimiter:
                break
            body.append(value)
        values[key] = "\n".join(body)
    assert values["unit"] == "first\nsecond"
    assert json.loads(values["release_tags"]) == ["engine/v1.2.3"]
    assert set(values) == {*ci_contract.KEYS, "release_tags", "release_group"}


def test_release_group_tracks_version_set_not_order_or_commit(tmp_path, monkeypatch):
    manifest(tmp_path, "one.json")
    manifest(tmp_path, "two.json", '{"version":"2.0.0"}')
    entries = [package("one.json", "one/v"), package("two.json", "two/v")]
    groups = []
    for index, packages in enumerate((entries, list(reversed(entries)), entries)):
        if index == 2:
            manifest(tmp_path, "two.json", '{"version":"2.0.1"}')
        configure(tmp_path, release_packages=packages)
        output = tmp_path / f"output-{index}"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))
        assert ci_contract.main([str(tmp_path), "--github-output"]) == 0
        lines = output.read_text().splitlines()
        start = next(
            i for i, line in enumerate(lines) if line.startswith("release_group<<")
        )
        groups.append(lines[start + 1])
    assert groups[0] == groups[1]
    assert groups[1] != groups[2]


def test_export_rejects_a_uuid_delimiter_present_as_a_value_line(tmp_path, monkeypatch):
    import uuid

    collision = uuid.UUID("00000000-0000-4000-8000-000000000000")
    replacement = uuid.UUID("00000000-0000-4000-8000-000000000001")
    generated = iter([collision, replacement])
    monkeypatch.setattr(uuid, "uuid4", lambda: next(generated, replacement))
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    data = {**COMMANDS, "unit": f"first\n{collision}\nlast"}
    ci_contract._export(data, ["v1.2.3"])
    lines = output.read_text().splitlines()
    assert lines[:5] == [
        f"unit<<{replacement}",
        "first",
        str(collision),
        "last",
        str(replacement),
    ]


@pytest.mark.parametrize("extension", ["json", "toml"])
def test_tomllib_absence_keeps_json_usable_and_explains_toml_requirement(
    tmp_path, monkeypatch, extension
):
    import runpy
    import sys

    monkeypatch.setitem(sys.modules, "tomllib", None)
    namespace = runpy.run_path(ci_contract.__file__)
    body = (
        '{"version":"1.2.3"}' if extension == "json" else '[project]\nversion="1.2.3"'
    )
    configure(tmp_path, version_file=manifest(tmp_path, f"plugin.{extension}", body))
    faults = namespace["faults"](tmp_path)
    assert faults == (
        []
        if extension == "json"
        else ["version_file: TOML requires Python 3.11+ (stdlib tomllib)"]
    )


def test_marketplace_declared_bundle_version_preserves_historical_tag(tmp_path):
    # session-optimizer build-release-bundle.sh at 9145994 reads metadata.version.
    body = '{"metadata":{"version":"2.3.1"},"plugins":[{"version":"0.1.2"}]}'
    configure(tmp_path, version_file=manifest(tmp_path, "marketplace.json", body))
    data, _ = ci_contract._load(tmp_path)
    assert ci_contract.faults(tmp_path) == []
    assert ci_contract.release_tags(data, tmp_path) == ["v2.3.1"]


@pytest.mark.parametrize("version", [None, "", 3, "invalid version"])
def test_invalid_root_version_cannot_fall_back_to_valid_metadata(tmp_path, version):
    body = json.dumps({"version": version, "metadata": {"version": "2.3.1"}})
    configure(tmp_path, version_file=manifest(tmp_path, content=body))
    assert ci_contract.faults(tmp_path)


def test_root_version_takes_precedence_over_metadata(tmp_path):
    body = '{"version":"1.2.3","metadata":{"version":"2.3.1"}}'
    configure(tmp_path, version_file=manifest(tmp_path, content=body))
    data, _ = ci_contract._load(tmp_path)
    assert ci_contract.release_tags(data, tmp_path) == ["v1.2.3"]


@pytest.mark.parametrize("metadata", [None, [], "2.3.1", {}, {"version": None}])
def test_invalid_metadata_version_fails_contract(tmp_path, metadata):
    body = json.dumps({"metadata": metadata})
    configure(tmp_path, version_file=manifest(tmp_path, content=body))
    assert ci_contract.faults(tmp_path)
