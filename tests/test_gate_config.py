"""hooks/lib/gate_config.py: the declaration order and the rule that maps a change to the checks to run."""
from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
import gate_config as cfg  # noqa: E402

LINT = {"name": "lint", "paths": ["**/*.py"], "argv": ["ruff", "{files}"]}
TESTS = {"argv": ["pytest", "{tests}"], "files": ["tests/test_*.py"], "same_name": "tests/test_{stem}.py",
         "map": [{"paths": ["docs/**"], "tests": ["tests/test_docs.py"]}], "fast": ["tests/test_smoke.py"]}


def tree(root: Path, *files: str) -> Path:
    for name in files:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("x\n")
    return root


def config(**extra) -> dict:
    return cfg.validate({"version": 1, "checks": [LINT], "tests": TESTS, **extra})


def names(steps) -> list:
    return [s.name for s in steps]


@pytest.mark.parametrize("pattern,path,expected", [
    ("**/*.py", "a.py", True), ("**/*.py", "x/y/a.py", True), ("*.py", "x/a.py", False),
    ("hooks/**", "hooks/lib/a.py", True), ("hooks/**", "tools/a.py", False),
    ("tests/test_*.py", "tests/test_a.py", True), ("tests/test_*.py", "tests/sub/test_a.py", False),
    ("a?.txt", "ab.txt", True), ("a?.txt", "a/.txt", False), ("a.b", "axb", False),
    ("*.py", "apy", False), ("*.py", "a.py", True), ("a**b", "axyz", False), ("a**b", "a/x/b", True),
    ("**/x", "x", True), ("**/x", "d/x", True), ("**/x", "dx", False),
])
def test_glob(pattern, path, expected):
    assert bool(cfg.glob_regex(pattern).match(path)) is expected


def test_a_check_runs_only_for_matching_changed_files_and_receives_them(tmp_path):
    tree(tmp_path, "a.py", "b.txt", "tests/test_a.py")
    steps = cfg.plan(config(), tmp_path, ["a.py", "b.txt"])
    assert steps[0] == cfg.Step("lint", ["ruff", "a.py"])
    assert cfg.plan(config(), tmp_path, ["b.txt"])[0].name != "lint"


def test_tests_follow_the_map_the_same_name_rule_and_changed_test_files(tmp_path):
    tree(tmp_path, "a.py", "tests/test_a.py", "tests/test_docs.py", "tests/test_b.py", "docs/x.md", "tests/test_smoke.py")
    run = lambda changed: [s for s in cfg.plan(config(), tmp_path, changed) if s.name.startswith("tests")][0].argv  # noqa: E731
    assert run(["a.py"]) == ["pytest", "tests/test_a.py"]  # same_name
    assert run(["docs/x.md"]) == ["pytest", "tests/test_docs.py"]  # map
    assert run(["tests/test_b.py"]) == ["pytest", "tests/test_b.py"]  # a changed test file runs itself
    tree(tmp_path, "tests/test_stop_gate.py")
    assert run(["hooks/stop-gate.py"]) == ["pytest", "tests/test_stop_gate.py"]  # '-' in a script name is '_' in its test


def test_unmapped_change_runs_fast_then_whole_suite(tmp_path):
    tree(tmp_path, "README.md", "tests/test_smoke.py")
    steps = cfg.plan(config(), tmp_path, ["README.md"])
    assert steps == [cfg.Step("tests", ["pytest", "tests/test_smoke.py"])]
    no_fast = cfg.validate({"version": 1, "tests": {k: v for k, v in TESTS.items() if k != "fast"}})
    assert cfg.plan(no_fast, tmp_path, ["README.md"]) == [cfg.Step("tests-full", ["pytest"])]


def test_a_change_to_the_gate_config_runs_everything(tmp_path):
    tree(tmp_path, "a.py", "src/b.py", "tests/test_a.py", ".zetetic/gate.json")
    steps = cfg.plan(config(), tmp_path, [".zetetic/gate.json"])
    assert steps[0] == cfg.Step("lint", ["ruff", "a.py", "src/b.py", "tests/test_a.py"])  # every matching file, not only the changed ones
    assert steps[-1] == cfg.Step("tests-full", ["pytest"])
    custom = config(full_on=["pyproject.toml"])
    assert names(cfg.plan(custom, tmp_path, ["pyproject.toml"])) == ["lint", "tests-full"]
    assert names(cfg.plan(custom, tmp_path, [".zetetic/gate.json"])) == ["lint", "tests-full"]  # default always applies


