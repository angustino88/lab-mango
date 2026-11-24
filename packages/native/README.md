# Native Python extensions

Each Cargo workspace member owns one Python wheel. The extension handles bounded computation and returns values to a Python adapter. Feature commands own validation, authorization and persistence.

## XLSX reader pilot

`xlsx-reader` is imported as `xlsx_reader`. PyO3 exposes the worksheet parser to CPython, maturin builds the wheel, and quick-xml streams the worksheet's XML events. The Python adapter uses openpyxl to open the archive, resolve worksheet members and load shared strings and styles. It returns the existing `RawSheet` objects to Workbook Import. Check and Apply share that reader.

Backend Platform owns the native package and adapter. The Labs team owns Workbook Import and its contract tests. The existing openpyxl reader provides the baseline and handles worksheets outside the native parser's supported subset. `python-calamine` was considered, but the prototype changed integer types and mapped Excel error cells to blanks. Using the worksheet XML preserves numeric representations and error text while reusing openpyxl's workbook metadata.

The adapter uses openpyxl's private read-only worksheet stream, shared strings and date-style metadata. Changes to openpyxl should run the native parity tests. The adapter delegates a worksheet to openpyxl when those hooks are unavailable or the native parser encounters an unsupported representation, such as date-styled numbers or rich inline text. The existing archive limit applies before selecting a parser. The native reader also bounds the XML bytes and returned cells per worksheet and releases the GIL while decoding.

### Build and verify

With Rust, Cargo, and CPython 3.12 available, run from the repository root:

```sh
uv sync --frozen --extra native-xlsx
cargo test --locked --manifest-path packages/native/Cargo.toml
uv run --no-sync pytest packages/native/xlsx-reader/tests -q
```

For a standalone wheel, run `uvx maturin build --release --locked --manifest-path packages/native/xlsx-reader/Cargo.toml` with the target platform's build toolchain. Build on each supported platform and verify the installed artifact there before use.

### Select the reader

Set `XLSX_READER=native` in the backend process environment after installing the extra. Unset the variable to select openpyxl. An enabled pilot with a missing wheel raises a configuration error when a requested sheet is read. Benchmark the full import and memory under representative load before enabling the pilot in a deployment.
