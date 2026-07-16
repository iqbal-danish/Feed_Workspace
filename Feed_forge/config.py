import os

class Config:
    """Application configuration and directory setup."""
    
    # Base directory of the project
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    
    # Data storage directories
    UPLOADS_DIR = os.path.join(BASE_DIR, 'uploads')
    OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
    WORKSPACES_DIR = os.path.join(BASE_DIR, 'workspaces')
    XML_TEMPLATES_DIR = os.path.join(BASE_DIR, 'xml_templates')
    
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY', 'feedforge-dev-secret-key-129847')
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500 MB limit for larger data feeds
    
    @classmethod
    def ensure_directories_exist(cls):
        """Create necessary directories if they do not exist."""
        directories = [
            cls.UPLOADS_DIR,
            cls.OUTPUT_DIR,
            cls.WORKSPACES_DIR,
            cls.XML_TEMPLATES_DIR
        ]
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            print(f"Ensured directory exists: {directory}")

# Initialize directories on configuration import
Config.ensure_directories_exist()
