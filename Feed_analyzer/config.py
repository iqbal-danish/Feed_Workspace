import os

# Project Root Directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Folder Paths
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DB_FOLDER = os.path.join(UPLOAD_FOLDER, 'databases')
REPORT_FOLDER = os.path.join(BASE_DIR, 'reports')
REJECT_FOLDER = os.path.join(BASE_DIR, 'rejects')

# Ensure directories exist
for folder in [UPLOAD_FOLDER, DB_FOLDER, REPORT_FOLDER, REJECT_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# Application Settings
SECRET_KEY = os.urandom(24).hex()
ALLOWED_EXTENSIONS = {'xml', 'json'}

# Limits and Defaults
MAX_PREVIEW_ROWS = 1000
BATCH_SIZE = 10000  # Increased batch size to 10,000 for high-throughput streaming
DEFAULT_MAX_PEEK_BYTES = 5 * 1024 * 1024  # 5MB to peek schema/job element
DEFAULT_TIMEOUT_SECONDS = 30  # Timeout for HTTP URL downloads

# Ingestion Modes
MODE_EXTREME_FAST = "extreme"
MODE_FAST = "fast"
MODE_FULL = "full"

# Parallel Processing Thresholds
PARALLEL_MIN_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

