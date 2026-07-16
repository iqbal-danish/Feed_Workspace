# XML Validator Pro

**Fast, lightweight XML validation for files of any size.**

XML Validator Pro is a desktop application built with Python and PySide6 that validates XML files using a streaming parser, making it capable of handling multi-gigabyte files without excessive memory usage.

---

## ✨ Features

- **Streaming Validation** — Processes XML incrementally; constant memory regardless of file size
- **Multi-GB File Support** — Validate files of any size without loading them entirely into RAM
- **Context Viewer** — See the surrounding lines for every error with syntax-highlighted context
- **4 Report Formats** — Export validation reports as HTML, JSON, CSV, or plain text
- **Dark & Light Themes** — Choose the UI theme that works for your environment
- **Drag & Drop** — Drop XML files directly onto the window to start validating

---

## 📸 Screenshots

> _Screenshots will be added once the UI is finalised._

---

## 📋 Requirements

| Requirement | Version |
|---|---|
| Python | 3.14+ |
| PySide6 | ≥ 6.7 |
| lxml | ≥ 5.0 |
| defusedxml | ≥ 0.7 |
| charset-normalizer | ≥ 3.0 |

---

## 🚀 Installation

```bash
# Clone the repository
git clone <repo-url>
cd Feed_validator

# Install dependencies
pip install -r requirements.txt

# Launch the application
python main.py
```

---

## 📖 Usage

1. **Open a file** — Use *File → Open* or drag-and-drop an XML file onto the window.
2. **Validate** — Click the **Validate** button. Progress and errors appear in real time.
3. **Inspect errors** — Click any error row to see the surrounding context lines.
4. **Export** — Use *File → Export Report* and choose HTML, JSON, CSV, or TXT.

---

## 📦 Building a Standalone Executable

A [PyInstaller](https://pyinstaller.org/) spec file is included for building a single-directory distribution:

```bash
pyinstaller xml_validator_pro.spec
```

The output will be in `dist/XMLValidatorPro/`.

---

## 🧪 Running Tests

```bash
python -m pytest tests/ -v
```

To run with coverage:

```bash
python -m pytest tests/ -v --cov=validator --cov=utils --cov=reports
```

---

## 🗂️ Project Structure

```
Feed_validator/
├── main.py                        # Application entry point
├── requirements.txt               # Python dependencies
├── xml_validator_pro.spec         # PyInstaller build spec
├── README.md
│
├── validator/                     # Core validation engine
│   ├── __init__.py
│   ├── models.py                  # Data structures (errors, results, settings)
│   ├── encoding.py                # Character encoding detection
│   ├── xml_validator.py           # High-level validate_xml() API
│   └── streaming_validator.py     # Streaming SAX/pull parser
│
├── reports/                       # Report generation
│   └── report_generator.py        # HTML, JSON, CSV, TXT exporters
│
├── utils/                         # Utility functions
│   ├── __init__.py
│   └── file_utils.py              # File size, duration, speed formatters
│
├── ui/                            # PySide6 GUI
│   ├── __init__.py
│   ├── main_window.py
│   ├── context_viewer.py
│   └── theme.py
│
├── workers/                       # Background threads
│   ├── __init__.py
│   └── validation_worker.py
│
├── resources/                     # Static assets
│   └── icons/
│
└── tests/                         # Test suite
    ├── __init__.py
    ├── conftest.py                # Shared fixtures
    ├── fixtures/                  # XML test files
    │   ├── valid_small.xml
    │   ├── valid_with_namespaces.xml
    │   ├── malformed_tag_mismatch.xml
    │   ├── malformed_invalid_entity.xml
    │   ├── malformed_bad_encoding.xml
    │   ├── malformed_cdata.xml
    │   ├── malformed_duplicate_declaration.xml
    │   └── malformed_illegal_chars.xml
    ├── test_models.py
    ├── test_encoding.py
    ├── test_validator.py
    ├── test_streaming_validator.py
    ├── test_report_generator.py
    └── test_file_utils.py
```

---

## 📄 License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.
