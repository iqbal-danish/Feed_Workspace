use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::io::{BufRead, BufReader, Read};
use quick_xml::events::Event;
use quick_xml::Reader;
use serde_json::{Map, Value};

/// Common container tags that wrap the list of jobs, not a single job
const ROOT_CONTAINERS: &[&str] = &[
    "root", "root-node", "source", "sources", "jobs", "jobfeed", "feed", "feeds",
    "channel", "rss", "document", "results", "response", "data", "catalog", "items",
    "postings", "vacancies", "openings", "positions", "listings", "records", "array"
];

/// Known job record keywords with priority weights
fn get_keyword_score(tag: &str) -> f64 {
    match tag {
        "job" => 100.0,
        "posting" | "position" | "vacancy" | "opening" => 90.0,
        "opportunity" | "listing" => 85.0,
        "career" | "offer" => 80.0,
        "item" | "entry" => 75.0,
        "record" | "requisition" => 70.0,
        "work" => 60.0,
        _ => 0.0,
    }
}

/// Helper reader that stops after reading `limit` bytes
struct LimitedReader<R> {
    inner: R,
    remaining: usize,
}

impl<R: Read> LimitedReader<R> {
    fn new(inner: R, limit: usize) -> Self {
        Self { inner, remaining: limit }
    }
}

impl<R: Read> Read for LimitedReader<R> {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        if self.remaining == 0 {
            return Ok(0);
        }
        let max_to_read = std::cmp::min(buf.len(), self.remaining);
        let bytes_read = self.inner.read(&mut buf[..max_to_read])?;
        self.remaining -= bytes_read;
        Ok(bytes_read)
    }
}

/// Strip XML namespace prefix (e.g. "ns2:job" -> "job")
#[inline]
fn strip_namespace(name: &str) -> &str {
    if let Some(pos) = name.rfind(':') {
        &name[pos + 1..]
    } else {
        name
    }
}

/// Detects the repeating job element tag in an XML file at blazing speed
pub fn detect_xml_job_element(file_path: &str, limit_bytes: usize) -> Result<String, String> {
    let file = File::open(file_path).map_err(|e| format!("Failed to open file: {e}"))?;
    let limited = LimitedReader::new(file, limit_bytes);
    let mut reader = Reader::from_reader(BufReader::with_capacity(64 * 1024, limited));
    reader.config_mut().trim_text(true);

    let mut buf = Vec::with_capacity(4096);
    let mut stack: Vec<String> = Vec::with_capacity(32);
    let mut tag_counts: HashMap<String, usize> = HashMap::new();
    let mut tag_depths: HashMap<String, usize> = HashMap::new();
    let mut tag_parents: HashMap<String, HashSet<String>> = HashMap::new();
    let mut tag_child_tags: HashMap<String, HashSet<String>> = HashMap::new();
    let mut exact_casing: HashMap<String, String> = HashMap::new();

    let root_containers_set: HashSet<&str> = ROOT_CONTAINERS.iter().copied().collect();

    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(e)) => {
                let raw_name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                let local_name = strip_namespace(&raw_name).to_string();
                let lower_name = local_name.to_lowercase();

                exact_casing.entry(lower_name.clone()).or_insert_with(|| local_name.clone());

                let depth = stack.len();
                if let Some(parent) = stack.last() {
                    tag_parents.entry(lower_name.clone())
                        .or_default()
                        .insert(parent.clone());
                    tag_child_tags.entry(parent.clone())
                        .or_default()
                        .insert(lower_name.clone());
                }

                tag_depths.entry(lower_name.clone())
                    .and_modify(|d| *d = std::cmp::min(*d, depth))
                    .or_insert(depth);

                stack.push(lower_name);
            }
            Ok(Event::End(e)) => {
                let raw_name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                let local_name = strip_namespace(&raw_name).to_string();
                let lower_name = local_name.to_lowercase();

                if let Some(pos) = stack.iter().rposition(|x| x == &lower_name) {
                    stack.truncate(pos);
                }
                *tag_counts.entry(lower_name).or_insert(0) += 1;
            }
            Ok(Event::Empty(e)) => {
                let raw_name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                let local_name = strip_namespace(&raw_name).to_string();
                let lower_name = local_name.to_lowercase();

                exact_casing.entry(lower_name.clone()).or_insert_with(|| local_name.clone());

                let depth = stack.len();
                if let Some(parent) = stack.last() {
                    tag_parents.entry(lower_name.clone())
                        .or_default()
                        .insert(parent.clone());
                    tag_child_tags.entry(parent.clone())
                        .or_default()
                        .insert(lower_name.clone());
                }

                tag_depths.entry(lower_name.clone())
                    .and_modify(|d| *d = std::cmp::min(*d, depth))
                    .or_insert(depth);

                *tag_counts.entry(lower_name).or_insert(0) += 1;
            }
            Ok(Event::Eof) => break,
            Err(_) => {
                // Ignore parse errors from truncation at limit_bytes
                break;
            }
            _ => {}
        }
        buf.clear();
    }

    // Score candidates
    let mut best_tag = "job".to_string();
    let mut best_score = -999999.0;

    for (tag, &count) in &tag_counts {
        let depth = *tag_depths.get(tag).unwrap_or(&1);
        let num_children = tag_child_tags.get(tag).map(|c| c.len()).unwrap_or(0);

        // Leaf tags cannot be the record container
        if num_children == 0 {
            continue;
        }
        // Root tag cannot be individual job
        if depth == 0 {
            continue;
        }

        let mut score = get_keyword_score(tag);

        if let Some(parents) = tag_parents.get(tag) {
            for parent in parents {
                if root_containers_set.contains(parent.as_str()) {
                    score += 50.0;
                }
                if parent == &format!("{tag}s") || parent == &format!("{tag}es") {
                    score += 80.0;
                }
                if get_keyword_score(parent) > 0.0 {
                    score -= 80.0; // Nested inside another job container
                }
            }
        }

        match depth {
            1 => score += 40.0,
            2 => score += 35.0,
            3 => score -= 40.0,
            _ => score -= 80.0,
        }

        score += ((num_children as f64) * 5.0).min(50.0);
        score += ((count as f64) + 1.0).log2() * 5.0;

        if score > best_score {
            best_score = score;
            best_tag = tag.clone();
        }
    }

    Ok(exact_casing.get(&best_tag).cloned().unwrap_or(best_tag))
}

