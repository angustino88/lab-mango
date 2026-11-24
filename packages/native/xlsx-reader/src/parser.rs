//! Decode the supported subset of a worksheet's XML. None delegates the sheet to openpyxl.
use quick_xml::{
    escape::resolve_predefined_entity,
    events::{BytesStart, Event},
    Reader,
};

const MAIN_NAMESPACE: &[u8] = b"http://schemas.openxmlformats.org/spreadsheetml/2006/main";
const MAX_ROW: usize = 1_048_576;
const MAX_COL: usize = 16_384;
const MAX_CELLS: usize = 1_000_000;
pub const MAX_XML_BYTES: usize = 32 * 1024 * 1024;

type XmlReader<'a> = Reader<&'a [u8]>;

#[derive(Debug, PartialEq)]
pub enum Cell {
    Text(String),
    Integer(i64),
    Float(f64),
    Boolean(bool),
    Shared(usize),
}

type Row = Vec<Option<Cell>>;

#[derive(Debug, Default, PartialEq)]
pub struct Worksheet {
    pub headers: Row,
    pub rows: Vec<(usize, Row)>,
    pub truncated: bool,
}

pub struct SheetOptions<'a> {
    pub header_row: usize,
    pub first_data_row: usize,
    pub max_data_rows: usize,
    pub last_row: Option<usize>,
    pub last_column: Option<usize>,
    pub date_styles: &'a [usize],
    pub shared_blanks: &'a [bool],
}

pub fn read_sheet(xml: &[u8], options: &SheetOptions<'_>) -> Option<Worksheet> {
    if xml.len() > MAX_XML_BYTES
        || options.header_row == 0
        || options.first_data_row <= options.header_row
    {
        return None;
    }
    std::str::from_utf8(xml).ok()?;
    let mut reader = Reader::from_reader(xml);
    reader.config_mut().expand_empty_elements = true;
    let root = loop {
        match next_tag(&mut reader)? {
            Event::Decl(decl) => {
                if decl.version().ok()?.as_ref() != b"1.0" {
                    return None;
                }
                if let Some(encoding) = decl.encoding() {
                    if !encoding.ok()?.eq_ignore_ascii_case(b"UTF-8") {
                        return None;
                    }
                }
            }
            Event::Start(tag) if tag.name().as_ref() == b"worksheet" => break tag,
            _ => return None,
        }
    };
    if attribute(&root, b"xmlns")?? != MAIN_NAMESPACE {
        return None;
    }
    loop {
        match next_tag(&mut reader)? {
            Event::Start(tag) if tag.name().as_ref() == b"sheetData" => {
                if tag.attributes().next().is_some() {
                    return None;
                }
                let sheet = read_rows(&mut reader, options)?;
                reader.read_to_end(root.name()).ok()?;
                return matches!(next_tag(&mut reader)?, Event::Eof).then_some(sheet);
            }
            Event::Start(tag) => {
                reader.read_to_end(tag.name()).ok()?;
            }
            _ => return None,
        }
    }
}

fn read_rows(reader: &mut XmlReader<'_>, options: &SheetOptions<'_>) -> Option<Worksheet> {
    let mut result = Worksheet::default();
    let mut previous_row = 0;
    loop {
        let tag = match next_tag(reader)? {
            Event::Start(tag) if tag.name().as_ref() == b"row" => tag,
            Event::End(tag) if tag.name().as_ref() == b"sheetData" => return Some(result),
            _ => return None,
        };
        let row = parse_index(attribute(&tag, b"r")??)?;
        if row <= previous_row || row > MAX_ROW || attribute(&tag, b"xmlns")?.is_some() {
            return None;
        }
        previous_row = row;
        if row == options.header_row {
            result.headers =
                read_row(reader, row, options.last_column.unwrap_or(MAX_COL), options)?;
            while result
                .headers
                .last()
                .is_some_and(|cell| options.is_blank(cell))
            {
                result.headers.pop();
            }
            continue;
        }
        if row > options.header_row && result.headers.is_empty() {
            return Some(result);
        }
        if row < options.first_data_row {
            reader.read_to_end(tag.name()).ok()?;
            continue;
        }
        if options.last_row.is_some_and(|last| row > last) {
            return Some(result);
        }
        let width = result.headers.len();
        let mut values = read_row(reader, row, width, options)?;
        if values.iter().all(|cell| options.is_blank(cell)) {
            continue;
        }
        if result.rows.len() >= options.max_data_rows {
            result.truncated = true;
            return Some(result);
        }
        if (result.rows.len() + 1) * width > MAX_CELLS {
            return None;
        }
        values.resize_with(width, || None);
        result.rows.push((row, values));
    }
}