def test_no_change_means_no_step_and_a_deletion_still_selects_its_tests(tmp_path):
    tree(tmp_path, "tests/test_gone.py")
    assert cfg.plan(config(), tmp_path, []) == []
    steps = cfg.plan(config(), tmp_path, ["gone.py"])  # deleted source: no lint file, but its test runs
    assert steps == [cfg.Step("tests", ["pytest", "tests/test_gone.py"])]


def test_a_check_without_paths_runs_even_for_a_deletion_only_change(tmp_path):
    always = cfg.validate({"version": 1, "checks": [{"name": "all", "argv": ["x", "{files}"]}]})
    assert cfg.plan(always, tmp_path, ["gone.py"]) == [cfg.Step("all", ["x"])]


@pytest.mark.parametrize("bad", [
    {"version": 1, "checks": [{"name": "x", "argv": [1]}]}, {"version": 1, "checks": [{"name": "x", "argv": "s"}]},
    {"version": 1, "checks": [{"name": "", "argv": ["x"]}]}, {"version": 1, "checks": [{"name": 5, "argv": ["x"]}]},
    {"version": 1, "tests": []}, {"version": 1, "tests": {"argv": ["{tests}"], "zzz": 1}},
    {"version": 1, "tests": {"files": []}}, {"version": 1, "tests": {"argv": ["{tests}"], "same_name": 3}},
    {"version": 1, "checks": [LINT], "full_on": "x"}, {"version": 1, "checks": [LINT], "env": {"A": 1}}, {"version": 1, "checks": [LINT], "link": ["../x"]},
    {"version": 1, "checks": [LINT], "link": ["/abs"]}, {"version": 1, "checks": [LINT], "env": []},
    {"version": 2, "checks": [LINT]}, {"version": 1}, {"version": 1, "checks": "x"},
    {"version": 1, "checks": [{"name": "x"}]}, {"version": 1, "checks": [{"name": "x", "argv": []}]},
    {"version": 1, "tests": {"argv": ["pytest"]}}, {"version": 1, "checks": [LINT], "extra": 1},
    {"version": 1, "tests": {"argv": ["pytest", "{tests}"], "map": [{"paths": ["a"]}]}}, [],
])
def test_invalid_config_is_refused_not_guessed(bad):
    with pytest.raises(cfg.ConfigError):
        cfg.validate(bad)


def make_exec(path: Path, mode=0o755) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(mode)


def test_declaration_order(tmp_path):
    assert cfg.declaration(str(tmp_path)) is None
    (tmp_path / "pytest.ini").write_text("")
    (tmp_path / "tests").mkdir()
    assert cfg.declaration(str(tmp_path)) == "stack"
    make_exec(tmp_path / "scripts" / "gate.sh")
    assert cfg.declaration(str(tmp_path)) == "legacy"
    (tmp_path / ".zetetic").mkdir()
    (tmp_path / ".zetetic" / "gate.json").write_text(json.dumps({"version": 1, "checks": [LINT]}))
    assert cfg.declaration(str(tmp_path)) == "config"
    (tmp_path / ".zetetic" / "gate.json").write_text(json.dumps({"version": 1, "off": True}))
    assert cfg.declaration(str(tmp_path)) is None
    (tmp_path / ".zetetic" / "gate.json").unlink()
    (tmp_path / ".zetetic-gate.json").write_text('{"off": true}')
    assert cfg.declaration(str(tmp_path)) is None


def test_a_non_executable_script_is_not_a_declaration(tmp_path):
    make_exec(tmp_path / "scripts" / "gate.sh", mode=stat.S_IRUSR | stat.S_IWUSR)
    assert cfg.declaration(str(tmp_path)) is None


def test_stack_defaults_are_the_documented_whole_suites(tmp_path):
    (tmp_path / "Cargo.toml").write_text("")
    (tmp_path / "go.mod").write_text("")
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"lint": "x", "test": "y"}}))
    stack = cfg.stack_config(str(tmp_path))
    assert [c["name"] for c in stack["checks"]] == ["fmt", "clippy", "test", "lint", "test", "vet", "test"]
    assert cfg.setup_for(stack, "/top", "/top/.git") == ({"CARGO_TARGET_DIR": "/top/.git/zetetic-gate-target"}, ["node_modules"])
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "echo no test specified"}}))
    after = cfg.stack_config(str(tmp_path))
    assert "lint" not in [c["name"] for c in after["checks"]] and after["link"] == []
    assert cfg.validate(after) is after  # the default is itself a valid config


