use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use std::fs::File;

pub mod parser;
pub mod validator;
pub mod dedup;

/// Detects repeating job element tag in XML file
#[pyfunction]
#[pyo3(signature = (file_path, limit_bytes = 5 * 1024 * 1024))]
fn detect_xml_job_element_rs(file_path: &str, limit_bytes: usize) -> PyResult<String> {
    parser::xml::detect_xml_job_element(file_path, limit_bytes)
        .map_err(|e| PyValueError::new_err(e))
}

/// Detects repeating record path in JSON file
#[pyfunction]
#[pyo3(signature = (file_path, limit_bytes = 5 * 1024 * 1024))]
fn detect_json_record_path_rs(file_path: &str, limit_bytes: usize) -> PyResult<String> {
    parser::json::detect_json_record_path(file_path, limit_bytes)
        .map_err(|e| PyValueError::new_err(e))
}

/// Validates an XML file strictly for W3C syntax, unquoted boolean attributes, and tag mismatches
#[pyfunction]
#[pyo3(signature = (file_path, max_errors = 1000, context_window = 2))]
fn validate_xml_file_rs(file_path: &str, max_errors: usize, context_window: usize) -> PyResult<String> {
    let errors = validator::xml::validate_xml_file(file_path, max_errors, context_window)
        .map_err(|e| PyValueError::new_err(e))?;
    
    serde_json::to_string(&errors)
        .map_err(|e| PyValueError::new_err(format!("JSON serialization error: {e}")))
}

/// Computes a fast composite 64-bit hash for a JSON record
#[pyfunction]
#[pyo3(signature = (record_json, key_fields = vec![]))]
fn compute_record_hash_rs(record_json: &str, key_fields: Vec<String>) -> PyResult<u64> {
    let val: serde_json::Value = serde_json::from_str(record_json)
        .map_err(|e| PyValueError::new_err(format!("Invalid JSON record: {e}")))?;
    Ok(dedup::compute_record_hash(&val, &key_fields))
}

/// PyO3 Streaming XML Record Iterator
#[pyclass]
struct XmlRecordStreamer {
    inner: parser::xml::XmlRecordStream<File>,
    store_raw: bool,
}

#[pymethods]
impl XmlRecordStreamer {
    #[new]
    #[pyo3(signature = (file_path, tag_name, store_raw = true))]
    fn new(file_path: &str, tag_name: &str, store_raw: bool) -> PyResult<Self> {
        let file = File::open(file_path)
            .map_err(|e| PyValueError::new_err(format!("Cannot open file '{file_path}': {e}")))?;
        Ok(Self {
            inner: parser::xml::XmlRecordStream::new(file, tag_name),
            store_raw,
        })
    }

    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(mut slf: PyRefMut<'_, Self>) -> PyResult<Option<(String, String)>> {
        let store_raw = slf.store_raw;
        match slf.inner.next_record(store_raw) {
            Some(Ok(pair)) => Ok(Some(pair)),
            Some(Err(err)) => Err(PyValueError::new_err(err)),
            None => Ok(None),
        }
    }
}

/// PyO3 Fast In-Memory Deduplicator
#[pyclass]
struct FastDeduplicator {
    inner: dedup::FastDeduplicator,
}

#[pymethods]
impl FastDeduplicator {
    #[new]
    fn new() -> Self {
        Self {
            inner: dedup::FastDeduplicator::new(),
        }
    }

    /// Check if hash has been seen. Returns true if unique (added), false if duplicate.
    fn check_and_add(&self, hash: u64) -> bool {
        self.inner.check_and_add(hash)
    }

    /// Number of unique records seen
    fn unique_count(&self) -> usize {
        self.inner.unique_count()
    }

    /// Reset state
    fn clear(&self) {
        self.inner.clear();
    }
}

/// A Python module implemented in Rust.
#[pymodule]
fn feed_core_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(detect_xml_job_element_rs, m)?)?;
    m.add_function(wrap_pyfunction!(detect_json_record_path_rs, m)?)?;
    m.add_function(wrap_pyfunction!(validate_xml_file_rs, m)?)?;
    m.add_function(wrap_pyfunction!(compute_record_hash_rs, m)?)?;
    m.add_class::<XmlRecordStreamer>()?;
    m.add_class::<FastDeduplicator>()?;
    Ok(())
}
