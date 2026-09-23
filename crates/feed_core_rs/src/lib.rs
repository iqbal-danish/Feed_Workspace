use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use std::fs::File;
use std::collections::HashMap;

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

pub enum XmlStreamSource {
    Plain(File),
    Gz(flate2::read::GzDecoder<File>),
}

impl std::io::Read for XmlStreamSource {
    #[inline]
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        match self {
            XmlStreamSource::Plain(f) => f.read(buf),
            XmlStreamSource::Gz(gz) => gz.read(buf),
        }
    }
}

pub fn open_xml_source(file_path: &str) -> std::io::Result<XmlStreamSource> {
    use std::io::{Read, Seek, SeekFrom};
    let mut file = File::open(file_path)?;
    let mut magic = [0u8; 2];
    let n = file.read(&mut magic).unwrap_or(0);
    file.seek(SeekFrom::Start(0))?;

    let is_gz = (n >= 2 && magic[0] == 0x1f && magic[1] == 0x8b) || file_path.to_lowercase().ends_with(".gz");
    if is_gz {
        Ok(XmlStreamSource::Gz(flate2::read::GzDecoder::new(file)))
    } else {
        Ok(XmlStreamSource::Plain(file))
    }
}

/// PyO3 Streaming XML Record Iterator
#[pyclass]
struct XmlRecordStreamer {
    inner: parser::xml::XmlRecordStream<XmlStreamSource>,
    store_raw: bool,
}

#[pymethods]
impl XmlRecordStreamer {
    #[new]
    #[pyo3(signature = (file_path, tag_name, store_raw = true))]
    fn new(file_path: &str, tag_name: &str, store_raw: bool) -> PyResult<Self> {
        let source = open_xml_source(file_path)
            .map_err(|e| PyValueError::new_err(format!("Cannot open file '{file_path}': {e}")))?;
        Ok(Self {
            inner: parser::xml::XmlRecordStream::new(source, tag_name),
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

    /// Read next batch of pre-flattened records with GIL released
    #[pyo3(signature = (batch_size = 10000, skip_description = false))]
    fn next_flat_batch(
        &mut self,
        py: Python<'_>,
        batch_size: usize,
        skip_description: bool,
    ) -> PyResult<Vec<(HashMap<String, String>, String)>> {
        let store_raw = self.store_raw;
        py.allow_threads(|| {
            self.inner.next_flat_batch(batch_size, store_raw, skip_description)
        }).map_err(|e| PyValueError::new_err(e))
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

/// Prompts the user with a native Windows OS "Save As" file dialog (outside of Qt / WebEngine)
#[pyfunction]
#[pyo3(signature = (default_name = "export.csv", title = "Save As", extension_filters = vec![]))]
fn save_file_dialog_rs(
    py: Python<'_>,
    default_name: &str,
    title: &str,
    extension_filters: Vec<(String, Vec<String>)>,
) -> PyResult<String> {
    py.allow_threads(|| {
        let mut dialog = rfd::FileDialog::new()
            .set_title(title)
            .set_file_name(default_name);

        for (desc, exts) in &extension_filters {
            let ext_slices: Vec<&str> = exts.iter().map(|s| s.as_str()).collect();
            dialog = dialog.add_filter(desc, &ext_slices);
        }

        match dialog.save_file() {
            Some(path) => Ok(path.to_string_lossy().to_string()),
            None => Ok(String::new()),
        }
    })
}

/// Prompts the user with a native Windows OS "Open File" dialog
#[pyfunction]
#[pyo3(signature = (title = "Select File", extension_filters = vec![]))]
fn select_file_dialog_rs(
    py: Python<'_>,
    title: &str,
    extension_filters: Vec<(String, Vec<String>)>,
) -> PyResult<String> {
    py.allow_threads(|| {
        let mut dialog = rfd::FileDialog::new().set_title(title);

        for (desc, exts) in &extension_filters {
            let ext_slices: Vec<&str> = exts.iter().map(|s| s.as_str()).collect();
            dialog = dialog.add_filter(desc, &ext_slices);
        }

        match dialog.pick_file() {
            Some(path) => Ok(path.to_string_lossy().to_string()),
            None => Ok(String::new()),
        }
    })
}

/// A Python module implemented in Rust.
#[pymodule]
fn feed_core_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(detect_xml_job_element_rs, m)?)?;
    m.add_function(wrap_pyfunction!(detect_json_record_path_rs, m)?)?;
    m.add_function(wrap_pyfunction!(validate_xml_file_rs, m)?)?;
    m.add_function(wrap_pyfunction!(compute_record_hash_rs, m)?)?;
    m.add_function(wrap_pyfunction!(save_file_dialog_rs, m)?)?;
    m.add_function(wrap_pyfunction!(select_file_dialog_rs, m)?)?;
    m.add_class::<XmlRecordStreamer>()?;
    m.add_class::<FastDeduplicator>()?;
    Ok(())
}
