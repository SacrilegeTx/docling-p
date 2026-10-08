from openpyxl import Workbook

from xlsx_markdown import convert_xlsx_to_markdown


def build_workbook(path, sheets):
    """Save a workbook where `sheets` maps sheet name -> list of rows."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    workbook.save(path)


def convert(tmp_path, sheets, stem="report"):
    source = tmp_path / f"{stem}.xlsx"
    output = tmp_path / f"{stem}.md"
    build_workbook(source, sheets)
    convert_xlsx_to_markdown(source, output)
    return output.read_text(encoding="utf-8")


def table_rows(markdown):
    """Parse pipe tables into rows of cells (header and separator included)."""
    rows = []
    for line in markdown.splitlines():
        if line.startswith("|"):
            rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def data_rows(markdown):
    """Table rows without the header and the `---` separator line."""
    return table_rows(markdown)[2:]


def test_single_sheet_renders_title_and_table_without_sheet_heading(tmp_path):
    markdown = convert(
        tmp_path,
        {"Data": [["name", "qty"], ["apple", 3], ["pear", 5]]},
        stem="inventory",
    )

    assert markdown.startswith("# inventory\n")
    assert "## Hoja:" not in markdown
    rows = table_rows(markdown)
    assert rows[0] == ["name", "qty"]
    assert ["apple", "3"] in rows
    assert ["pear", "5"] in rows


def test_multiple_sheets_get_one_heading_each_in_workbook_order(tmp_path):
    markdown = convert(
        tmp_path,
        {
            "Zeta": [["a"], ["z1"]],
            "Alpha": [["b"], ["a1"]],
        },
    )

    headings = [line for line in markdown.splitlines() if line.startswith("## ")]
    assert headings == ["## Hoja: Zeta", "## Hoja: Alpha"]
    zeta, alpha = markdown.index("## Hoja: Zeta"), markdown.index("## Hoja: Alpha")
    assert zeta < markdown.index("z1") < alpha < markdown.index("a1")


def test_fully_empty_rows_and_columns_are_dropped(tmp_path):
    markdown = convert(
        tmp_path,
        {
            "Data": [
                ["a", None, "b"],
                [1, None, 2],
                [None, None, None],
                [3, None, 4],
            ]
        },
    )

    rows = table_rows(markdown)
    assert all(len(row) == 2 for row in rows)
    assert len(data_rows(markdown)) == 2
    assert ["1", "2"] in rows
    assert ["3", "4"] in rows


def test_empty_sheet_in_multi_sheet_workbook_is_marked_empty(tmp_path):
    markdown = convert(
        tmp_path,
        {
            "Full": [["a"], ["x"]],
            "Blank": [],
        },
    )

    blank_section = markdown.split("## Hoja: Blank")[1]
    assert "_(hoja vacía)_" in blank_section
    assert "|" not in blank_section


def test_column_without_header_keeps_its_values(tmp_path):
    markdown = convert(
        tmp_path,
        {"Data": [["name", None], ["apple", "headless-1"], ["pear", "headless-2"]]},
    )

    assert "headless-1" in markdown
    assert "headless-2" in markdown
    assert all(len(row) == 2 for row in table_rows(markdown))


def test_output_ends_with_exactly_one_trailing_newline(tmp_path):
    markdown = convert(
        tmp_path,
        {"One": [["a"], ["x"]], "Two": [["b"], ["y"]]},
    )

    assert markdown.endswith("\n")
    assert not markdown.endswith("\n\n")
