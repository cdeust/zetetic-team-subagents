"""The Cobertura coverage reader (tools/ci_coverage.py): line-rate against a
threshold. Design: docs/superpowers/specs/2026-10-22-single-ci-design.md,
"Repository contract: ci.json" (90 % of lines, enforced in the unit step)."""
from __future__ import annotations

import pytest

from tools import ci_coverage


def cobertura(tmp_path, line_rate: str):
    path = tmp_path / "coverage.xml"
    path.write_text(f'<?xml version="1.0" ?>\n<coverage line-rate="{line_rate}" branch-rate="0" version="7.0">'
                    "<packages/></coverage>\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("rate, percent", [("0.899", "89.90"), ("0.9", "90.00"), ("1.0", "100.00"), ("0.8995", "89.95")])
def test_the_line_rate_is_read_as_a_percentage(tmp_path, rate, percent):
    assert ci_coverage.percent(cobertura(tmp_path, rate)) == ci_coverage.Decimal(percent)


def test_eighty_nine_point_nine_fails_the_default_threshold(tmp_path, capsys):
    assert ci_coverage.main([str(cobertura(tmp_path, "0.899"))]) == 1
    assert capsys.readouterr().out.strip() == "coverage: 89.90% of lines, under the minimum 90.00%"


def test_ninety_passes_the_default_threshold(tmp_path, capsys):
    assert ci_coverage.main([str(cobertura(tmp_path, "0.9"))]) == 0
    assert capsys.readouterr().out.strip() == "coverage: 90.00% of lines, minimum 90.00%"


def test_one_hundred_passes(tmp_path):
    assert ci_coverage.main([str(cobertura(tmp_path, "1.0"))]) == 0


def test_the_threshold_is_an_option(tmp_path):
    path = cobertura(tmp_path, "0.5")
    assert ci_coverage.main([str(path), "--min", "50"]) == 0
    assert ci_coverage.main([str(path), "--min", "50.1"]) == 1


def test_an_absent_file_is_an_error_not_a_pass(tmp_path, capsys):
    assert ci_coverage.main([str(tmp_path / "coverage.xml")]) == 2
    assert capsys.readouterr().err.strip() == f"{tmp_path / 'coverage.xml'}: no such file"


def test_malformed_xml_is_an_error(tmp_path, capsys):
    path = tmp_path / "coverage.xml"
    path.write_text("<coverage line-rate=", encoding="utf-8")
    assert ci_coverage.main([str(path)]) == 2
    assert "not well-formed" in capsys.readouterr().err


@pytest.mark.parametrize("xml", ['<report line-rate="1.0"/>', "<coverage/>", '<coverage line-rate="high"/>'])
def test_a_document_without_a_numeric_root_line_rate_is_an_error(tmp_path, xml):
    path = tmp_path / "coverage.xml"
    path.write_text(xml, encoding="utf-8")
    with pytest.raises(ci_coverage.CoverageError):
        ci_coverage.percent(path)
