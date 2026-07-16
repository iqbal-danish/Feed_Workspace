import os
import time
import logging
import psutil
from typing import Optional

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
