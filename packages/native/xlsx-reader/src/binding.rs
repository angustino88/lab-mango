use crate::parser::{self, Cell, SheetOptions, Worksheet, MAX_XML_BYTES};
use pyo3::{
    prelude::*,
    types::{PyBytes, PyString, PyTuple},
    IntoPyObjectExt,
};

type PythonRow = Vec<Option<Py<PyAny>>>;
type PythonWorksheet = (PythonRow, Vec<(usize, PythonRow)>, bool);

/// Return the headers, indexed rows and truncation flag, or None if Python should read the sheet.
#[pyfunction]
fn read_sheet(
    py: Python<'_>,
    xml: &Bound<'_, PyBytes>,
    layout: (usize, usize, usize),
    dimensions: (Option<usize>, Option<usize>),
    date_styles: Vec<usize>,
    shared_strings: &Bound<'_, PyTuple>,
) -> PyResult<Option<PythonWorksheet>> {
    let bytes = xml.as_bytes();
    if bytes.len() > MAX_XML_BYTES {
        return Ok(None);
    }
    let shared_blanks = shared_strings
        .iter()
        .map(|value| Ok(parser::is_blank_text(&value.cast::<PyString>()?.to_cow()?)))
        .collect::<PyResult<Vec<_>>>()?;
    let (header_row, first_data_row, max_data_rows) = layout;
    let (last_row, last_column) = dimensions;
    let options = SheetOptions {
        header_row,
        first_data_row,
        max_data_rows,
        last_row,
        last_column,
        date_styles: &date_styles,
        shared_blanks: &shared_blanks,
    };
    let sheet = py.detach(|| parser::read_sheet(bytes, &options));
    sheet
        .map(|sheet| to_python(py, sheet, shared_strings))
        .transpose()
}

fn to_python(
    py: Python<'_>,
    sheet: Worksheet,
    shared_strings: &Bound<'_, PyTuple>,
) -> PyResult<PythonWorksheet> {
    let header = row_to_python(py, sheet.headers, shared_strings)?;
    let rows = sheet
        .rows
        .into_iter()
        .map(|(number, row)| Ok((number, row_to_python(py, row, shared_strings)?)))
        .collect::<PyResult<_>>()?;
    Ok((header, rows, sheet.truncated))
}

fn row_to_python(
    py: Python<'_>,
    row: Vec<Option<Cell>>,
    shared_strings: &Bound<'_, PyTuple>,
) -> PyResult<PythonRow> {
    row.into_iter()
        .map(|value| match value {
            Some(Cell::Text(text)) => text.into_py_any(py).map(Some),
            Some(Cell::Boolean(value)) => value.into_py_any(py).map(Some),
            Some(Cell::Integer(value)) => value.into_py_any(py).map(Some),
            Some(Cell::Float(value)) => value.into_py_any(py).map(Some),
            Some(Cell::Shared(index)) => Ok(Some(shared_strings.get_item(index)?.unbind())),
            None => Ok(None),
        })
        .collect()
}

#[pymodule]
fn xlsx_reader(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(read_sheet, module)?)?;
    module.add("MAX_XML_BYTES", MAX_XML_BYTES)?;
    Ok(())
}
