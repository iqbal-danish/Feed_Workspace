from flask import Flask, jsonify
from config import Config
from api.upload import upload_bp
from api.template import template_bp
from api.mapping import mapping_bp
from api.generate import generate_bp
from api.workspace import workspace_bp

def create_app():
    # Set static_folder to 'frontend' and static_url_path to '' to serve static assets at the root
    app = Flask(__name__, static_folder='frontend', static_url_path='')
    app.config.from_object(Config)
    
    # Register blueprints
    app.register_blueprint(upload_bp)
    app.register_blueprint(template_bp)
    app.register_blueprint(mapping_bp)
    app.register_blueprint(generate_bp)
    app.register_blueprint(workspace_bp)

    @app.route('/')
    def index():
        """Serve the frontend SPA entry point."""
        return app.send_static_file('index.html')

    # Stub APIs to verify skeleton works
    @app.route('/api/health', methods=['GET'])
    def health_check():
        """Basic health check to verify backend is up."""
        return jsonify({
            'status': 'healthy',
            'message': 'FeedForge API backend is running.'
        })

    # Error Handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return jsonify({'error': 'Resource not found'}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'error': 'Internal server error'}), 500

    return app

app = create_app()

if __name__ == '__main__':
    import os
    import webbrowser
    from threading import Timer
    
    def open_browser():
        webbrowser.open("http://127.0.0.1:5000")
        
    # Open browser only once (handles Werkzeug reloader child process vs main process)
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        Timer(1.2, open_browser).start()
        
    # Run the server locally
    app.run(host='127.0.0.1', port=5000, debug=True)
