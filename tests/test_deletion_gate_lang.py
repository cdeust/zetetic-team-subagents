"""Unit tests for tools/deletion_gate_lang.py — language registry and
top-level-definition extraction.

Pure text-in/dict-out functions, no git, no I/O: every branch is reachable
from a string fixture. Imported dotted (tools.deletion_gate_lang) per
mutmut's trampoline-matching requirement (see tests/test_manifest_gate.py).
"""
from __future__ import annotations

import tools.deletion_gate_lang as dgl


# ── detect_lang ──────────────────────────────────────────────────────────────

def test_detect_lang_recognizes_every_registered_extension():
    assert dgl.detect_lang("a.py") == "python"
    assert dgl.detect_lang("a.ts") == "javascript"
    assert dgl.detect_lang("a.tsx") == "javascript"
    assert dgl.detect_lang("a.mjs") == "javascript"
    assert dgl.detect_lang("a.rs") == "rust"
    assert dgl.detect_lang("a.sh") == "shell"
    assert dgl.detect_lang("a.bash") == "shell"


def test_detect_lang_returns_none_for_unregistered_extension():
    assert dgl.detect_lang("a.md") is None
    assert dgl.detect_lang("a.txt") is None
    assert dgl.detect_lang("Makefile") is None


# ── extract_definitions: python (indent family) ─────────────────────────────

def test_python_extracts_top_level_function_and_class_only():
    text = (
        "def top(x):\n"
        "    return x\n"
        "\n"
        "class Foo:\n"
        "    def method(self):\n"
        "        return 1\n"
        "\n"
        "async def other():\n"
        "    pass\n"
    )
    defs = dgl.extract_definitions(text, "python")
    assert set(defs) == {"top", "Foo", "other"}
    assert defs["Foo"][0] == "class"
    assert defs["top"][0] == "function"
    assert "method" not in defs  # nested, not top-level


def test_python_body_ends_at_next_column_zero_line():
    text = "def a():\n    return 1\ndef b():\n    return 2\n"
    defs = dgl.extract_definitions(text, "python")
    assert defs["a"][1] == "def a():\n    return 1"
    assert defs["b"][1] == "def b():\n    return 2"


def test_python_blank_lines_inside_body_do_not_terminate_it():
    text = "def a():\n    x = 1\n\n    return x\n"
    defs = dgl.extract_definitions(text, "python")
    assert "return x" in defs["a"][1]


# ── extract_definitions: brace family (js/rust/shell) ───────────────────────

def test_javascript_export_function_and_class_and_const():
    text = (
        "export function run(x) {\n  return x;\n}\n"
        "export class Widget {\n  method() {}\n}\n"
        "export const value = 1;\n"
    )
    defs = dgl.extract_definitions(text, "javascript")
    assert set(defs) == {"run", "Widget", "value"}
    assert defs["run"][0] == "function"
    assert defs["Widget"][0] == "class"
    assert defs["value"][0] == "const"


def test_rust_pub_fn_struct_enum():
    text = (
        "pub fn run(x: i32) -> i32 {\n    x\n}\n"
        "pub struct Point {\n    x: i32,\n}\n"
        "pub enum Color {\n    Red,\n}\n"
    )
    defs = dgl.extract_definitions(text, "rust")
    assert set(defs) == {"run", "Point", "Color"}


def test_shell_function_two_styles():
    text = (
        "emit() {\n  echo 1\n}\n"
        "function other {\n  echo 2\n}\n"
    )
    defs = dgl.extract_definitions(text, "shell")
    assert set(defs) == {"emit", "other"}


def test_brace_family_second_definition_is_independently_bounded():
    """Regression for the mutation-found defect: a broken closing-brace
    tracker over-extends the FIRST definition to EOF and silently drops
    every definition after it."""
    text = "helper() {\n  echo 1\n}\n\nemit_event() {\n  echo 2\n}\n"
    defs = dgl.extract_definitions(text, "shell")
    assert set(defs) == {"helper", "emit_event"}
    assert "emit_event" not in defs["helper"][1]


def test_brace_family_string_containing_braces_does_not_confuse_the_scanner():
    text = 'export function run() {\n  const s = "}";\n  return 1;\n}\n'
    defs = dgl.extract_definitions(text, "javascript")
    assert set(defs) == {"run"}


def test_brace_family_one_line_semicolon_statement_has_no_open_brace():
    text = "pub struct Marker;\npub fn run() {\n    1\n}\n"
    defs = dgl.extract_definitions(text, "rust")
    assert set(defs) == {"Marker", "run"}
    assert defs["Marker"][1] == "pub struct Marker;"


def test_brace_family_unterminated_block_bounds_at_eof_rather_than_raising():
    text = "export function broken() {\n  return 1;\n"  # no closing brace
    defs = dgl.extract_definitions(text, "javascript")
    assert "broken" in defs
    assert defs["broken"][1].endswith("return 1;")


def test_extract_definitions_returns_empty_for_text_with_no_definitions():
    assert dgl.extract_definitions("# just a comment\nx = 1\n", "python") == {}
