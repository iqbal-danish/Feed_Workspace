use std::fs::File;
use std::io::{BufRead, BufReader, Seek, SeekFrom};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RustContextLine {
    pub line_number: usize,
    pub text: String,
    pub is_error_line: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RustValidationError {
    pub error_number: usize,
    pub line: usize,
    pub column: usize,
    pub byte_offset: u64,
    pub message: String,
    pub category: String,
    pub severity: String,
    pub context_lines: Vec<RustContextLine>,
    pub tag_name: String,
    pub reference_tag: String,
    pub reference_line: usize,
}

struct TagOpenInfo {
    name: String,
    line: usize,
    column: usize,
}

/// Linear scan validator for strict XML syntax, tag nesting, and HTML boolean attribute detection
pub fn validate_xml_file(
    file_path: &str,
    max_errors: usize,
    context_window: usize,
) -> Result<Vec<RustValidationError>, String> {
    let file = File::open(file_path).map_err(|e| format!("Cannot open file '{file_path}': {e}"))?;
    let mut reader = BufReader::with_capacity(128 * 1024, file);

    let mut errors = Vec::new();
    let mut stack: Vec<TagOpenInfo> = Vec::with_capacity(64);

    let mut line_num = 1usize;
    let mut byte_offset = 0u64;
    let mut in_cdata = false;
    let mut in_comment = false;

    let mut line_buf = Vec::with_capacity(4096);

    loop {
        line_buf.clear();
        let bytes_read = reader.read_until(b'\n', &mut line_buf)
            .map_err(|e| format!("Read error at line {line_num}: {e}"))?;

        if bytes_read == 0 {
            break;
        }

        let line_len = line_buf.len();
        let line_str = String::from_utf8_lossy(&line_buf);
        let chars: Vec<char> = line_str.chars().collect();
        let mut idx = 0;

        while idx < chars.len() {
            let ch = chars[idx];

            if in_comment {
                if ch == '-' && idx + 2 < chars.len() && chars[idx + 1] == '-' && chars[idx + 2] == '>' {
                    in_comment = false;
                    idx += 3;
                    continue;
                }
                idx += 1;
                continue;
            }

            if in_cdata {
                if ch == ']' && idx + 2 < chars.len() && chars[idx + 1] == ']' && chars[idx + 2] == '>' {
                    in_cdata = false;
                    idx += 3;
                    continue;
                }
                idx += 1;
                continue;
            }

            // Check start of comment <!--
            if ch == '<' && idx + 3 < chars.len() && chars[idx + 1] == '!' && chars[idx + 2] == '-' && chars[idx + 3] == '-' {
                in_comment = true;
                idx += 4;
                continue;
            }

            // Check start of CDATA <![CDATA[
            if ch == '<' && idx + 8 < chars.len() && line_str[idx..].starts_with("<![CDATA[") {
                in_cdata = true;
                idx += 9;
                continue;
            }

            // Check XML declaration <?xml ... ?> or processing instruction
            if ch == '<' && idx + 1 < chars.len() && chars[idx + 1] == '?' {
                if let Some(end_pos) = line_str[idx..].find("?>") {
                    idx += end_pos + 2;
                } else {
                    idx += 2;
                }
                continue;
            }

            // Check Doctype <!DOCTYPE ... >
            if ch == '<' && idx + 1 < chars.len() && chars[idx + 1] == '!' {
                if let Some(end_pos) = line_str[idx..].find('>') {
                    idx += end_pos + 1;
                } else {
                    idx += 2;
                }
                continue;
            }

            // Check Closing tag </tag>
            if ch == '<' && idx + 1 < chars.len() && chars[idx + 1] == '/' {
                let tag_start_col = idx + 1;
                let rest = &line_str[idx + 2..];
                if let Some(end_pos) = rest.find('>') {
                    let tag_content = rest[..end_pos].trim();
                    let tag_name = tag_content.split_whitespace().next().unwrap_or("").to_string();

                    if let Some(last) = stack.pop() {
                        if last.name != tag_name {
                            let err_num = errors.len() + 1;
                            errors.push(RustValidationError {
                                error_number: err_num,
                                line: line_num,
                                column: tag_start_col,
                                byte_offset: byte_offset + (idx as u64),
                                message: format!("Opening and ending tag mismatch: <{}> on line {} and </{}>", last.name, last.line, tag_name),
                                category: "Tag Mismatch".to_string(),
                                severity: "Fatal".to_string(),
                                context_lines: extract_context(file_path, line_num, context_window),
                                tag_name: tag_name.clone(),
                                reference_tag: last.name.clone(),
                                reference_line: last.line,
                            });
                            if errors.len() >= max_errors {
                                return Ok(errors);
                            }
                        }
                    } else {
                        let err_num = errors.len() + 1;
                        errors.push(RustValidationError {
                            error_number: err_num,
                            line: line_num,
                            column: tag_start_col,
                            byte_offset: byte_offset + (idx as u64),
                            message: format!("Closing tag </{}> without matching opening tag", tag_name),
                            category: "Tag Mismatch".to_string(),
                            severity: "Fatal".to_string(),
                            context_lines: extract_context(file_path, line_num, context_window),
                            tag_name: tag_name.clone(),
                            reference_tag: String::new(),
                            reference_line: 0,
                        });
                        if errors.len() >= max_errors {
                            return Ok(errors);
                        }
                    }

                    idx += 2 + end_pos + 1;
                    continue;
                }
            }

            // Check Opening / Empty tag <tag attr="val"> or <tag boolean_attr>
            if ch == '<' && idx + 1 < chars.len() && (chars[idx + 1].is_alphabetic() || chars[idx + 1] == '_') {
                let tag_start_col = idx + 1;
                let rest = &line_str[idx + 1..];
                if let Some(end_pos) = rest.find('>') {
                    let full_tag = &rest[..end_pos];
                    let is_self_closing = full_tag.ends_with('/');
                    let tag_body = if is_self_closing {
                        &full_tag[..full_tag.len() - 1]
                    } else {
                        full_tag
                    }.trim();

                    // Parse tag name and attributes
                    let mut tokens = tag_body.split_whitespace();
                    let tag_name = tokens.next().unwrap_or("").to_string();

                    // Check attribute well-formedness in the tag
                    let attr_str = if tag_body.len() > tag_name.len() {
                        tag_body[tag_name.len()..].trim()
                    } else {
                        ""
                    };

                    if !attr_str.is_empty() {
                        if let Some(attr_err) = check_xml_attributes(attr_str) {
                            let err_num = errors.len() + 1;
                            errors.push(RustValidationError {
                                error_number: err_num,
                                line: line_num,
                                column: tag_start_col,
                                byte_offset: byte_offset + (idx as u64),
                                message: format!("Specification mandate value for attribute {attr_err} in <{tag_name}>"),
                                category: "Invalid Attribute".to_string(),
                                severity: "Fatal".to_string(),
                                context_lines: extract_context(file_path, line_num, context_window),
                                tag_name: tag_name.clone(),
                                reference_tag: String::new(),
                                reference_line: 0,
                            });
                            if errors.len() >= max_errors {
                                return Ok(errors);
                            }
                        }
                    }

                    if !is_self_closing {
                        stack.push(TagOpenInfo {
                            name: tag_name,
                            line: line_num,
                            column: tag_start_col,
                        });
                    }

                    idx += 1 + end_pos + 1;
                    continue;
                }
            }

            idx += 1;
        }

        byte_offset += line_len as u64;
        line_num += 1;
    }

    // Check unclosed tags at EOF
    if let Some(unclosed) = stack.last() {
        let err_num = errors.len() + 1;
        errors.push(RustValidationError {
            error_number: err_num,
            line: unclosed.line,
            column: unclosed.column,
            byte_offset,
            message: format!("Unclosed tag <{}> opened on line {}", unclosed.name, unclosed.line),
            category: "Tag Mismatch".to_string(),
            severity: "Fatal".to_string(),
            context_lines: extract_context(file_path, unclosed.line, context_window),
            tag_name: unclosed.name.clone(),
            reference_tag: String::new(),
            reference_line: 0,
        });
    }

    Ok(errors)
}

/// Checks that all attributes in a tag follow XML specification name="value" or name='value'
fn check_xml_attributes(attr_str: &str) -> Option<String> {
    let mut chars = attr_str.chars().peekable();
    while let Some(&ch) = chars.peek() {
        if ch.is_whitespace() {
            chars.next();
            continue;
        }

        // Read attribute name
        let mut name = String::new();
        while let Some(&c) = chars.peek() {
            if c == '=' || c.is_whitespace() || c == '/' || c == '>' {
                break;
            }
            name.push(c);
            chars.next();
        }

        if name.is_empty() {
            break;
        }

        // Skip whitespace before '='
        while let Some(&c) = chars.peek() {
            if c.is_whitespace() {
                chars.next();
            } else {
                break;
            }
        }

        // Next character MUST be '=' in well-formed XML
        if chars.peek() != Some(&'=') {
            // Unquoted/boolean attribute found! (e.g. <div control>)
            return Some(name);
        }
        chars.next(); // Consume '='

        // Skip whitespace after '='
        while let Some(&c) = chars.peek() {
            if c.is_whitespace() {
                chars.next();
            } else {
                break;
            }
        }

        // Next character MUST be quote '"' or '\''
        match chars.next() {
            Some('"') => {
                // Read until next unescaped '"'
                for c in chars.by_ref() {
                    if c == '"' {
                        break;
                    }
                }
            }
            Some('\'') => {
                // Read until next unescaped '\''
                for c in chars.by_ref() {
                    if c == '\'' {
                        break;
                    }
                }
            }
            _ => {
                // Unquoted attribute value (e.g. width=100)
                return Some(name);
            }
        }
    }
    None
}

/// Extracts surrounding context lines from file around an error
fn extract_context(file_path: &str, error_line: usize, window: usize) -> Vec<RustContextLine> {
    let mut context = Vec::new();
    let Ok(file) = File::open(file_path) else {
        return context;
    };
    let mut reader = BufReader::new(file);

    let start_line = error_line.saturating_sub(window).max(1);
    let end_line = error_line + window;

    let mut current_line = 1;
    let mut line_buf = String::new();

    while reader.read_line(&mut line_buf).unwrap_or(0) > 0 {
        if current_line >= start_line && current_line <= end_line {
            let clean_text = line_buf.trim_end_matches(&['\r', '\n'][..]).to_string();
            context.push(RustContextLine {
                line_number: current_line,
                text: clean_text,
                is_error_line: current_line == error_line,
            });
        }
        if current_line > end_line {
            break;
        }
        line_buf.clear();
        current_line += 1;
    }

    context
}
