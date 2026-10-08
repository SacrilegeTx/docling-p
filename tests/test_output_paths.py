from pathlib import Path

import pytest

from output_paths import markdown_output_name, resolve_paths


def test_markdown_name_keeps_the_source_extension():
    assert markdown_output_name(Path("Report.xlsx")) == "Report.xlsx.md"


def test_markdown_name_preserves_extension_case():
    assert markdown_output_name(Path("Scan.PDF")) == "Scan.PDF.md"


def test_markdown_name_keeps_every_dot_of_a_multi_dot_name():
    assert markdown_output_name(Path("a.b.pdf")) == "a.b.pdf.md"


def test_default_output_is_a_sibling_named_after_the_full_source_name(tmp_path):
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF")

    resolved_source, resolved_output = resolve_paths(source, None)

    assert resolved_source == source.resolve()
    assert resolved_output == source.resolve().with_name("input.pdf.md")


def test_same_stem_with_different_extensions_gets_distinct_outputs(tmp_path):
    pdf = tmp_path / "data.pdf"
    xlsx = tmp_path / "data.xlsx"
    pdf.write_bytes(b"%PDF")
    xlsx.write_bytes(b"PK")

    assert resolve_paths(pdf, None)[1] != resolve_paths(xlsx, None)[1]


def test_explicit_output_is_honored_and_parents_are_created(tmp_path):
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF")
    target = tmp_path / "nested" / "deeper" / "custom.md"

    _, resolved_output = resolve_paths(source, target)

    assert resolved_output == target.resolve()
    assert target.parent.is_dir()


def test_missing_input_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_paths(tmp_path / "missing.pdf", None)


def test_directory_input_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        resolve_paths(tmp_path, None)
