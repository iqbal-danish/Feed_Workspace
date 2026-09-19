use ahash::AHashSet;
use std::sync::Mutex;
use serde_json::Value;

/// Thread-safe in-memory deduplicator for fast streaming merge
pub struct FastDeduplicator {
    seen_hashes: Mutex<AHashSet<u64>>,
}

impl FastDeduplicator {
    pub fn new() -> Self {
        Self {
            seen_hashes: Mutex::new(AHashSet::with_capacity(256 * 1024)),
        }
    }

    /// Check if hash has been seen. Returns true if unique (first time seen), false if duplicate.
    pub fn check_and_add(&self, hash: u64) -> bool {
        let mut set = self.seen_hashes.lock().unwrap();
        set.insert(hash)
    }

    /// Number of unique records seen
    pub fn unique_count(&self) -> usize {
        let set = self.seen_hashes.lock().unwrap();
        set.len()
    }

    /// Clear seen hashes
    pub fn clear(&self) {
        let mut set = self.seen_hashes.lock().unwrap();
        set.clear();
    }
}

/// Computes a fast aHash 64-bit value from composite field values of a JSON record
pub fn compute_record_hash(record: &Value, key_fields: &[String]) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut hasher = ahash::AHasher::default();

    if key_fields.is_empty() {
        // Hash entire JSON string representation
        record.to_string().hash(&mut hasher);
    } else {
        for field_name in key_fields {
            if let Some(val) = record.get(field_name) {
                match val {
                    Value::String(s) => s.trim().to_lowercase().hash(&mut hasher),
                    _ => val.to_string().hash(&mut hasher),
                }
            } else {
                "".hash(&mut hasher);
            }
        }
    }

    hasher.finish()
}
