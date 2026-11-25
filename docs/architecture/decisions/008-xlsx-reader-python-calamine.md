# ADR 008 — Read .xlsx uploads with python-calamine

- Status: **Accepted by the repository owner** (2026-11-24: "remove the custom Rust reader, change completely to python-calamine, do not use openpyxl" for reading; dependency approved 2026-11-24)
- Date: 2026-11-24
- Risk: T2 (new runtime dependency, AGENTS rule 7)
- Scope: `core/infrastructure/spreadsheets/xlsx.py` `read_workbook`; its only caller is Workbook Import (Check and Apply)

## Context

`read_workbook` used openpyxl in read-only mode. A Rust extension (`packages/native/xlsx-reader`, commit
`20ce23f`) was piloted to speed it up, and reverted in this change because:

- it handed every sheet with a date-formatted cell back to openpyxl, after doing its own work, so the usual
  file (our own export writes real dates) was about 16% *slower* than openpyxl;
- it relied on private openpyxl attributes and needed a Rust toolchain and a per-platform wheel build in CI
  and deploy.

## Decision

`read_workbook` reads with **python-calamine** (`python-calamine>=0.9.1,<0.10`). openpyxl stays only for
writing (`build_workbook`, `core/infrastructure/exports/excel.py`): calamine cannot write files.

The adapter keeps the `RawSheet` contract callers saw with openpyxl:

| Cell | calamine returns | `read_workbook` returns (as with openpyxl) |
|---|---|---|
| Empty | `""` | `None` |
| Whole number | `float` (`42.0`) | `int` (`42`) |
| Date at midnight | `date` | `datetime` |
| Error (`#DIV/0!`, `#N/A`) | `""` | the error text; read from the worksheet XML only when the sheet contains `t="e"` |
| Row number | list position | Excel row number (`skip_empty_area=False` anchors the grid at A1) |

Unchanged: only worksheets (not chart sheets) whose name was asked for, hidden sheets included; cached
formula results; header trimming; blank-row skipping; `max_data_rows` and `truncated`; the 200 MB
unpacked-size limit before any parsing.

## Dependency record (AGENTS rule 7)

- **Purpose:** faster upload parsing. Measured with `read_workbook` on 5,000 rows: 20 columns 579 → 133 ms,
  60 columns with a date column 1,736 → 375 ms (4.3–4.8×), identical `RawSheet` output to the old reader.
- **Alternatives considered:** keep openpyxl (slower); the custom Rust reader (reverted, see Context).
- **Maintenance owner:** Backend Platform (owns `core/infrastructure/spreadsheets`). python-calamine ships
  prebuilt abi3 wheels, so no Rust toolchain is needed in CI or deploy.

## Consequences

- A malformed worksheet now raises `SpreadsheetUnreadable` (a 400 `validation_failed` response) instead of an
  unhandled `xml.etree.ElementTree.ParseError` (500).
- A zip that is not an OOXML package (for example an `.ods`) is refused as before: the package relationships
  are required.
- Numbers come back from a float, so integers above 2^53 lose precision. Excel itself stores numbers as
  doubles, so a file saved by Excel cannot hold them either.
- A cell holding `1.0` written by a tool other than Excel reads as `1` (openpyxl returned `1.0`). The importer
  already treats whole floats as integers (`workbook_import/application/cells.py`).
- The reader is about 0.2% of an import's time; a 2,000-row Check takes about 85 s because of per-row queries
  and Python constraint validation. That is a separate, larger task.
