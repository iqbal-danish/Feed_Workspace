import os
import json
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from config import Config

workspace_bp = Blueprint('workspace', __name__)

@workspace_bp.route('/api/workspaces', methods=['GET'])
def list_workspaces():
    """List all available JSON workspaces in the workspaces folder."""
    try:
        files = os.listdir(Config.WORKSPACES_DIR)
        workspaces = [os.path.splitext(f)[0] for f in files if f.endswith('.json')]
        return jsonify({'workspaces': workspaces})
    except Exception as e:
        return jsonify({'error': f'Failed to list workspaces: {str(e)}'}), 500

@workspace_bp.route('/api/workspace/save', methods=['POST'])
def save_workspace():
    """
    Save current workspace settings to a JSON file.
    Expects JSON: { name: str, filename: str, worksheet: str, template: str, mapping: dict, static_fields: dict }
    """
    data = request.get_json() or {}
    name = data.get('name')
    
    if not name:
        return jsonify({'error': 'workspace name is required.'}), 400
        
    filename = secure_filename(name) + ".json"
    filepath = os.path.join(Config.WORKSPACES_DIR, filename)
    
    # Extract workspace payload
    source_config = data.get('source_config', {}).copy()
    # Scrub sensitive credentials
    if 'password' in source_config:
        source_config['password'] = ''
    if 'token' in source_config:
        source_config['token'] = ''
    if 'header_value' in source_config:
        source_config['header_value'] = ''
        
    payload = {
        'filename': data.get('filename'),
        'worksheet': data.get('worksheet'),
        'template': data.get('template'),
        'mapping': data.get('mapping', {}),
        'static_fields': data.get('static_fields', {}),
        'campaign_custom_fields': data.get('campaign_custom_fields', []),
        'awm_config': data.get('awm_config', {}),
        'salary_config': data.get('salary_config', {}),
        'headers_config': data.get('headers_config', {}),
        'disabled_fields': data.get('disabled_fields', []),
        'ftp_config': data.get('ftp_config', {}),
        'source_type': data.get('source_type', 'excel'),
        'source_config': source_config,
        'transforms': data.get('transforms', [])
    }
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=4)
            
        return jsonify({
            'status': 'success',
            'message': f'Workspace "{name}" saved successfully.'
        })
    except Exception as e:
        return jsonify({'error': f'Failed to save workspace: {str(e)}'}), 500

@workspace_bp.route('/api/workspace/load', methods=['POST'])
def load_workspace():
    """
    Load a workspace configuration.
    Expects JSON: { name: str }
    """
    data = request.get_json() or {}
    name = data.get('name')
    
    if not name:
        return jsonify({'error': 'workspace name is required.'}), 400
        
    filename = secure_filename(name) + ".json"
    filepath = os.path.join(Config.WORKSPACES_DIR, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': f'Workspace "{name}" not found.'}), 404
        
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            payload = json.load(f)
            
        payload['name'] = name
        return jsonify(payload)
    except Exception as e:
        return jsonify({'error': f'Failed to load workspace: {str(e)}'}), 500