def test_declared_above_sees_only_explicit_declarations(tmp_path):
    inner = tmp_path / "a" / "b"
    inner.mkdir(parents=True)
    (tmp_path / "pytest.ini").write_text("")
    (tmp_path / "tests").mkdir()
    assert cfg.declared_above(str(inner)) is False  # a stack guess of an ancestor gates nothing
    make_exec(tmp_path / "scripts" / "gate.sh")
    assert cfg.declared_above(str(inner)) is True
    (tmp_path / "scripts" / "gate.sh").unlink()
    (tmp_path / ".zetetic").mkdir()
    (tmp_path / ".zetetic" / "gate.json").write_text("{broken")
    assert cfg.declared_above(str(inner)) is True  # an invalid config is still a declaration


def test_python_stack_needs_both_a_project_and_tests(tmp_path):
    (tmp_path / "pytest.ini").write_text("")
    assert cfg.stack_config(str(tmp_path)) is None  # a project without tests
    (tmp_path / "test_a.txt").write_text("")
    assert cfg.stack_config(str(tmp_path)) is None  # a file that is not a test module
    (tmp_path / "test_a.py").write_text("")
    assert cfg.stack_config(str(tmp_path))["checks"][0]["argv"][-3:] == ["-m", "pytest", "-q"]  # root-level test module
    (tmp_path / "test_a.py").unlink()
    (tmp_path / "pytest.ini").unlink()
    (tmp_path / "tests").mkdir()
    assert cfg.stack_config(str(tmp_path)) is None  # tests without a project


def test_test_globs_expand_against_the_tree_and_same_name_is_opt_in(tmp_path):
    tree(tmp_path, "a.py", "tests/test_a.py", "tests/test_b.py", "tests/test_c.py", "tests/test_smoke.py")
    mapped = cfg.validate({"version": 1, "tests": {"argv": ["pytest", "{tests}"], "fast": ["tests/test_smoke.py"],
                                                     "map": [{"paths": ["lib/**"], "tests": ["tests/test_b*.py", "tests/test_*.py"]}]}})
    # a glob map entry expands to every match; no same_name key: the same-named test is NOT guessed
    steps = cfg.plan(mapped, tmp_path, ["lib/x.py"])
    assert sorted(steps[0].argv[1:]) == ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py", "tests/test_smoke.py"]
    assert cfg.plan(mapped, tmp_path, ["a.py"]) == [cfg.Step("tests", ["pytest", "tests/test_smoke.py"])]


def test_a_missing_literal_test_is_not_selected(tmp_path):
    only = cfg.validate({"version": 1, "tests": {"argv": ["pytest", "{tests}"], "fast": ["tests/test_smoke.py"],
                                                   "map": [{"paths": ["lib/**"], "tests": ["tests/test_gone.py"]}]}})
    assert cfg.plan(only, tmp_path, ["lib/x.py"]) == [cfg.Step("tests-full", ["pytest"])]  # nothing exists: whole suite


# --------------------------------------------------- rules read from a tree object, not from the working copy


def committed(tmp_path: Path, files: dict, mode: dict | None = None) -> tuple:
    """(repo, tree id) of a repository whose single commit holds ``files``; ``mode`` maps a name to its chmod."""
    from gate_support import git
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
        (repo / name).chmod((mode or {}).get(name, 0o644))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "c", "--no-verify")
    return repo, git(repo, "rev-parse", "HEAD^{tree}")


def test_a_tree_source_answers_what_a_directory_does(tmp_path):
    import gate_source as src
    files = {".zetetic/gate.json": json.dumps({"version": 1, "checks": [LINT]}), "package.json": '{"scripts": {"test": "t"}}'}
    repo, tree_id = committed(tmp_path, files)
    for where in (str(repo), src.GitSource(str(repo), tree_id)):
        assert cfg.declaration(where) == "config" and cfg.load(where)["checks"] == [LINT]
        assert cfg.stack_config(where)["checks"][0]["argv"] == ["npm", "test", "--silent"]
    git_src = src.GitSource(str(repo), tree_id)
    assert git_src.isfile("package.json") and git_src.isdir(".zetetic") and not git_src.isfile(".zetetic")
    assert git_src.read("absent") is None and git_src.names() == [".zetetic", "package.json"]


