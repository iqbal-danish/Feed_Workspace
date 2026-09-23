"""
Fast Feed Downloader Utility
High-speed multi-threaded parallel HTTP range downloader for massive XML/JSON feeds (1GB+).
Bypasses browser single-thread download throttling by splitting HTTP requests across parallel connections.
"""

import os
import sys
import time
import math
import argparse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) XML Feed Fast Downloader"

def format_bytes(bytes_num: float) -> str:
    """Formats bytes into human-readable unit string."""
    if bytes_num <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(bytes_num, 1024)))
    p = math.pow(1024, i)
    s = round(bytes_num / p, 2)
    return f"{s} {units[i]}"

def get_remote_file_info(url: str, timeout: int = 15) -> tuple[int, bool]:
    """Inspects remote URL for file size and range request support."""
    req = urllib.request.Request(
        url,
        headers={'User-Agent': DEFAULT_USER_AGENT, 'Range': 'bytes=0-0'}
    )
    try:
        res = urllib.request.urlopen(req, timeout=timeout)
        if res.getcode() == 206:
            cr = res.headers.get('Content-Range', '')
            if '/' in cr:
                total_size = int(cr.split('/')[-1])
                return total_size, True
    except Exception:
        pass

    # Fallback to HEAD request
    try:
        req_head = urllib.request.Request(url, method='HEAD', headers={'User-Agent': DEFAULT_USER_AGENT})
        res_head = urllib.request.urlopen(req_head, timeout=timeout)
        cl = res_head.headers.get('Content-Length')
        if cl:
            return int(cl), False
    except Exception:
        pass

    return 0, False

def download_chunk_range(
    url: str,
    start_byte: int,
    end_byte: int,
    output_path: str,
    chunk_index: int,
    progress_callback: Optional[Callable[[int], None]] = None,
    timeout: int = 30
) -> int:
    """Worker function to download a specific byte range to disk."""
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': DEFAULT_USER_AGENT,
            'Range': f'bytes={start_byte}-{end_byte}',
            'Accept-Encoding': 'identity'
        }
    )
    bytes_downloaded = 0
    res = urllib.request.urlopen(req, timeout=timeout)
    
    with open(output_path, 'r+b') as f:
        f.seek(start_byte)
        buf_size = 1024 * 1024 # 1 MB socket buffer
        while True:
            buffer = res.read(buf_size)
            if not buffer:
                break
            f.write(buffer)
            bytes_downloaded += len(buffer)
            if progress_callback:
                progress_callback(len(buffer))
                
    return bytes_downloaded

def download_file_fast(
    url: str,
    output_path: Optional[str] = None,
    num_threads: int = 16,
    progress_callback: Optional[Callable[[int, int, float, float], None]] = None
) -> str:
    """Downloads a large file from URL using multi-threaded parallel byte-range streams.
    
    Args:
        url: Remote HTTP/HTTPS URL.
        output_path: Local file path to save (defaults to uploads directory).
        num_threads: Number of parallel HTTP range streams (default 8).
        progress_callback: Callback(downloaded_bytes, total_bytes, speed_mb_s, eta_s).
        
    Returns:
        Absolute path to the downloaded file.
    """
    if not output_path:
        filename = url.split('/')[-1].split('?')[0] or "downloaded_feed.xml"
        if not filename.endswith(('.xml', '.json', '.gz')):
            filename += ".xml"
        os.makedirs("downloads", exist_ok=True)
        output_path = os.path.join("downloads", filename)

    abs_output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_output_path), exist_ok=True)

    print(f"Connecting to: {url}")
    total_size, supports_range = get_remote_file_info(url)

    if total_size > 0 and supports_range and num_threads > 1:
        print(f"File Size: {format_bytes(total_size)} | Parallel Mode: {num_threads} Streams")
        # Pre-allocate output file size
        with open(abs_output_path, 'wb') as f:
            f.truncate(total_size)

        chunk_size = total_size // num_threads
        start_time = time.time()
        downloaded_bytes = 0

        def on_chunk_bytes(n):
            nonlocal downloaded_bytes
            downloaded_bytes += n
            elapsed = time.time() - start_time
            speed = (downloaded_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
            eta = (total_size - downloaded_bytes) / (downloaded_bytes / elapsed) if downloaded_bytes > 0 and elapsed > 0 else 0
            
            if progress_callback:
                progress_callback(downloaded_bytes, total_size, speed, eta)
            else:
                pct = (downloaded_bytes / total_size) * 100
                sys.stdout.write(f"\rDownloading: {pct:.1f}% | {format_bytes(downloaded_bytes)}/{format_bytes(total_size)} | {speed:.1f} MB/s | ETA: {eta:.1f}s")
                sys.stdout.flush()

        futures = []
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            for i in range(num_threads):
                start = i * chunk_size
                end = total_size - 1 if i == num_threads - 1 else (i + 1) * chunk_size - 1
                futures.append(
                    executor.submit(download_chunk_range, url, start, end, abs_output_path, i, on_chunk_bytes)
                )

            for future in as_completed(futures):
                future.result()

        elapsed = time.time() - start_time
        print(f"\nDownload Completed in {elapsed:.2f} seconds! Saved to: {abs_output_path}")
        return abs_output_path

    else:
        print(f"Single Stream Mode (Size: {format_bytes(total_size) if total_size else 'Unknown'})...")
        req = urllib.request.Request(url, headers={'User-Agent': DEFAULT_USER_AGENT})
        start_time = time.time()
        downloaded_bytes = 0

        with urllib.request.urlopen(req, timeout=60) as res, open(abs_output_path, 'wb') as f:
            while True:
                buf = res.read(256 * 1024)
                if not buf:
                    break
                f.write(buf)
                downloaded_bytes += len(buf)
                elapsed = time.time() - start_time
                speed = (downloaded_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                eta = ((total_size - downloaded_bytes) / (downloaded_bytes / elapsed)) if (total_size and total_size > downloaded_bytes and downloaded_bytes > 0 and elapsed > 0) else 0.0

                if progress_callback:
                    progress_callback(downloaded_bytes, total_size or 0, speed, eta)
                else:
                    if total_size:
                        pct = (downloaded_bytes / total_size) * 100
                        sys.stdout.write(f"\rDownloading: {pct:.1f}% | {format_bytes(downloaded_bytes)}/{format_bytes(total_size)} | {speed:.1f} MB/s")
                    else:
                        sys.stdout.write(f"\rDownloaded: {format_bytes(downloaded_bytes)} | {speed:.1f} MB/s")
                    sys.stdout.flush()

        elapsed = time.time() - start_time
        print(f"\nDownload Completed in {elapsed:.2f} seconds! Saved to: {abs_output_path}")
        return abs_output_path

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Fast Multi-Threaded Feed Downloader Utility")
    parser.add_argument("url", help="URL of the XML or JSON feed to download")
    parser.add_argument("-o", "--output", help="Output file path (optional)")
    parser.add_argument("-t", "--threads", type=int, default=8, help="Number of parallel download threads (default 8)")
    
    args = parser.parse_args()
    download_file_fast(args.url, args.output, args.threads)
