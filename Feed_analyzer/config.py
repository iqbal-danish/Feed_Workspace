import os

# Project Root Directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Folder Paths
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DB_FOLDER = os.path.join(UPLOAD_FOLDER, 'databases')
REPORT_FOLDER = os.path.join(BASE_DIR, 'reports')

# Ensure directories exist
for folder in [UPLOAD_FOLDER, DB_FOLDER, REPORT_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# Application Settings
SECRET_KEY = os.urandom(24).hex()
ALLOWED_EXTENSIONS = {'xml', 'json'}

# Limits and Defaults
MAX_PREVIEW_ROWS = 1000
BATCH_SIZE = 2000  # Number of records to commit in a single SQLite transaction
DEFAULT_MAX_PEEK_BYTES = 5 * 1024 * 1024  # 5MB to peek schema/job element
DEFAULT_TIMEOUT_SECONDS = 30  # Timeout for HTTP URL downloads
