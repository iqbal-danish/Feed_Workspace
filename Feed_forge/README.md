# FeedForge

FeedForge is a modern, production-quality, desktop-style Single Page Application (SPA) designed to convert Excel spreadsheets into XML files. It runs entirely locally on the user's machine without any database or external cloud dependencies, keeping configuration states stored as clean JSON files.

## Features

- **Local-First Execution**: No database, cloud APIs, or authentication needed.
- **Single Page Application (SPA)**: Smooth transition flows built with Bootstrap 5, Bootstrap Icons, and Vanilla ES6 JavaScript.
- **Excel Explorer**: Upload spreadsheets, switch worksheet tabs, and preview raw data (first 100 rows) using **AG Grid Community**.
- **XML Template Manager**: Upload, save, edit, and validate XML schemas directly in the browser. Supports automatic parsing of double curly-brace variables (`{{placeholder}}`).
- **Dynamic Field Mapping**: Map spreadsheet columns to XML tags, plus custom static variables.
- **Robust Generation Engine**: Integrates pandas and lxml to compile XML feeds, automatically escaping breaking entities (`&`, `<`, `>`, `"`, `'`).
- **Session Workspaces**: Save or load complete workflow templates as JSON files.

## Project Structure

```text
FeedForge/
├── app.py                 # Main Flask server entry point
├── config.py              # Directory paths and config variables
├── requirements.txt       # Project python dependencies
├── start.bat              # Windows click-to-run startup script
├── README.md              # Documentation
├── api/                   # Flask blueprints (upload, template, mapping, workspaces, generator)
├── core/                  # Core modules (excel parsing, template parser, XML generator)
├── frontend/              # HTML, CSS, JavaScript assets
│   ├── index.html         # SPA markup entrypoint
│   ├── css/style.css      # Themes, transitions, custom code styles
│   └── js/                # ES6 JavaScript modules
├── uploads/               # Stored workbook uploads (ignored by git)
├── output/                # Compiled XML feeds (ignored by git)
├── workspaces/            # Saved workspace configurations (ignored by git)
└── xml_templates/         # User XML templates
```

## Prerequisites

- **Python 3.12+**
- Modern Web Browser (Chrome, Edge, Firefox, or Safari)

## Setup & Running

1. **Build Python Virtual Environment**:
   ```bash
   python -m venv .venv
   ```
2. **Install Dependencies**:
   ```bash
   .venv\Scripts\pip install -r requirements.txt
   ```
3. **Launch Application**:
   Double click the **`start.bat`** file to start the Flask server. It will automatically launch your default browser to `http://127.0.0.1:5000`.

## XML Template Writing Guide

Placeholders should be declared using double curly braces inside tags or attributes:

```xml
<jobfeed>
  <job>
    <title>{{title}}</title>
    <company>{{company}}</company>
    <location>{{location}}</location>
    <provider>{{provider}}</provider>
  </job>
</jobfeed>
```

The conversion engine identifies the root tag (`<jobfeed>`) and isolates the repeating record tag (`<job>`), repeating it for every row inside the worksheet during compilation.