def test_the_declaration_is_read_from_the_tree_not_the_working_copy(tmp_path):
    import gate_source as src
    repo, tree_id = committed(tmp_path, {".zetetic/gate.json": json.dumps({"version": 1, "checks": [LINT]})})
    (repo / ".zetetic" / "gate.json").write_text(json.dumps({"version": 1, "off": True}))  # edited, not committed
    assert cfg.declaration(str(repo)) is None  # the working copy says off ...
    assert cfg.declaration(src.GitSource(str(repo), tree_id)) == "config"  # ... the committed tree does not


def test_the_legacy_script_needs_the_executable_bit_in_the_tree(tmp_path):
    import gate_source as src
    repo, tree_id = committed(tmp_path, {"scripts/gate.sh": "#!/bin/sh\n"}, {"scripts/gate.sh": 0o755})
    assert cfg.declaration(src.GitSource(str(repo), tree_id)) == "legacy"
    plain, plain_tree = committed(tmp_path / "p", {"scripts/gate.sh": "#!/bin/sh\n"})
    assert cfg.declaration(src.GitSource(str(plain), plain_tree)) is None


def test_an_invalid_config_in_a_tree_is_a_config_error(tmp_path):
    import gate_source as src
    repo, tree_id = committed(tmp_path, {".zetetic/gate.json": "{torn"})
    with pytest.raises(cfg.ConfigError):
        cfg.declaration(src.GitSource(str(repo), tree_id))


def test_force_full_runs_everything_even_for_no_change_and_no_covering_path(tmp_path):
    root = tree(tmp_path, "a.py", "docs/x.md", "tests/test_a.py", "tests/test_docs.py")
    config_ = config()
    assert cfg.plan(config_, str(root), []) == []
    assert names(cfg.plan(config_, str(root), [], force_full=True)) == ["lint", "tests-full"]
    only_docs = cfg.plan(config_, str(root), ["docs/x.md"])
    assert names(only_docs) == ["tests"]  # affected-only: the map selects the docs test
    assert names(cfg.plan(config_, str(root), ["docs/x.md"], force_full=True)) == ["lint", "tests-full"]


def test_the_probed_paths_of_a_tree_cost_one_git_call_not_one_per_path(tmp_path, monkeypatch):
    import gate_git
    import gate_source as src
    repo, tree_id = committed(tmp_path, {".zetetic/gate.json": json.dumps({"version": 1, "checks": [LINT]}), "package.json": "{}"})
    calls = []
    real = gate_git.git
    monkeypatch.setattr(gate_git, "git", lambda *a, **k: calls.append(a) or real(*a, **k))
    source = src.GitSource(str(repo), tree_id, None, cfg.PROBE_PATHS)
    assert cfg.declaration(source) == "config" and cfg.load(source)["checks"] == [LINT]
    assert len(calls) == 1 and calls[0][1] == "ls-tree"  # every probed path answered by that one listing
    assert source.entry("never-probed") is None and len(calls) == 2  # a path outside the probe costs its own call


@pytest.mark.parametrize("bad", ["", "/abs/path", "../outside", "a/../b"])
def test_link_entries_must_be_paths_inside_the_repository(bad):
    with pytest.raises(cfg.ConfigError, match="link entries"):
        cfg.validate({"version": 1, "checks": [LINT], "link": [bad]})


def test_good_link_entries_and_env_are_accepted():
    assert cfg.validate({"version": 1, "checks": [LINT], "link": ["node_modules", "a/b"], "env": {"K": "v"}})["link"] == ["node_modules", "a/b"]
    with pytest.raises(cfg.ConfigError, match="env"):
        cfg.validate({"version": 1, "checks": [LINT], "env": {"K": 1}})


@pytest.mark.parametrize("text", ["{torn", "[1]", '"s"', "null"])
def test_a_malformed_package_json_is_not_an_npm_stack(tmp_path, text):
    (tmp_path / "package.json").write_text(text)
    assert cfg.stack_config(str(tmp_path)) is None


def test_a_blob_that_git_cannot_read_is_unavailable_not_a_crash(tmp_path):
    import gate_git
    import gate_source as src
    repo, _ = committed(tmp_path, {"a": "1\n"})
    with pytest.raises(gate_git.Unavailable, match="cannot read x"):
        src._blob(str(repo), "f" * 40, "x", None)