fn read_row(
    reader: &mut XmlReader<'_>,
    row: usize,
    width: usize,
    options: &SheetOptions<'_>,
) -> Option<Row> {
    let mut values = Row::new();
    let mut previous_column = 0;
    loop {
        let tag = match next_tag(reader)? {
            Event::Start(tag) if tag.name().as_ref() == b"c" => tag,
            Event::End(tag) if tag.name().as_ref() == b"row" => return Some(values),
            _ => return None,
        };
        let column = column_number(attribute(&tag, b"r")??, row)?;
        if column <= previous_column || attribute(&tag, b"xmlns")?.is_some() {
            return None;
        }
        previous_column = column;
        let value = read_cell(reader, &tag, options)?;
        if column <= width {
            values.resize_with(column - 1, || None);
            values.push(value);
        }
    }
}

fn read_cell(
    reader: &mut XmlReader<'_>,
    tag: &BytesStart<'_>,
    options: &SheetOptions<'_>,
) -> Option<Option<Cell>> {
    let kind = attribute(tag, b"t")?.unwrap_or(b"n");
    let style = attribute(tag, b"s")?.map_or(Some(0), parse_index)?;
    let mut value = None;
    let mut seen_value = false;
    loop {
        match next_tag(reader)? {
            Event::Start(child) if child.name().as_ref() == b"f" => {
                reader.read_to_end(child.name()).ok()?;
            }
            Event::Start(child)
                if child.name().as_ref() == b"is" && kind == b"inlineStr" && !seen_value =>
            {
                if attribute(&child, b"xmlns")?.is_some() {
                    return None;
                }
                seen_value = true;
                let text = match next_tag(reader)? {
                    Event::Start(text) if text.name().as_ref() == b"t" => text,
                    _ => return None,
                };
                value = Some(Cell::Text(read_text(reader, &text)?));
                match next_tag(reader)? {
                    Event::End(end) if end.name() == child.name() => (),
                    _ => return None,
                }
            }
            Event::Start(child)
                if child.name().as_ref() == b"v" && kind != b"inlineStr" && !seen_value =>
            {
                seen_value = true;
                let text = read_text(reader, &child)?;
                if !text.is_empty() {
                    value = Some(decode_value(kind, style, options, text)?);
                }
            }
            Event::End(end) if end.name() == tag.name() => return Some(value),
            _ => return None,
        }
    }
}

fn decode_value(
    kind: &[u8],
    style: usize,
    options: &SheetOptions<'_>,
    text: String,
) -> Option<Cell> {
    match kind {
        b"n" if !options.date_styles.contains(&style) => {
            if text.contains(['.', 'e', 'E']) {
                text.parse().ok().map(Cell::Float)
            } else {
                text.parse().ok().map(Cell::Integer)
            }
        }
        b"b" => Some(Cell::Boolean(text.parse::<i64>().ok()? != 0)),
        b"str" | b"e" => Some(Cell::Text(text)),
        b"s" => {
            let index = text.parse().ok()?;
            (index < options.shared_blanks.len()).then_some(Cell::Shared(index))
        }
        // Date/time cells and rich inline text use openpyxl's existing converters.
        _ => None,
    }
}

