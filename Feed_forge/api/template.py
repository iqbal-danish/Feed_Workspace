import os
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from config import Config
from core.template_parser import TemplateParser

template_bp = Blueprint('template', __name__)

ALLOWED_EXTENSIONS = {'xml'}

def allowed_file(filename: str) -> bool:
    """Check if file ends with .xml."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@template_bp.route('/api/templates', methods=['GET'])
def list_templates():
    """List all available XML templates in the templates directory."""
    try:
        files = os.listdir(Config.XML_TEMPLATES_DIR)
        xml_files = [f for f in files if f.endswith('.xml')]
        return jsonify({'templates': xml_files})
    except Exception as e:
        return jsonify({'error': f'Failed to list templates: {str(e)}'}), 500

@template_bp.route('/api/templates/upload', methods=['POST'])
def upload_template():
    """Upload a new XML template file, validate it, and extract placeholders."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected for uploading'}), 400
        
    if not allowed_file(file.filename):
        return jsonify({'error': 'Only XML (.xml) files are supported as templates'}), 400
        
    try:
        filename = secure_filename(file.filename)
        filepath = os.path.join(Config.XML_TEMPLATES_DIR, filename)
        
        # Read content to validate
        content = file.read().decode('utf-8')
        
        # Validate XML well-formedness
        is_valid, err_msg = TemplateParser.validate_template(content)
        if not is_valid:
            return jsonify({'error': f'Invalid XML template: {err_msg}'}), 400
            
        # Reset file cursor and save
        file.seek(0)
        file.save(filepath)
        
        placeholders = TemplateParser.extract_placeholders(content)
        
        return jsonify({
            'filename': filename,
            'content': content,
            'placeholders': placeholders
        })
    except Exception as e:
        return jsonify({'error': f'Failed to upload template: {str(e)}'}), 500

@template_bp.route('/api/templates/parse', methods=['GET'])
def parse_template():
    """Load an existing template and extract placeholders."""
    filename = request.args.get('name')
    if not filename:
        return jsonify({'error': 'Template name parameter is required'}), 400
        
    filename = secure_filename(filename)
    filepath = os.path.join(Config.XML_TEMPLATES_DIR, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'Template file not found'}), 404
        
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        is_valid, err_msg = TemplateParser.validate_template(content)
        if not is_valid:
            return jsonify({'error': f'Stored template XML is invalid: {err_msg}'}), 400
            
        placeholders = TemplateParser.extract_placeholders(content)
        
        return jsonify({
            'filename': filename,
            'content': content,
            'placeholders': placeholders
        })
    except Exception as e:
        return jsonify({'error': f'Failed to parse template: {str(e)}'}), 500

@template_bp.route('/api/templates/save', methods=['POST'])
def save_template():
    """Create or overwrite a template directly via editor submission."""
    data = request.get_json() or {}
    filename = data.get('filename')
    content = data.get('content')
    
    if not filename or not content:
        return jsonify({'error': 'Both filename and content are required'}), 400
        
    # Ensure filename ends with .xml
    if not filename.lower().endswith('.xml'):
        filename += '.xml'
        
    filename = secure_filename(filename)
    filepath = os.path.join(Config.XML_TEMPLATES_DIR, filename)
    
    try:
        # Validate XML well-formedness before saving
        is_valid, err_msg = TemplateParser.validate_template(content)
        if not is_valid:
            return jsonify({'error': f'Invalid XML layout: {err_msg}'}), 400
            
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
            
        placeholders = TemplateParser.extract_placeholders(content)
        
        return jsonify({
            'filename': filename,
            'content': content,
            'placeholders': placeholders,
            'message': 'Template saved successfully.'
        })
    except Exception as e:
        return jsonify({'error': f'Failed to save template: {str(e)}'}), 500
