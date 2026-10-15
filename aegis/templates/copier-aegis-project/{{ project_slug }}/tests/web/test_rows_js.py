"""How rows.js exports and sorts a table's rows (static/js/rows.js, run
in node): CSV quoted as spreadsheets read it, a cell a spreadsheet would
run as a formula made text, a Markdown table that stays one, numbers
sorted as numbers."""

from pathlib import Path

from tests.web.node import call, run

ROWS_JS = Path("app/components/web_frontend/static/js/rows.js")


def test_csv_quotes_what_needs_it_and_defuses_formulas() -> None:
    rows = [["a,b", 'say "hi"', "=1+1", "-5", "line\nbreak"]]
    assert call(ROWS_JS, f"c.toCsv(['x', 'y', 'z', 'n', 'l'], {rows})") == (
        'x,y,z,n,l\r\n"a,b","say ""hi""",\'=1+1,-5,"line\nbreak"'
    )


def test_markdown_escapes_its_pipes_and_keeps_a_row_a_line() -> None:
    rows = [["a|b", "two\nlines"]]
    assert call(ROWS_JS, f"c.toMarkdown(['x', 'y'], {rows})") == (
        "| x | y |\n| --- | --- |\n| a\\|b | two lines |"
    )


def test_numbers_sort_as_numbers_and_text_as_text() -> None:
    values = ["10", "9", "-2", "1.5", "b", "A"]
    assert call(ROWS_JS, f"{values}.sort(c.compare)") == [
        "-2",
        "1.5",
        "9",
        "10",
        "A",
        "b",
    ]


def test_json_keeps_two_columns_of_one_name() -> None:
    """A join's ``u.id, o.id``: an object keeps one key, so the second is
    named apart."""
    assert call(ROWS_JS, "c.toJson(['id', 'id', 'name'], [['1', '2', 'x']])") == (
        '[\n  {\n    "id": "1",\n    "id_2": "2",\n    "name": "x"\n  }\n]'
    )


def test_a_sorted_row_keeps_its_keys_line_under_it() -> None:
    """The line of where a row's keys lead moves with its row."""
    script = """
const c = require(ROWS_JS);
const row = (v) => ({ classList: { contains: (n) => n === 'log-row' }, cells: [{ textContent: v }], v });
const links = (v) => ({ classList: { contains: () => false }, cells: [], v });
const order = [];
const body = { children: [row('10'), links('10 keys'), row('9'), row('-2')], append: (...rows) => order.push(...rows.map((r) => r.v)) };
c.sortBody(body, 0, false);
console.log(JSON.stringify(order));
"""
    assert run(script, ROWS_JS=ROWS_JS) == ["-2", "9", "10", "10 keys"]