fn read_text(reader: &mut XmlReader<'_>, tag: &BytesStart<'_>) -> Option<String> {
    let mut result = String::new();
    if attribute(tag, b"xmlns")?.is_some() {
        return None;
    }
    loop {
        match reader.read_event().ok()? {
            Event::Text(text) => result.push_str(&text.xml10_content().ok()?),
            Event::GeneralRef(reference) => {
                if let Some(value) = reference.resolve_char_ref().ok()? {
                    result.push(value);
                } else {
                    result.push_str(resolve_predefined_entity(&reference.decode().ok()?)?);
                }
            }
            Event::End(end) if end.name() == tag.name() => {
                return result.chars().all(is_xml_character).then_some(result);
            }
            _ => return None,
        }
    }
}

fn next_tag<'a>(reader: &mut XmlReader<'a>) -> Option<Event<'a>> {
    loop {
        match reader.read_event().ok()? {
            Event::Text(text) if text.as_ref().iter().all(u8::is_ascii_whitespace) => (),
            Event::Comment(_) => (),
            event => return Some(event),
        }
    }
}

fn attribute<'a>(tag: &'a BytesStart<'_>, name: &[u8]) -> Option<Option<&'a [u8]>> {
    match tag.try_get_attribute(name).ok()? {
        None => Some(None),
        Some(attribute) => match attribute.value {
            std::borrow::Cow::Borrowed(value) => Some(Some(value)),
            std::borrow::Cow::Owned(_) => None,
        },
    }
}

fn parse_index(bytes: &[u8]) -> Option<usize> {
    std::str::from_utf8(bytes).ok()?.parse().ok()
}

fn column_number(coordinate: &[u8], row: usize) -> Option<usize> {
    let letters = coordinate
        .iter()
        .take_while(|byte| byte.is_ascii_uppercase());
    let mut column = 0;
    let mut offset = 0;
    for &letter in letters {
        column = (column * 26) + usize::from(letter - b'A' + 1);
        if column > MAX_COL {
            return None;
        }
        offset += 1;
    }
    (column > 0 && parse_index(&coordinate[offset..])? == row).then_some(column)
}

impl SheetOptions<'_> {
    fn is_blank(&self, value: &Option<Cell>) -> bool {
        match value {
            None => true,
            Some(Cell::Text(text)) => is_blank_text(text),
            Some(Cell::Shared(index)) => self.shared_blanks[*index],
            _ => false,
        }
    }
}

pub fn is_blank_text(text: &str) -> bool {
    text.chars()
        .all(|ch| ch.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&ch))
}

fn is_xml_character(ch: char) -> bool {
    matches!(ch, '\t' | '\n' | '\r' | '\u{20}'..='\u{d7ff}' | '\u{e000}'..='\u{fffd}' | '\u{10000}'..='\u{10ffff}')
}

#[cfg(test)]
mod tests {
    use super::*;

    fn options() -> SheetOptions<'static> {
        SheetOptions {
            header_row: 2,
            first_data_row: 4,
            max_data_rows: 1,
            last_row: None,
            last_column: None,
            date_styles: &[3],
            shared_blanks: &[false, true],
        }
    }

    #[test]
    fn limits_non_empty_rows_and_preserves_sparse_coordinates() {
        let xml = br#"<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
            <sheetData>
                <row r="2"><c r="A2" t="s"><v>0</v></c><c r="B2" t="s"><v>1</v></c></row>
                <row r="4"><c r="A4" t="s"><v>1</v></c></row>
                <row r="7"><c r="A7" t="e"><v>#DIV/0!</v></c></row>
                <row r="9"><c r="A9"><v>42</v></c></row>
            </sheetData>
        </worksheet>"#;
        let sheet = read_sheet(xml, &options()).expect("supported worksheet");
        assert_eq!(sheet.headers, vec![Some(Cell::Shared(0))]);
        assert_eq!(
            sheet.rows,
            vec![(7, vec![Some(Cell::Text(String::from("#DIV/0!")))])]
        );
        assert!(sheet.truncated);
    }

    #[test]
    fn delegates_date_styles() {
        let xml = br#"<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
            <sheetData>
                <row r="2"><c r="A2" t="inlineStr"><is><t>Date</t></is></c></row>
                <row r="4"><c r="A4" s="3"><v>45000</v></c></row>
            </sheetData>
        </worksheet>"#;
        assert!(read_sheet(xml, &options()).is_none());
    }
}
