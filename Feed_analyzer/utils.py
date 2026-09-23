import os
import time
import logging
import shutil
import zipfile
import gzip
import tarfile
import psutil
from typing import Optional, Tuple
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

def configure_logging(log_file: Optional[str] = None) -> None:
    """Configures application-wide logging."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return
        
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )
    
    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File Handler
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

def get_memory_usage_mb() -> float:
    """Returns the RSS memory usage of the current process in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024.0 * 1024.0)

def format_size(bytes_count: float) -> str:
    """Formats raw bytes count into a human-readable size string (e.g. KB, MB, GB)."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_count < 1024.0:
            return f"{bytes_count:.2f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.2f} PB"

class ProgressEstimator:
    """Helper class to track streaming import progress, speeds, and ETA."""
    def __init__(self, total_size_bytes: Optional[int] = None):
        self.start_time: float = time.time()
        self.total_size_bytes: Optional[int] = total_size_bytes
        self.processed_bytes: int = 0
        self.processed_records: int = 0
        self.last_update_time: float = self.start_time
        self.last_update_records: int = 0

    def update(self, records_increment: int, bytes_read: int) -> None:
        """Updates the progress status."""
        self.processed_records += records_increment
        self.processed_bytes = bytes_read

    @property
    def elapsed_time(self) -> float:
        """Returns elapsed time in seconds."""
        return time.time() - self.start_time

    @property
    def speed_records_per_sec(self) -> float:
        """Returns processing speed in records per second."""
        elapsed = self.elapsed_time
        if elapsed <= 0:
            return 0.0
        return self.processed_records / elapsed

    @property
    def percentage_complete(self) -> float:
        """Returns progress percentage (0.0 to 100.0) based on bytes parsed."""
        if not self.total_size_bytes or self.total_size_bytes <= 0:
            return 0.0
        pct = (self.processed_bytes / self.total_size_bytes) * 100.0
        return min(max(pct, 0.0), 100.0)

    @property
    def eta_seconds(self) -> Optional[float]:
        """Estimates remaining time in seconds based on bytes read rate."""
        elapsed = self.elapsed_time
        if elapsed <= 0 or self.processed_bytes <= 0 or not self.total_size_bytes:
            return None
        
        bytes_per_sec = self.processed_bytes / elapsed
        if bytes_per_sec <= 0:
            return None
            
        remaining_bytes = self.total_size_bytes - self.processed_bytes
        return max(remaining_bytes / bytes_per_sec, 0.0)


def handle_compressed_file(file_path: str, task_id: str, upload_folder: str) -> Tuple[str, str]:
    """Inspects a local file. If it is a .zip, .gz, or .tar.gz archive, decompresses it.
    
    Returns:
        Tuple of (decompressed_or_extracted_file_path, inner_feed_filename)
    """
    if not os.path.isfile(file_path):
        return file_path, os.path.basename(file_path)

    # Read leading bytes to check magic headers
    try:
        with open(file_path, 'rb') as f:
            header = f.read(512)
    except Exception as e:
        logger.warning(f"Could not read header of {file_path}: {e}")
        return file_path, os.path.basename(file_path)

    # 1. ZIP Archive (magic header PK\x03\x04 or .zip)
    if header.startswith(b'PK\x03\x04') or file_path.lower().endswith('.zip'):
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                entries = [
                    info for info in zf.infolist() 
                    if not info.is_dir() and not info.filename.startswith('__MACOSX') and not os.path.basename(info.filename).startswith('.')
                ]
                if not entries:
                    logger.warning(f"Zip file {file_path} is empty or has no readable files.")
                    return file_path, os.path.basename(file_path)

                # Prioritize feed extensions: xml, json, csv, rss, atom
                feed_entries = [
                    e for e in entries 
                    if any(e.filename.lower().endswith(ext) for ext in ('.xml', '.json', '.jsonl', '.ndjson', '.rss', '.atom', '.csv'))
                ]
                target_entry = max(feed_entries, key=lambda e: e.file_size) if feed_entries else max(entries, key=lambda e: e.file_size)

                inner_filename = os.path.basename(target_entry.filename)
                extracted_path = os.path.join(upload_folder, f"{task_id}_{secure_filename(inner_filename)}")
                
                with zf.open(target_entry) as z_in, open(extracted_path, 'wb') as f_out:
                    shutil.copyfileobj(z_in, f_out, length=1024 * 1024)

                logger.info(f"Extracted {target_entry.filename} ({target_entry.file_size} bytes) from ZIP {file_path} -> {extracted_path}")
                return extracted_path, inner_filename
        except Exception as e:
            logger.error(f"Failed to extract ZIP archive {file_path}: {e}")
            return file_path, os.path.basename(file_path)

    # 2. GZIP Archive (magic header 1F 8B or .gz/.gzip)
    if header.startswith(b'\x1f\x8b') or file_path.lower().endswith(('.gz', '.gzip')):
        try:
            base_name = os.path.basename(file_path)
            if base_name.lower().endswith('.gz'):
                inner_filename = base_name[:-3]
            elif base_name.lower().endswith('.gzip'):
                inner_filename = base_name[:-5]
            else:
                inner_filename = base_name + ".decompressed"

            if inner_filename.startswith(f"{task_id}_"):
                inner_filename = inner_filename[len(f"{task_id}_"):]

            decompressed_path = os.path.join(upload_folder, f"{task_id}_{secure_filename(inner_filename)}")
            
            with gzip.open(file_path, 'rb') as gz_in, open(decompressed_path, 'wb') as f_out:
                shutil.copyfileobj(gz_in, f_out, length=1024 * 1024)

            logger.info(f"Decompressed GZIP file {file_path} -> {decompressed_path} ({os.path.getsize(decompressed_path)} bytes)")
            return decompressed_path, inner_filename
        except Exception as e:
            logger.error(f"Failed to decompress GZIP file {file_path}: {e}")
            return file_path, os.path.basename(file_path)

    # 3. TAR / TAR.GZ Archive
    if file_path.lower().endswith(('.tar.gz', '.tgz', '.tar')):
        try:
            with tarfile.open(file_path, 'r:*') as tf:
                members = [
                    m for m in tf.getmembers() 
                    if m.isfile() and not m.name.startswith('__MACOSX') and not os.path.basename(m.name).startswith('.')
                ]
                if not members:
                    return file_path, os.path.basename(file_path)
                
                feed_members = [
                    m for m in members 
                    if any(m.name.lower().endswith(ext) for ext in ('.xml', '.json', '.jsonl', '.ndjson', '.rss', '.atom', '.csv'))
                ]
                target_member = max(feed_members or members, key=lambda m: m.size)
                inner_filename = os.path.basename(target_member.name)
                extracted_path = os.path.join(upload_folder, f"{task_id}_{secure_filename(inner_filename)}")
                
                f_in = tf.extractfile(target_member)
                if f_in:
                    with open(extracted_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out, length=1024 * 1024)
                    return extracted_path, inner_filename
        except Exception as e:
            logger.error(f"Failed to extract TAR archive {file_path}: {e}")
            return file_path, os.path.basename(file_path)

    return file_path, os.path.basename(file_path)
