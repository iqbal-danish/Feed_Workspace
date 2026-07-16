import os
from flask import Blueprint, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from config import Config
from core.generator import XMLGenerator
from core.ftp_client import FTPClient

generate_bp = Blueprint('generate', __name__)

@generate_bp.route('/api/generate', methods=['POST'])
def generate_xml():
    """
    Compile Excel sheet, XML file, or XML URL and XML template to output XML.
    Expects JSON: { 
        filename: str (optional for url), 
        sheet: str (optional for xml), 
        template: str, 
        mapping: dict, 
        static_fields: dict,
        source_type: str,
        source_config: dict,
        transforms: list
    }
    """
    data = request.get_json() or {}
    excel_filename = data.get('filename')
    sheet_name = data.get('sheet')
    template_filename = data.get('template')
    mapping = data.get('mapping')
    static_fields = data.get('static_fields', {})
    campaign_custom_fields = data.get('campaign_custom_fields', [])
    awm_config = data.get('awm_config', {})
    salary_config = data.get('salary_config', {})
    headers_config = data.get('headers_config', {})
    disabled_fields = data.get('disabled_fields', [])
    source_type = data.get('source_type', 'excel')
    source_config = data.get('source_config', {})
    transforms = data.get('transforms', [])
    
    if not template_filename or mapping is None:
        return jsonify({'error': 'template and mapping are required.'}), 400
        
    if source_type == 'excel':
        if not excel_filename or not sheet_name:
            return jsonify({'error': 'filename and sheet are required for Excel sources.'}), 400
    elif source_type == 'xml_file':
        if not excel_filename:
            return jsonify({'error': 'filename is required for XML File sources.'}), 400
    elif source_type == 'xml_url':
        if not source_config.get('url'):
            return jsonify({'error': 'URL parameter is required inside source_config for XML URL sources.'}), 400
            
    if excel_filename:
        excel_filename = secure_filename(excel_filename)
        excel_path = os.path.join(Config.UPLOADS_DIR, excel_filename)
        if not os.path.exists(excel_path):
            return jsonify({'error': f'Source file {excel_filename} not found.'}), 404
    else:
        excel_path = ""
        
    template_filename = secure_filename(template_filename)
    template_path = os.path.join(Config.XML_TEMPLATES_DIR, template_filename)
    
    if not os.path.exists(template_path):
        return jsonify({'error': f'Template XML {template_filename} not found.'}), 404
        
    try:
        # Run generation
        output_xml = XMLGenerator.generate(
            excel_path=excel_path,
            sheet_name=sheet_name,
            template_path=template_path,
            mapping=mapping,
            static_fields=static_fields,
            campaign_custom_fields=campaign_custom_fields,
            awm_config=awm_config,
            salary_config=salary_config,
            headers_config=headers_config,
            disabled_fields=disabled_fields,
            source_type=source_type,
            source_config=source_config,
            transforms=transforms
        )
        
        # Save output file
        if excel_filename:
            excel_base = os.path.splitext(excel_filename)[0]
            output_filename = f"{excel_base}_{sheet_name or 'feed'}_feed.xml"
        else:
            output_filename = "url_feed.xml"
            
        output_filename = secure_filename(output_filename)
        output_path = os.path.join(Config.OUTPUT_DIR, output_filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output_xml)
            
        # Create a preview of the first 100 lines
        lines = output_xml.splitlines()
        preview_lines = lines[:100]
        preview_text = "\n".join(preview_lines)
        if len(lines) > 100:
            preview_text += "\n\n<!-- ... (truncated, download full file to view remaining records) ... -->"
            
        return jsonify({
            'status': 'success',
            'output_file': output_filename,
            'preview': preview_text,
            'line_count': len(lines)
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to generate XML: {str(e)}'}), 500

@generate_bp.route('/api/download', methods=['GET'])
def download_file():
    """
    Download a generated XML feed.
    Query parameters: file
    """
    filename = request.args.get('file')
    if not filename:
        return jsonify({'error': 'file parameter is required.'}), 400
        
    filename = secure_filename(filename)
    
    # Send from directory ensures file security checks
    return send_from_directory(
        directory=Config.OUTPUT_DIR,
        path=filename,
        as_attachment=True,
        download_name=filename
    )

@generate_bp.route('/api/generate/upload-ftp', methods=['POST'])
def upload_ftp():
    """
    Upload a generated XML feed to a remote FTP or SFTP server.
    Expects JSON: {
        filename: str,
        protocol: str (ftp/sftp),
        host: str,
        port: int,
        username: str,
        password: str,
        remote_dir: str,
        remote_filename: str
    }
    """
    data = request.get_json() or {}
    filename = data.get('filename')
    protocol = data.get('protocol', 'ftp').lower()
    host = data.get('host')
    port = data.get('port')
    username = data.get('username')
    password = data.get('password')
    remote_dir = data.get('remote_dir', '')
    remote_filename = data.get('remote_filename')
    
    if not filename or not host or not username or not password:
        return jsonify({'error': 'Missing host, username, password, or source file.'}), 400
        
    filename = secure_filename(filename)
    local_path = os.path.join(Config.OUTPUT_DIR, filename)
    
    if not os.path.exists(local_path):
        return jsonify({'error': 'Compiled XML file not found. Please compile the XML first.'}), 404
        
    # Default remote filename to local file name if not customized
    if not remote_filename or not remote_filename.strip():
        remote_filename = filename
    else:
        # Keep dots and dashes for filename validation
        remote_filename = secure_filename(remote_filename)
        if not remote_filename.lower().endswith('.xml'):
            remote_filename += '.xml'
            
    try:
        if protocol == 'sftp':
            FTPClient.upload_sftp(
                host=host,
                port=port,
                username=username,
                password=password,
                remote_dir=remote_dir,
                remote_filename=remote_filename,
                local_filepath=local_path
            )
        else:
            FTPClient.upload_ftp(
                host=host,
                port=port,
                username=username,
                password=password,
                remote_dir=remote_dir,
                remote_filename=remote_filename,
                local_filepath=local_path
            )
            
        return jsonify({
            'status': 'success',
            'message': f'File successfully uploaded as "{remote_filename}" via {protocol.upper()}!'
        })
    except Exception as e:
        return jsonify({'error': f'File transfer failed: {str(e)}'}), 500
