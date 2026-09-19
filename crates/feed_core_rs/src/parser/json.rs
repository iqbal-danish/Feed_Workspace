use std::collections::HashMap;
use std::fs::File;
use std::io::{BufReader, Read};
use serde_json::Value;

/// Scans the beginning of a JSON file to detect repeating record array path
pub fn detect_json_record_path(file_path: &str, _limit_bytes: usize) -> Result<String, String> {
    let file = File::open(file_path).map_err(|e| format!("Failed to open JSON file: {e}"))?;
    let reader = BufReader::with_capacity(64 * 1024, file);

    let val: Value = serde_json::from_reader(reader).map_err(|e| format!("JSON parse error: {e}"))?;

    // Find the largest array of objects in the JSON structure
    let mut candidate_paths: HashMap<String, usize> = HashMap::new();
    find_arrays(&val, "", &mut candidate_paths);

    if let Some((best_path, _)) = candidate_paths.into_iter().max_by_key(|(_, len)| *len) {
        if best_path.is_empty() {
            Ok("item".to_string())
        } else {
            Ok(format!("{best_path}.item"))
        }
    } else {
        Ok("item".to_string())
    }
}

fn find_arrays(val: &Value, current_path: &str, candidates: &mut HashMap<String, usize>) {
    match val {
        Value::Array(arr) => {
            if arr.iter().any(|item| item.is_object()) {
                candidates.insert(current_path.to_string(), arr.len());
            }
        }
        Value::Object(map) => {
            for (k, v) in map {
                let next_path = if current_path.is_empty() {
                    k.clone()
                } else {
                    format!("{current_path}.{k}")
                };
                find_arrays(v, &next_path, candidates);
            }
        }
        _ => {}
    }
}