/// Fast streaming XML record parser
pub struct XmlRecordStream<R: Read> {
    reader: Reader<BufReader<R>>,
    target_tag_lower: String,
    buf: Vec<u8>,
}

impl<R: Read> XmlRecordStream<R> {
    pub fn new(read: R, target_tag: &str) -> Self {
        let mut reader = Reader::from_reader(BufReader::with_capacity(128 * 1024, read));
        reader.config_mut().trim_text(true);
        Self {
            reader,
            target_tag_lower: target_tag.to_lowercase(),
            buf: Vec::with_capacity(8192),
        }
    }

    /// Read next record from stream into (JSON string, raw XML string)
    pub fn next_record(&mut self, store_raw: bool) -> Option<Result<(String, String), String>> {
        loop {
            match self.reader.read_event_into(&mut self.buf) {
                Ok(Event::Start(ref e)) => {
                    let raw_name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                    let local_name = strip_namespace(&raw_name);
                    if local_name.eq_ignore_ascii_case(&self.target_tag_lower) {
                        let mut raw_xml = String::new();
                        if store_raw {
                            raw_xml.push('<');
                            raw_xml.push_str(&String::from_utf8_lossy(e.as_ref()));
                            raw_xml.push('>');
                        }

                        let mut root_attrs = Map::new();
                        for attr in e.attributes().flatten() {
                            let key = String::from_utf8_lossy(attr.key.as_ref()).to_string();
                            let val = String::from_utf8_lossy(&attr.value).to_string();
                            root_attrs.insert(format!("@{key}"), Value::String(val));
                        }

                        let res = parse_element_children(&mut self.reader, &self.target_tag_lower, store_raw, &mut raw_xml);
                        match res {
                            Ok(mut map) => {
                                for (k, v) in root_attrs {
                                    map.insert(k, v);
                                }
                                let json_str = serde_json::to_string(&Value::Object(map))
                                    .unwrap_or_else(|_| "{}".to_string());
                                return Some(Ok((json_str, raw_xml)));
                            }
                            Err(err) => return Some(Err(err)),
                        }
                    }
                }
                Ok(Event::Empty(ref e)) => {
                    let raw_name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                    let local_name = strip_namespace(&raw_name);
                    if local_name.eq_ignore_ascii_case(&self.target_tag_lower) {
                        let mut map = Map::new();
                        for attr in e.attributes().flatten() {
                            let key = String::from_utf8_lossy(attr.key.as_ref()).to_string();
                            let val = String::from_utf8_lossy(&attr.value).to_string();
                            map.insert(format!("@{key}"), Value::String(val));
                        }
                        let raw_xml = if store_raw {
                            format!("<{}/>", String::from_utf8_lossy(e.as_ref()))
                        } else {
                            String::new()
                        };
                        let json_str = serde_json::to_string(&Value::Object(map))
                            .unwrap_or_else(|_| "{}".to_string());
                        return Some(Ok((json_str, raw_xml)));
                    }
                }
                Ok(Event::Eof) => return None,
                Err(err) => return Some(Err(format!("XML parse error: {err}"))),
                _ => {}
            }
            self.buf.clear();
        }
    }

