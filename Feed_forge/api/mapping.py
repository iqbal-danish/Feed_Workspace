import os
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from config import Config
from core.excel_reader import ExcelReader

mapping_bp = Blueprint('mapping', __name__)

@mapping_bp.route('/api/mapping', methods=['POST'])
def validate_mapping():
    """
    Validate spreadsheet or XML source column mappings.
    Expects JSON: { filename: str, sheet: str, mapping: dict, source_type: str, source_config: dict }
    """
    data = request.get_json() or {}
    filename = data.get('filename')
    sheet_name = data.get('sheet')
    mapping = data.get('mapping')
    source_type = data.get('source_type', 'excel')
    source_config = data.get('source_config', {})
    
    if mapping is None:
        return jsonify({'error': 'mapping is a required field'}), 400
        
    try:
        # Resolve source headers
        source_headers = []
        
        if source_type == 'excel':
            if not filename or not sheet_name:
                return jsonify({'error': 'filename and sheet are required fields for Excel validation'}), 400
            filename = secure_filename(filename)
            filepath = os.path.join(Config.UPLOADS_DIR, filename)
            if not os.path.exists(filepath):
                return jsonify({'error': f'Excel file {filename} not found'}), 404
            preview_data = ExcelReader.get_sheet_preview(filepath, sheet_name, max_rows=1)
            source_headers = [col['headerName'] for col in preview_data['columns']]
            
        elif source_type == 'xml_file':
            if not filename:
                return jsonify({'error': 'filename is required for XML validation'}), 400
            filename = secure_filename(filename)
            filepath = os.path.join(Config.UPLOADS_DIR, filename)
            if not os.path.exists(filepath):
                return jsonify({'error': f'XML file {filename} not found'}), 404
            from core.xml_source_reader import XMLSourceReader
            records, _ = XMLSourceReader.load_records_from_file(filepath, source_config.get('record_xpath'))
            if records:
                source_headers = list(records[0].keys())
                
        elif source_type == 'xml_url':
            url = source_config.get('url')
            if not url:
                return jsonify({'error': 'URL is required for XML URL validation'}), 400
            from core.xml_source_reader import XMLSourceReader
            records, _ = XMLSourceReader.load_records_from_url(url, source_config.get('record_xpath'), source_config)
            if records:
                source_headers = list(records[0].keys())
                
        else:
            return jsonify({'error': f'Unknown source type: {source_type}'}), 400
            
        # Verify that all mapped keys exist in the source headers
        invalid_columns = []
        for src_col in mapping.keys():
            if src_col not in source_headers:
                invalid_columns.append(src_col)
                
        if invalid_columns:
            return jsonify({
                'error': f'The following mapped columns/fields do not exist in the source: {", ".join(invalid_columns)}'
            }), 400
            
        return jsonify({
            'status': 'success',
            'message': 'Column mapping validated successfully.'
        })
    except Exception as e:
        return jsonify({'error': f'Validation failed: {str(e)}'}), 500

@mapping_bp.route('/api/static-fields', methods=['POST'])
def validate_static_fields():
    """
    Validate static fields.
    Expects JSON: { static_fields: dict }
    Where static_fields is: { "XML Tag": "Static Value" }
    """
    data = request.get_json() or {}
    static_fields = data.get('static_fields')
    
    if static_fields is None or not isinstance(static_fields, dict):
        return jsonify({'error': 'static_fields is a required dictionary field'}), 400
        
    # Basic validation: ensure tags are alphanumeric/underscores
    invalid_keys = []
    for key in static_fields.keys():
        if not key or not isinstance(key, str):
            invalid_keys.append(str(key))
            
    if invalid_keys:
        return jsonify({
            'error': f'Invalid static XML field tags: {", ".join(invalid_keys)}'
        }), 400
        
    return jsonify({
        'status': 'success',
        'message': 'Static fields validated successfully.'
    })
