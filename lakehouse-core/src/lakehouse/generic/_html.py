"""Static HTML table extraction on the standard library only.

``pandas.read_html`` needs lxml, or html5lib together with BeautifulSoup. Three dependencies
to read a ``<table>`` is a poor trade when the standard library's ``html.parser`` already
does the tokenising, and the difference matters here for a reason beyond package count:
this module can state exactly what it does **not** do, because it is the whole implementation.

- No script is executed. ``<script>`` and ``<style>`` content is discarded as text.
- No external resource is requested. There is no URL handling in this file at all, so a
  ``<img src>``, ``<link>`` or ``<iframe>`` is inert by construction rather than by policy.
- No entity or DTD expansion beyond what ``html.parser`` does for named character references,
  so the billion-laughs class of attack has no surface here.

The trade is that a malformed page may extract differently than a browser would render it.
That is acceptable: this reads published data tables, not arbitrary web pages, and a page
that needs a browser to make sense of is out of scope anyway.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Final


MAX_TABLES: Final[int] = 200
MAX_ROWS: Final[int] = 1_000_000
MAX_COLUMNS: Final[int] = 4096
MAX_CELL_CHARS: Final[int] = 32_768

_IGNORED_TEXT_TAGS: Final[frozenset[str]] = frozenset({"script", "style"})
_CELL_TAGS: Final[frozenset[str]] = frozenset({"td", "th"})


class HtmlTableError(ValueError):
    """Raised when a document holds no usable table, or a limit is exceeded."""


class _Cell:
    __slots__ = ("text", "rowspan", "colspan", "header")

    def __init__(self, rowspan: int, colspan: int, header: bool) -> None:
        self.text: list[str] = []
        self.rowspan = rowspan
        self.colspan = colspan
        self.header = header

    def value(self) -> str:
        text = "".join(self.text)
        if len(text) > MAX_CELL_CHARS:
            raise HtmlTableError(f"a cell is longer than {MAX_CELL_CHARS} characters")
        return " ".join(text.split())


def _span(value: str | None) -> int:
    """Read a rowspan/colspan attribute, clamping anything hostile to 1."""

    try:
        span = int((value or "1").strip())
    except (TypeError, ValueError):
        return 1
    if span < 1:
        return 1
    return min(span, MAX_COLUMNS)


class _TableCollector(HTMLParser):
    """Collect every top-level table's cells, honouring rowspan and colspan."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[_Cell]]] = []
        self._table_stack: list[list[list[_Cell]]] = []
        self._row: list[_Cell] | None = None
        self._cell: _Cell | None = None
        self._ignore_depth = 0

    # -- tags ---------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _IGNORED_TEXT_TAGS:
            self._ignore_depth += 1
            return
        if self._ignore_depth:
            return
        attributes = dict(attrs)
        if tag == "table":
            if len(self.tables) + len(self._table_stack) >= MAX_TABLES:
                raise HtmlTableError(f"document holds more than {MAX_TABLES} tables")
            self._table_stack.append([])
            self._row = None
            self._cell = None
            return
        if not self._table_stack:
            return
        if tag == "tr":
            self._close_cell()
            self._row = []
            return
        if tag in _CELL_TAGS:
            self._close_cell()
            if self._row is None:
                # A cell outside any <tr>; treat it as opening one rather than dropping data.
                self._row = []
            if len(self._row) >= MAX_COLUMNS:
                raise HtmlTableError(f"a row holds more than {MAX_COLUMNS} cells")
            self._cell = _Cell(
                rowspan=_span(attributes.get("rowspan")),
                colspan=_span(attributes.get("colspan")),
                header=tag == "th",
            )

    def handle_endtag(self, tag: str) -> None:
        if tag in _IGNORED_TEXT_TAGS:
            self._ignore_depth = max(0, self._ignore_depth - 1)
            return
        if self._ignore_depth or not self._table_stack:
            return
        if tag in _CELL_TAGS:
            self._close_cell()
            return
        if tag == "tr":
            self._close_row()
            return
        if tag == "table":
            self._close_row()
            finished = self._table_stack.pop()
            if len(self.tables) >= MAX_TABLES:
                raise HtmlTableError(f"document holds more than {MAX_TABLES} tables")
            self.tables.append(finished)
            self._row = None
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._ignore_depth or self._cell is None:
            return
        self._cell.text.append(data)

    # -- helpers ------------------------------------------------------------

    def _close_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row.append(self._cell)
        self._cell = None

    def _close_row(self) -> None:
        self._close_cell()
        if self._row is not None and self._table_stack:
            table = self._table_stack[-1]
            if len(table) >= MAX_ROWS:
                raise HtmlTableError(f"a table holds more than {MAX_ROWS} rows")
            table.append(self._row)
        self._row = None


def _expand(rows: list[list[_Cell]]) -> list[list[str]]:
    """Turn spanned cells into a rectangular grid.

    A ``rowspan`` or ``colspan`` cell repeats its text into every position it covers. That is
    the interpretation a reader gets from a rendered table, and it keeps the grid rectangular
    so downstream code never has to reason about holes.
    """

    grid: list[list[str | None]] = []
    pending: dict[tuple[int, int], str] = {}

    for row_index, row in enumerate(rows):
        while len(grid) <= row_index:
            grid.append([])
        column = 0
        for cell in row:
            while (row_index, column) in pending:
                _place(grid, row_index, column, pending.pop((row_index, column)))
                column += 1
            text = cell.value()
            for row_offset in range(cell.rowspan):
                for column_offset in range(cell.colspan):
                    target_row = row_index + row_offset
                    target_column = column + column_offset
                    if row_offset == 0 and column_offset == 0:
                        _place(grid, target_row, target_column, text)
                    else:
                        pending[(target_row, target_column)] = text
            column += cell.colspan
        while (row_index, column) in pending:
            _place(grid, row_index, column, pending.pop((row_index, column)))
            column += 1

    # Anything still pending belongs to rows the table never opened; place it so a rowspan
    # running past the last <tr> does not silently drop a value.
    for (row_index, column), text in sorted(pending.items()):
        _place(grid, row_index, column, text)

    width = max((len(row) for row in grid), default=0)
    if width > MAX_COLUMNS:
        raise HtmlTableError(f"a table is wider than {MAX_COLUMNS} columns")
    return [[("" if value is None else value) for value in row] + [""] * (width - len(row)) for row in grid]


def _place(grid: list[list[str | None]], row: int, column: int, text: str) -> None:
    while len(grid) <= row:
        grid.append([])
    line = grid[row]
    while len(line) <= column:
        line.append(None)
    line[column] = text


def extract_tables(markup: str) -> list[list[list[str]]]:
    """Return every table in the document as a rectangular grid of strings."""

    collector = _TableCollector()
    collector.feed(markup)
    collector.close()
    # A document that ends mid-table still yields what it had.
    while collector._table_stack:  # noqa: SLF001 - same module
        collector._close_row()
        collector.tables.append(collector._table_stack.pop())
    return [_expand(rows) for rows in collector.tables]


__all__ = [
    "MAX_CELL_CHARS",
    "MAX_COLUMNS",
    "MAX_ROWS",
    "MAX_TABLES",
    "HtmlTableError",
    "extract_tables",
]