    /// Read next pre-flattened record from stream
    pub fn next_flat_record(
        &mut self,
        store_raw: bool,
        skip_description: bool,
    ) -> Option<Result<(HashMap<String, String>, String), String>> {
        loop {
            match self.reader.read_event_into(&mut self.buf) {
                Ok(Event::Start(ref e)) => {
                    let raw_name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                    let local_name = strip_namespace(&raw_name);
                    if local_name.eq_ignore_ascii_case(&self.target_tag_lower) {
                        let mut raw_xml = String::new();
                        if store_raw {
                            raw_xml.push('<');
                            raw_xml.push_str(&String::from_utf8_lossy(e.as_ref()));
                            raw_xml.push('>');
                        }

                        let mut root_attrs = HashMap::new();
                        for attr in e.attributes().flatten() {
                            let key = String::from_utf8_lossy(attr.key.as_ref()).to_string();
                            let val = String::from_utf8_lossy(&attr.value).to_string();
                            root_attrs.insert(format!("@{key}"), val);
                        }

                        let res = parse_element_children(&mut self.reader, &self.target_tag_lower, store_raw, &mut raw_xml);
                        match res {
                            Ok(map) => {
                                let mut flat = HashMap::new();
                                for (k, v) in root_attrs {
                                    flat.insert(k, v);
                                }
                                flatten_json_map(&map, &mut flat, "", skip_description);
                                return Some(Ok((flat, raw_xml)));
                            }
                            Err(err) => return Some(Err(err)),
                        }
                    }
                }
                Ok(Event::Empty(ref e)) => {
                    let raw_name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                    let local_name = strip_namespace(&raw_name);
                    if local_name.eq_ignore_ascii_case(&self.target_tag_lower) {
                        let mut flat = HashMap::new();
                        for attr in e.attributes().flatten() {
                            let key = String::from_utf8_lossy(attr.key.as_ref()).to_string();
                            let val = String::from_utf8_lossy(&attr.value).to_string();
                            flat.insert(format!("@{key}"), val);
                        }
                        let raw_xml = if store_raw {
                            format!("<{}/>", String::from_utf8_lossy(e.as_ref()))
                        } else {
                            String::new()
                        };
                        return Some(Ok((flat, raw_xml)));
                    }
                }
                Ok(Event::Eof) => return None,
                Err(err) => return Some(Err(format!("XML parse error: {err}"))),
                _ => {}
            }
            self.buf.clear();
        }
    }

    /// Read next batch of pre-flattened records
    pub fn next_flat_batch(
        &mut self,
        batch_size: usize,
        store_raw: bool,
        skip_description: bool,
    ) -> Result<Vec<(HashMap<String, String>, String)>, String> {
        let mut batch = Vec::with_capacity(batch_size);
        while batch.len() < batch_size {
            match self.next_flat_record(store_raw, skip_description) {
                Some(Ok(rec)) => batch.push(rec),
                Some(Err(e)) => return Err(e),
                None => break,
            }
        }
        Ok(batch)
    }
}

/// Recursively flattens a JSON Map into dot/slash separated key-value pairs
fn flatten_json_map(
    map: &Map<String, Value>,
    out: &mut HashMap<String, String>,
    prefix: &str,
    skip_description: bool,
) {
    for (k, v) in map {
        if skip_description && k.to_lowercase().contains("description") {
            continue;
        }
        let full_key = if prefix.is_empty() {
            k.clone()
        } else {
            format!("{prefix}/{k}")
        };
        match v {
            Value::Object(nested) => {
                flatten_json_map(nested, out, &full_key, skip_description);
            }
            Value::Array(arr) => {
                if arr.iter().any(|item| item.is_object()) {
                    let mut merged_lists: HashMap<String, Vec<Value>> = HashMap::new();
                    for item in arr {
                        if let Value::Object(item_obj) = item {
                            let mut temp_flat = HashMap::new();
                            flatten_json_map(item_obj, &mut temp_flat, "", skip_description);
                            for (sub_k, sub_v) in temp_flat {
                                merged_lists.entry(sub_k).or_default().push(Value::String(sub_v));
                            }
                        }
                    }
                    for (sub_k, items) in merged_lists {
                        let merged_key = format!("{full_key}/{sub_k}");
                        if let Ok(serialized) = serde_json::to_string(&items) {
                            out.insert(merged_key, serialized);
                        }
                    }
                } else {
                    if let Ok(serialized) = serde_json::to_string(arr) {
                        out.insert(full_key, serialized);
                    }
                }
            }
            Value::String(s) => {
                out.insert(full_key, s.clone());
            }
            Value::Null => {}
            _ => {
                out.insert(full_key, v.to_string());
            }
        }
    }
}

