"""gate_superset.weakenings on data: every weakening form of tests/test_gate_rule_floor.py, in process.

The end-to-end file proves the hook denies each form; this one is the fast, exact statement of the relation (and
what the mutation sweep of gate_superset runs against). A form is a function BASE -> the weakened config.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

from test_gate_rule_floor import BASE, WEAKENINGS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
import gate_rules as rules  # noqa: E402
import gate_superset as superset  # noqa: E402


def rule_set(config: dict, kind: str = "config") -> rules.RuleSet:
    return rules.RuleSet(kind, config, None)


def declared(config: dict) -> rules.RuleSet | None:
    """What gate_rules.of_tree makes of a config: `"off": true` declares nothing."""
    return None if config.get("off") else rule_set(config)


@pytest.mark.parametrize("form", sorted(WEAKENINGS))
def test_every_weakening_form_is_named(form):
    change, fragment = WEAKENINGS[form]
    weakened = superset.weakenings(rule_set(BASE), declared(change(BASE)))
    assert weakened and any(fragment in w for w in weakened), (form, weakened)


def test_no_declaration_is_a_weakening_of_every_part_and_names_them_all():
    weakened = superset.weakenings(rule_set(BASE), None)
    text = "\n".join(weakened)
    for part in ("gate.json", '"always"', '"scoped"', "tests were removed", "Makefile", "pyproject.toml", "env changed", '"ratchet"'):
        assert part in text, part


def test_a_name_is_not_a_rule():
    renamed = copy.deepcopy(BASE)
    renamed["checks"][0]["name"] = "another name"
    assert superset.weakenings(rule_set(BASE), rule_set(renamed)) == []


def test_a_pathless_check_is_covered_only_by_a_pathless_one():
    scoped = copy.deepcopy(BASE)
    scoped["checks"][0]["paths"] = ["**"]
    assert superset.weakenings(rule_set(BASE), rule_set(scoped))  # `**` does not match a deletion
    assert superset.weakenings(rule_set(scoped), rule_set(BASE)) == []  # the reverse widens the selection


def test_double_star_covers_any_selection():
    widened = copy.deepcopy(BASE)
    widened["checks"][1]["paths"] = ["**"]
    assert superset.weakenings(rule_set(BASE), rule_set(widened)) == []


def test_a_check_may_be_replaced_by_two_that_together_keep_it():
    split = copy.deepcopy(BASE)
    split["checks"].append(copy.deepcopy(split["checks"][1]))
    split["checks"][1]["name"] = "again"
    assert superset.weakenings(rule_set(BASE), rule_set(split)) == []


def test_a_map_pattern_may_move_between_entries_while_its_tests_are_kept():
    moved = copy.deepcopy(BASE)
    moved["tests"]["map"] = [{"paths": ["src/**"], "tests": ["tests/test_src.py"]},
                             {"paths": ["lib/**", "src/**"], "tests": ["tests/test_lib.py", "tests/test_src.py"]}]
    assert superset.weakenings(rule_set(BASE), rule_set(moved)) == []


def test_the_empty_fast_list_of_the_old_rules_may_not_become_a_list():
    old = copy.deepcopy(BASE)
    old["tests"]["fast"] = []
    new = copy.deepcopy(BASE)
    assert superset.weakenings(rule_set(old), rule_set(new))  # an empty `fast` meant: the whole suite
    assert superset.weakenings(rule_set(old), rule_set(old)) == []


def test_the_sentence_says_whether_a_check_was_removed_or_replaced():
    replaced = copy.deepcopy(BASE)
    replaced["checks"][0]["argv"] = ["other"]
    assert superset.weakenings(rule_set(BASE), rule_set(replaced)) == ['check "always" was replaced (argv, paths or scope differ)']
    removed = copy.deepcopy(BASE)
    del removed["checks"][0]
    assert superset.weakenings(rule_set(BASE), rule_set(removed)) == ['check "always" was removed']


def test_the_sentence_says_why_the_fast_list_changed():
    empty = copy.deepcopy(BASE)
    empty["tests"]["fast"] = []
    shrunk = copy.deepcopy(BASE)
    shrunk["tests"]["fast"] = ["tests/test_other.py"]
    (was_empty,) = superset.weakenings(rule_set(empty), rule_set(BASE))
    (lost,) = superset.weakenings(rule_set(BASE), rule_set(shrunk))
    assert "it was empty" in was_empty and "an entry was removed" in lost
