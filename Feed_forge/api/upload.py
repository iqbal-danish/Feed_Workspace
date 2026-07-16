import os
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from config import Config
from core.excel_reader import ExcelReader

upload_bp = Blueprint('upload', __name__)

ALLOWED_EXTENSIONS = {'xlsx', 'xml'}

def allowed_file(filename: str) -> bool:
    """Check if the uploaded file has a permitted extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@upload_bp.route('/api/upload', methods=['POST'])
def upload_file():
    """
    Upload an Excel spreadsheet or XML feed file.
    Saves file to uploads/ and returns sheets or detected XML xpath.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected for uploading'}), 400
        
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file format. Supported formats: .xlsx, .xml'}), 400
        
    try:
        filename = secure_filename(file.filename)
        # Handle filename collisions by ensuring a unique path
        base, ext = os.path.splitext(filename)
        counter = 1
        unique_filename = filename
        
        while os.path.exists(os.path.join(Config.UPLOADS_DIR, unique_filename)):
            unique_filename = f"{base}_{counter}{ext}"
            counter += 1
            
        filepath = os.path.join(Config.UPLOADS_DIR, unique_filename)
        file.save(filepath)
        
        if unique_filename.lower().endswith('.xml'):
            from core.xml_source_reader import XMLSourceReader
            detected_xpath = XMLSourceReader.detect_repeating_xpath_stream(filepath)
            
            return jsonify({
                'filename': unique_filename,
                'is_xml': True,
                'detected_xpath': detected_xpath
            })
        else:
            # Parse workbook to retrieve sheets
            sheets = ExcelReader.get_sheet_names(filepath)
            
            return jsonify({
                'filename': unique_filename,
                'is_xml': False,
                'sheets': sheets
            })
    except Exception as e:
        return jsonify({'error': f'Failed to process file: {str(e)}'}), 500

@upload_bp.route('/api/sheets', methods=['GET'])
def get_sheets():
    """
    Get all worksheets from an uploaded workbook.
    Query parameters: filename
    """
    filename = request.args.get('filename')
    if not filename:
        return jsonify({'error': 'filename parameter is required'}), 400
        
    filename = secure_filename(filename)
    filepath = os.path.join(Config.UPLOADS_DIR, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
        
    try:
        sheets = ExcelReader.get_sheet_names(filepath)
        return jsonify({'sheets': sheets})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@upload_bp.route('/api/preview', methods=['GET'])
def preview_source():
    """
    Get preview rows for a specific worksheet or XML source.
    Query parameters: filename, sheet (for Excel), xpath (optional for XML)
    """
    filename = request.args.get('filename')
    sheet_name = request.args.get('sheet')
    record_xpath = request.args.get('xpath')
    
    if not filename:
        return jsonify({'error': 'filename parameter is required'}), 400
        
    # Prevent directory traversal attacks
    filename = secure_filename(filename)
    filepath = os.path.join(Config.UPLOADS_DIR, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
        
    try:
        if filename.lower().endswith('.xml'):
            from core.xml_source_reader import XMLSourceReader
            records, xpath = XMLSourceReader.load_records_from_file(filepath, record_xpath)
            preview_data = XMLSourceReader.get_preview(records)
            preview_data['detected_xpath'] = xpath
            return jsonify(preview_data)
        else:
            if not sheet_name:
                return jsonify({'error': 'sheet parameter is required for Excel files'}), 400
            preview_data = ExcelReader.get_sheet_preview(filepath, sheet_name)
            return jsonify(preview_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@upload_bp.route('/api/source/fetch-url', methods=['POST'])
def fetch_url():
    """
    Fetch XML source from a remote URL, apply auth, detect repeating xpath,
    and return preview data.
    """
    data = request.get_json() or {}
    url = data.get('url')
    record_xpath = data.get('record_xpath')
    auth_config = data.get('auth_config', {})
    
    if not url:
        return jsonify({'error': 'url parameter is required'}), 400
        
    try:
        from core.xml_source_reader import XMLSourceReader
        records, xpath = XMLSourceReader.load_records_from_url(url, record_xpath, auth_config)
        preview_data = XMLSourceReader.get_preview(records)
        preview_data['detected_xpath'] = xpath
        return jsonify(preview_data)
    except Exception as e:
        return jsonify({'error': f'Failed to fetch XML from URL: {str(e)}'}), 500