/// Recursive XML element subtree parser to JSON Map
fn parse_element_children<R: Read + BufRead>(
    reader: &mut Reader<R>,
    closing_tag_lower: &str,
    store_raw: bool,
    raw_xml: &mut String,
) -> Result<Map<String, Value>, String> {
    let mut map = Map::new();
    let mut buf = Vec::with_capacity(2048);
    let mut current_text = String::new();

    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(ref e)) => {
                let tag_name = strip_namespace(&String::from_utf8_lossy(e.name().as_ref())).to_string();
                let tag_lower = tag_name.to_lowercase();

                if store_raw {
                    raw_xml.push('<');
                    raw_xml.push_str(&String::from_utf8_lossy(e.as_ref()));
                    raw_xml.push('>');
                }

                // Parse attributes
                let mut child_map = Map::new();
                for attr in e.attributes().flatten() {
                    let key = String::from_utf8_lossy(attr.key.as_ref()).to_string();
                    let val = String::from_utf8_lossy(&attr.value).to_string();
                    child_map.insert(format!("@{key}"), Value::String(val));
                }

                let sub_map = parse_element_children(reader, &tag_lower, store_raw, raw_xml)?;
                for (k, v) in sub_map {
                    child_map.insert(k, v);
                }

                let child_value = if child_map.is_empty() {
                    Value::String(String::new())
                } else if child_map.len() == 1 && child_map.contains_key("#text") {
                    child_map.remove("#text").unwrap()
                } else {
                    Value::Object(child_map)
                };

                insert_or_append(&mut map, tag_name, child_value);
            }
            Ok(Event::Empty(ref e)) => {
                let tag_name = strip_namespace(&String::from_utf8_lossy(e.name().as_ref())).to_string();
                if store_raw {
                    raw_xml.push('<');
                    raw_xml.push_str(&String::from_utf8_lossy(e.as_ref()));
                    raw_xml.push_str("/>");
                }

                let mut child_map = Map::new();
                for attr in e.attributes().flatten() {
                    let key = String::from_utf8_lossy(attr.key.as_ref()).to_string();
                    let val = String::from_utf8_lossy(&attr.value).to_string();
                    child_map.insert(format!("@{key}"), Value::String(val));
                }

                let child_value = if child_map.is_empty() {
                    Value::String(String::new())
                } else {
                    Value::Object(child_map)
                };

                insert_or_append(&mut map, tag_name, child_value);
            }
            Ok(Event::Text(ref e)) => {
                let text = String::from_utf8_lossy(e.as_ref()).trim().to_string();
                if !text.is_empty() {
                    if store_raw {
                        raw_xml.push_str(&text);
                    }
                    current_text.push_str(&text);
                }
            }
            Ok(Event::CData(ref e)) => {
                let text = String::from_utf8_lossy(e.as_ref()).to_string();
                if store_raw {
                    raw_xml.push_str("<![CDATA[");
                    raw_xml.push_str(&text);
                    raw_xml.push_str("]]>");
                }
                current_text.push_str(&text);
            }
            Ok(Event::End(ref e)) => {
                let tag_name = strip_namespace(&String::from_utf8_lossy(e.name().as_ref())).to_string();
                if store_raw {
                    raw_xml.push_str("</");
                    raw_xml.push_str(&tag_name);
                    raw_xml.push('>');
                }

                if tag_name.eq_ignore_ascii_case(closing_tag_lower) {
                    if !current_text.is_empty() {
                        map.insert("#text".to_string(), Value::String(current_text));
                    }
                    return Ok(map);
                }
            }
            Ok(Event::Eof) => return Ok(map),
            Err(err) => return Err(format!("Parse error: {err}")),
            _ => {}
        }
        buf.clear();
    }
}

#[inline]
fn insert_or_append(map: &mut Map<String, Value>, key: String, val: Value) {
    if let Some(existing) = map.get_mut(&key) {
        match existing {
            Value::Array(arr) => arr.push(val),
            _ => {
                let prev = existing.take();
                *existing = Value::Array(vec![prev, val]);
            }
        }
    } else {
        map.insert(key, val);
    }
}
