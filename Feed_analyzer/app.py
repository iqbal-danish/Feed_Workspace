import os
import io
import uuid
import time
import json
import logging
import threading
import datetime
# Defer pandas import to speed up startup
# import pandas as pd
from flask import Flask, render_template, request, jsonify, Response, send_file, redirect, url_for
from werkzeug.utils import secure_filename
import config
from utils import configure_logging, get_memory_usage_mb, format_size, ProgressEstimator, handle_compressed_file, get_gz_uncompressed_size
from parser import (
    stream_xml_records, stream_json_records,
    stream_xml_batches, stream_json_batches,
    get_url_stream, detect_xml_job_element, detect_json_record_path,
    PeekableStream, detect_content_type_from_bytes
)
try:
    from fast_downloader import download_file_fast
except ImportError:
    from Feed_analyzer.fast_downloader import download_file_fast
from analyzer import FeedAnalyzerDb, get_analytics_connection, get_db_connection
from filters import compile_filters
from search import compile_search
from statistics import get_field_stats, get_multi_group_by, get_global_statistics, precache_field_stats
from duplicates import find_duplicates
from reports import generate_missing_value_report, generate_duplicate_summary
from exporters import (
    query_to_dataframe,
    export_csv,
    export_excel,
    export_json,
    export_html_report,
    stream_query_csv_response,
)
from charts import compile_chart_data

# Initialize logging
configure_logging(os.path.join(config.BASE_DIR, 'logs', 'app.log'))
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# Thread-safe dictionary to track background parsing jobs
# task_id -> {status, records_count, bytes_read, percentage, speed, memory_mb, eta_seconds, error, metadata}
parsing_tasks = {}
tasks_lock = threading.Lock()


def get_export_request_data():
    """Accept export payloads from JSON fetches and standard form posts."""
    if request.is_json:
        return request.get_json(silent=True) or {}

    payload = request.form.get("payload")
    if payload:
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {}

    return request.form.to_dict() if request.form else {}


def csv_download_response(df, download_name):
    """Return a CSV download directly from memory to avoid temp-file overhead."""
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_bytes = csv_buffer.getvalue().encode("utf-8-sig")
    headers = {"Content-Disposition": f'attachment; filename="{download_name}"'}
    return Response(csv_bytes, mimetype="text/csv", headers=headers)

def get_recent_feeds() -> List[Dict[str, Any]]:
    """Returns a list of recently analyzed feed database metadata."""
    feeds = []
    if not os.path.exists(config.DB_FOLDER):
        return feeds
        
    for fname in os.listdir(config.DB_FOLDER):
        if fname.endswith('.db'):
            task_id = fname[:-3]
            db_path = os.path.join(config.DB_FOLDER, fname)
            try:
                db = FeedAnalyzerDb(db_path)
                meta = db.get_metadata()
                db.close()
                if meta:
                    meta["task_id"] = task_id
                    feeds.append(meta)
            except Exception as e:
                logger.error(f"Error loading metadata for {fname}: {e}")
                
    return sorted(feeds, key=lambda x: x.get("filename", ""))

def run_parsing_task(
    task_id: str,
    source_path_or_url: str,
    is_url: bool,
    job_element_or_path: str,
    original_filename: str,
    skip_description: bool = True,
    store_raw_content: bool = False
) -> None:
    """Background thread function that parses the feed and populates the SQLite database."""
    logger.info(f"Starting parsing task {task_id} for {original_filename} (skip_description={skip_description}, store_raw_content={store_raw_content})")
    stream = None
    db = None
    try:
        # 1. High-speed multi-threaded download for URL sources
        if is_url:
            with tasks_lock:
                parsing_tasks[task_id].update({
                    "status": "downloading feed (parallel streams)",
                    "job_element": job_element_or_path
                })

            download_target_path = os.path.join(config.UPLOAD_FOLDER, f"{task_id}_{secure_filename(original_filename)}")
            
            def dl_progress(downloaded_bytes, total_bytes, speed_mb, eta_s):
                pct = (downloaded_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0
                with tasks_lock:
                    parsing_tasks[task_id].update({
                        "status": "downloading feed (parallel streams)",
                        "bytes_read": downloaded_bytes,
                        "percentage": round(pct, 2),
                        "speed": round(speed_mb * 1000, 1),
                        "eta_seconds": round(eta_s, 1) if eta_s else None,
                        "memory_mb": round(get_memory_usage_mb(), 2)
                    })

            try:
                source_path_or_url = download_file_fast(
                    url=source_path_or_url,
                    output_path=download_target_path,
                    num_threads=8,
                    progress_callback=dl_progress
                )
                is_url = False
            except Exception as e_dl:
                logger.warning(f"Parallel download fallback to direct stream: {e_dl}")

        if not is_url:
            with tasks_lock:
                parsing_tasks[task_id].update({
                    "status": "inspecting archive"
                })
            source_path_or_url, inner_filename = handle_compressed_file(
                source_path_or_url, task_id, config.UPLOAD_FOLDER
            )
            if inner_filename != original_filename:
                original_filename = inner_filename
                with tasks_lock:
                    parsing_tasks[task_id]["filename"] = inner_filename

        if is_url:
            raw_stream, total_size = get_url_stream(source_path_or_url, config.DEFAULT_TIMEOUT_SECONDS)
            # Peek first 2048 bytes to check content
            peek_data = raw_stream.read(2048) if raw_stream else b""
            
            # Direct GZIP stream handling
            if peek_data.startswith(b'\x1f\x8b'):
                import gzip
                gz_stream = gzip.GzipFile(fileobj=PeekableStream(raw_stream, peek_data))
                decomp_peek = gz_stream.read(2048)
                stream = PeekableStream(gz_stream, decomp_peek)
                file_type = detect_content_type_from_bytes(decomp_peek, source_path_or_url)
            else:
                stream = PeekableStream(raw_stream, peek_data)
                hint = source_path_or_url
                if hasattr(raw_stream, 'headers'):
                    ct = raw_stream.headers.get('Content-Type', '')
                    if ct:
                        hint = f"{source_path_or_url} {ct}"
                file_type = detect_content_type_from_bytes(peek_data, hint)
        else:
            stream = open(source_path_or_url, 'rb')
            peek_data = stream.read(2048)
            stream.seek(0)
            file_type = detect_content_type_from_bytes(peek_data, source_path_or_url)

            is_gz = source_path_or_url.lower().endswith(('.gz', '.gzip')) or peek_data.startswith(b'\x1f\x8b')
            if is_gz:
                total_size = get_gz_uncompressed_size(source_path_or_url) or (os.path.getsize(source_path_or_url) * 5)
            else:
                total_size = os.path.getsize(source_path_or_url)

        # 2. Setup SQLite Cache
        db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
        db = FeedAnalyzerDb(db_path)
        # Update initial task info to "reading file"
        with tasks_lock:
            parsing_tasks[task_id].update({
                "job_element": job_element_or_path,
                "file_type": file_type.upper(),
                "status": "reading file"
            })

        # 3. Auto-detect job element/path if set to Auto
        if not job_element_or_path or job_element_or_path.lower() == "auto":
            if not is_url:
                if file_type == "xml":
                    job_element_or_path = detect_xml_job_element(source_path_or_url)
                else:
                    job_element_or_path = detect_json_record_path(source_path_or_url)
            else:
                job_element_or_path = "job" if file_type == "xml" else "item"

        # Update stage to "ingesting rows"
        with tasks_lock:
            parsing_tasks[task_id].update({
                "job_element": job_element_or_path,
                "status": "ingesting rows"
            })

        # 4. Initialize progress estimator
        estimator = ProgressEstimator(total_size)
        
        def progress_callback(bytes_read):
            estimator.update(0, bytes_read)
            with tasks_lock:
                parsing_tasks[task_id].update({
                    "bytes_read": bytes_read,
                    "percentage": round(estimator.percentage_complete, 2),
                    "eta_seconds": round(estimator.eta_seconds, 1) if estimator.eta_seconds is not None else None,
                    "memory_mb": round(get_memory_usage_mb(), 2)
                })

        # 5. Determine correct generator and setup reject logging
        reject_log_path = os.path.join(config.REJECT_FOLDER, f"{task_id}.reject.log")
        if file_type == "xml":
            batches_gen = stream_xml_batches(
                stream, job_element_or_path, batch_size=config.BATCH_SIZE,
                progress_callback=progress_callback, reject_log_path=reject_log_path,
                strict_mode=False, store_raw_content=store_raw_content,
                skip_description=skip_description
            )
        else:
            batches_gen = stream_json_batches(
                stream, job_element_or_path, batch_size=config.BATCH_SIZE,
                progress_callback=progress_callback, reject_log_path=reject_log_path,
                strict_mode=False, store_raw_content=store_raw_content,
                skip_description=skip_description
            )

        # 6. Stream parse and insert in batches
        start_time = time.time()
        last_progress_time = start_time
        
        for batch in batches_gen:
            db.insert_records(batch)
            estimator.update(len(batch), estimator.processed_bytes)
            
            # Periodically update records count and speed (rate-limited to avoid lock contention)
            now = time.time()
            if now - last_progress_time >= 0.25:
                last_progress_time = now
                with tasks_lock:
                    parsing_tasks[task_id].update({
                        "records_count": estimator.processed_records,
                        "speed": round(estimator.speed_records_per_sec, 1)
                    })
                    
        if stream:
            stream.close()

        # 6b. Post-load indexing
        with tasks_lock:
            parsing_tasks[task_id].update({
                "status": "building indexes"
            })
        db.create_indexes()

        # 6c. Count validation and reconciliation metrics
        rejected_count = 0
        if os.path.exists(reject_log_path):
            try:
                with open(reject_log_path, 'r', encoding='utf-8', errors='ignore') as rf:
                    rejected_count = sum(1 for _ in rf)
            except Exception:
                pass

        # 7. Collect and save metadata
        elapsed = time.time() - start_time
        metadata = {
            "task_id": task_id,
            "filename": original_filename,
            "file_size": format_size(total_size) if total_size else "Unknown",
            "file_type": file_type.upper(),
            "processing_time": f"{elapsed:.2f}",
            "job_element": job_element_or_path,
            "total_jobs": str(estimator.processed_records),
            "total_fields": str(len(db.field_mappings)),
            "records_seen": str(estimator.processed_records + rejected_count),
            "records_inserted": str(estimator.processed_records),
            "records_rejected": str(rejected_count),
            "memory_used": format_size(get_memory_usage_mb() * 1024 * 1024),
            "average_job_size": f"{(total_size / estimator.processed_records):.2f} B" if estimator.processed_records > 0 and total_size else "Unknown",
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        db.save_metadata(metadata)

        with tasks_lock:
            parsing_tasks[task_id].update({
                "status": "completed",
                "metadata": metadata,
                "records_count": estimator.processed_records,
                "speed": round(estimator.speed_records_per_sec, 1)
            })

        # Pre-cache top field statistics and global duplicate metrics asynchronously in background thread
        def _bg_precache():
            try:
                # Pre-calculate global duplicate statistics and persist to feed_info
                global_stats = get_global_statistics(db_path, db.field_mappings)
                db.save_metadata({
                    "duplicate_id_count": str(global_stats.get("duplicate_id_count", 0)),
                    "duplicate_id_field": str(global_stats.get("duplicate_id_field", "None"))
                })
                precache_field_stats(db_path, db.field_mappings)
            except Exception as e_cache:
                logger.warning(f"Field stats pre-caching warning: {e_cache}")

        threading.Thread(target=_bg_precache, daemon=True).start()
            
        logger.info(f"Task {task_id} completed successfully. Parsed {estimator.processed_records} records.")
        
    except Exception as e:
        logger.error(f"Error in task {task_id}: {e}", exc_info=True)
        if stream:
            try:
                stream.close()
            except Exception:
                pass
        with tasks_lock:
            parsing_tasks[task_id].update({
                "status": "failed",
                "error": str(e)
            })
    finally:
        if db:
            try:
                db.close()
            except Exception as e_close:
                logger.error(f"Failed to close DB in finally block: {e_close}")

@app.route('/')
def index():
    """Renders the main home screen."""
    recent_feeds = get_recent_feeds()
    return render_template('index.html', recent_feeds=recent_feeds)

@app.route('/analyze', methods=['POST'])
def analyze():
    """Triggers background feed parsing."""
    source_type = request.form.get('source_type')
    job_element = request.form.get('job_element', 'auto').strip()
    ingestion_mode = request.form.get('ingestion_mode', config.MODE_EXTREME_FAST).strip().lower()
    
    skip_description = ingestion_mode in (config.MODE_EXTREME_FAST, config.MODE_FAST)
    store_raw_content = ingestion_mode != config.MODE_EXTREME_FAST
    
    task_id = str(uuid.uuid4())
    is_url = False
    source_path = ""
    filename = ""

    if source_type == 'file':
        local_file_path = request.form.get('local_file_path', '').strip()
        if local_file_path and os.path.isfile(local_file_path):
            source_path = local_file_path
            filename = os.path.basename(local_file_path)
        else:
            if 'xml_file' not in request.files:
                return jsonify({"error": "No file uploaded"}), 400
            file = request.files['xml_file']
            if file.filename == '':
                return jsonify({"error": "No file selected"}), 400
                
            filename = secure_filename(file.filename)
            source_path = os.path.join(config.UPLOAD_FOLDER, f"{task_id}_{filename}")
            file.save(source_path)
        
    elif source_type == 'url':
        url = request.form.get('xml_url', '').strip()
        if not url:
            return jsonify({"error": "Empty URL"}), 400
        if not (url.startswith('http://') or url.startswith('https://')):
            return jsonify({"error": "Invalid URL protocol (must be http:// or https://)"}), 400
        source_path = url
        is_url = True
        filename = url.split('/')[-1] or "feed_data"
    else:
        return jsonify({"error": "Invalid source type"}), 400

    # Initialize task state
    with tasks_lock:
        parsing_tasks[task_id] = {
            "status": "processing",
            "records_count": 0,
            "bytes_read": 0,
            "percentage": 0.0,
            "speed": 0.0,
            "memory_mb": round(get_memory_usage_mb(), 2),
            "eta_seconds": None,
            "error": None,
            "metadata": {},
            "filename": filename,
            "job_element": job_element
        }

    # Start background thread
    t = threading.Thread(
        target=run_parsing_task,
        args=(task_id, source_path, is_url, job_element, filename, skip_description, store_raw_content)
    )
    t.daemon = True
    t.start()

    return jsonify({"task_id": task_id})

@app.route('/api/progress/<task_id>')
def get_progress_api(task_id):
    """Endpoint returning parsing progress state as JSON for AJAX polling."""
    with tasks_lock:
        task = parsing_tasks.get(task_id)
        
    if task:
        return jsonify(task)
        
    # If task not in memory, check if SQLite DB exists (completed task)
    db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
    if os.path.exists(db_path):
        db = FeedAnalyzerDb(db_path)
        try:
            meta = db.get_metadata()
            if meta:
                return jsonify({"status": "completed", "metadata": meta})
        except Exception as e:
            logger.error(f"Error reading metadata from cache: {e}")
            
    return jsonify({"status": "not_found"})

@app.route('/dashboard/<task_id>')
def dashboard(task_id):
    """Renders the analytical dashboard for a specific feed instantly without blocking on heavy queries."""
    db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
    if not os.path.exists(db_path):
        return redirect(url_for('index'))
        
    db = FeedAnalyzerDb(db_path)
    metadata = db.get_metadata()
    
    # Ensure baseline metadata fields exist
    if "total_fields" not in metadata:
        metadata["total_fields"] = str(len(db.field_mappings))
    if "total_jobs" not in metadata:
        metadata["total_jobs"] = "0"
        
    # If duplicate metrics are missing from cache, trigger background computation without stalling page load
    if "duplicate_id_count" not in metadata:
        metadata["duplicate_id_count"] = "0"
        metadata["duplicate_id_field"] = "None"
        
        def _bg_calc_dups():
            try:
                stats = get_global_statistics(db_path, db.field_mappings)
                db.save_metadata({
                    "duplicate_id_count": str(stats.get("duplicate_id_count", 0)),
                    "duplicate_id_field": str(stats.get("duplicate_id_field", "None"))
                })
            except Exception as e:
                logger.warning(f"Background duplicate calculation error: {e}")
                
        threading.Thread(target=_bg_calc_dups, daemon=True).start()
    
    return render_template(
        'dashboard.html',
        task_id=task_id,
        metadata=metadata,
        schema_tree=db.get_schema_tree()
    )

@app.route('/api/duplicate_summary/<task_id>')
def duplicate_summary(task_id):
    """Returns duplicate ID stats if available, or calculates them asynchronously."""
    db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
    if not os.path.exists(db_path):
        return jsonify({"error": "Database not found"}), 404
        
    db = FeedAnalyzerDb(db_path)
    metadata = db.get_metadata()
    
    if "duplicate_id_count" in metadata and "duplicate_id_field" in metadata:
        return jsonify({
            "duplicate_id_count": int(metadata.get("duplicate_id_count", 0)),
            "duplicate_id_field": metadata.get("duplicate_id_field", "None")
        })
        
    # Compute and persist
    stats = get_global_statistics(db_path, db.field_mappings)
    db.save_metadata({
        "duplicate_id_count": str(stats.get("duplicate_id_count", 0)),
        "duplicate_id_field": str(stats.get("duplicate_id_field", "None"))
    })
    return jsonify({
        "duplicate_id_count": stats.get("duplicate_id_count", 0),
        "duplicate_id_field": stats.get("duplicate_id_field", "None")
    })

@app.route('/api/field_stats/<task_id>')
def field_stats(task_id):
    """API endpoint to get statistics for a single field path."""
    field_path = request.args.get('field')
    if not field_path:
        return jsonify({"error": "Missing field query parameter"}), 400
        
    db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
    if not os.path.exists(db_path):
        return jsonify({"error": "Database not found"}), 404
        
    db = FeedAnalyzerDb(db_path)
    stats = get_field_stats(db_path, field_path, db.field_mappings)
    return jsonify(stats)

@app.route('/api/field_values/<task_id>')
def field_values(task_id):
    """API endpoint returning all unique values and frequencies for a field."""
    field_path = request.args.get('field')
    if not field_path:
        return jsonify({"error": "Missing field query parameter"}), 400
        
    db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
    if not os.path.exists(db_path):
        return jsonify({"error": "Database not found"}), 404
        
    db = FeedAnalyzerDb(db_path)
    col_name = db.field_mappings.get(field_path)
    if not col_name:
        return jsonify({"error": f"Field '{field_path}' not found in mappings"}), 404
        
    conn = get_analytics_connection(db_path)
    try:
        query = f"""
            SELECT {col_name} as val, COUNT(*) as cnt
            FROM records
            WHERE {col_name} IS NOT NULL
            GROUP BY {col_name}
            ORDER BY cnt DESC
        """
        rows = conn.execute(query).fetchall()
        data = [{"value": r["val"] if r["val"] != "" else "[Empty]", "count": r["cnt"]} for r in rows]
        return jsonify({"values": data})
    except Exception as e:
        logger.error(f"Error fetching all values for {field_path}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/export/<task_id>/field_values')
def export_field_values(task_id):
    """Downloads a CSV file containing all unique values and counts for a field."""
    import pandas as pd
    field_path = request.args.get('field')
    if not field_path:
        return jsonify({"error": "Missing field query parameter"}), 400
        
    db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
    if not os.path.exists(db_path):
        return jsonify({"error": "Database not found"}), 404
        
    db = FeedAnalyzerDb(db_path)
    col_name = db.field_mappings.get(field_path)
    if not col_name:
        return jsonify({"error": f"Field '{field_path}' not found in mappings"}), 404
        
    conn = get_db_connection(db_path)
    try:
        metadata = db.get_metadata()
        query = f"""
            SELECT {col_name} as Value, COUNT(*) as Count
            FROM records
            WHERE {col_name} IS NOT NULL AND {col_name} != ''
            GROUP BY {col_name}
            ORDER BY Count DESC
        """
        df = pd.read_sql_query(query, conn)

        download_name = f"{metadata.get('filename', 'export')}_{field_path.replace('/', '_')}_values.csv"
        return csv_download_response(df, download_name)
    except Exception as e:
        logger.error(f"Error exporting values for {field_path}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/query/<task_id>', methods=['POST'])
def run_query(task_id):
    """Executes filtering and group-by visual queries against the feed database."""
    import pandas as pd
    db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
    if not os.path.exists(db_path):
        return jsonify({"error": "Database not found"}), 404
        
    data = request.json or {}
    filters_list = data.get('filters', [])
    group_by_fields = data.get('group_by', [])
    search_term = data.get('search_term', '').strip()
    search_type = data.get('search_type', 'Contains')
    search_field = data.get('search_field', 'all')

    db = FeedAnalyzerDb(db_path)
    mappings = db.field_mappings

    # 1. Compile filters and searches
    filter_sql, filter_params = compile_filters(filters_list, mappings)
    search_sql, search_params = compile_search(search_term, search_type, search_field, mappings)

    # 2. Combine WHERE clause
    where_parts = []
    params = []
    
    if filter_sql:
        where_parts.append(f"({filter_sql})")
        params.extend(filter_params)
    if search_sql:
        where_parts.append(f"({search_sql})")
        params.extend(search_params)
        
    where_sql = " AND ".join(where_parts)

    conn = get_analytics_connection(db_path)
    try:
        # Check if group by is active
        if group_by_fields:
            group_data = get_multi_group_by(db_path, group_by_fields, mappings, where_sql, params)
            chart_data = compile_chart_data(group_data)
            return jsonify({
                "type": "grouped",
                "group_by": group_by_fields,
                "data": group_data,
                "chart_data": chart_data
            })
        else:
            # Standard preview records
            where_clause = f"WHERE {where_sql}" if where_sql else ""
            
            # Select Safe Column Mappings
            col_selections = []
            for path, col in mappings.items():
                safe_path = path.replace('"', '""')
                col_selections.append(f'{col} as "{safe_path}"')
            col_selections_str = ", " + ", ".join(col_selections) if col_selections else ""
            
            query = f"""
                SELECT id as "_row_id", raw_content as "_raw_content" {col_selections_str}
                FROM records
                {where_clause}
                LIMIT {config.MAX_PREVIEW_ROWS}
            """
            
            count_query = f"SELECT COUNT(*) as cnt FROM records {where_clause}"
            
            # Execute queries
            df = pd.read_sql_query(query, conn, params=params)
            count_row = conn.execute(count_query, params).fetchone()
            total_matches = count_row["cnt"] if count_row else 0
            
            # Format dataframe values (convert lists to strings for display)
            records = df.to_dict(orient='records')
            
            return jsonify({
                "type": "records",
                "records": records,
                "total_matches": total_matches,
                "preview_count": len(records)
            })
    except Exception as e:
        logger.error(f"Failed executing visual query: {e}")
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()

@app.route('/api/duplicates/<task_id>', methods=['POST'])
def run_duplicates(task_id):
    """Endpoint for finding duplicates in a specific field."""
    field_path = request.json.get('field') if request.json else None
    if not field_path:
        return jsonify({"error": "Field is required"}), 400
        
    db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
    if not os.path.exists(db_path):
        return jsonify({"error": "Database not found"}), 404
        
    db = FeedAnalyzerDb(db_path)
    dups = find_duplicates(db_path, field_path, db.field_mappings)
    return jsonify({"duplicates": dups})

@app.route('/api/missing/<task_id>', methods=['GET'])
def get_missing_report(task_id):
    """Endpoint generating a missing value report for all fields."""
    db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
    if not os.path.exists(db_path):
        return jsonify({"error": "Database not found"}), 404
        
    db = FeedAnalyzerDb(db_path)
    report = generate_missing_value_report(db_path, db.field_mappings)
    return jsonify({"report": report})

@app.route('/export/<task_id>/<export_format>', methods=['POST'])
def export_data(task_id, export_format):
    """Exports visual query results to Excel, CSV, JSON or generates HTML report."""
    import pandas as pd
    db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
    if not os.path.exists(db_path):
        return jsonify({"error": "Database not found"}), 404
        
    db = FeedAnalyzerDb(db_path)
    metadata = db.get_metadata()
    mappings = db.field_mappings
    
    # 1. Check if we're exporting standard visual query results or just general reports
    data = get_export_request_data()
    export_type = data.get('export_type', 'query') # 'query', 'duplicates', 'stats'
    
    temp_filename = f"export_{uuid.uuid4().hex}"
    
    if export_format not in ('csv', 'xlsx', 'json', 'html'):
        return jsonify({"error": "Unsupported export format"}), 400
        
    output_path = os.path.join(config.REPORT_FOLDER, f"{temp_filename}.{export_format}")
    
    try:
        if export_type == 'query':
            filters_list = data.get('filters', [])
            search_term = data.get('search_term', '').strip()
            search_type = data.get('search_type', 'Contains')
            search_field = data.get('search_field', 'all')
            
            # Compile WHERE
            filter_sql, filter_params = compile_filters(filters_list, mappings)
            search_sql, search_params = compile_search(search_term, search_type, search_field, mappings)
            
            where_parts = []
            params = []
            if filter_sql:
                where_parts.append(f"({filter_sql})")
                params.extend(filter_params)
            if search_sql:
                where_parts.append(f"({search_sql})")
                params.extend(search_params)
                
            where_sql = " AND ".join(where_parts)
            where_clause = f"WHERE {where_sql}" if where_sql else ""

            col_selections = []
            for path, col in mappings.items():
                col_selections.append(col)
            select_columns = ", ".join(["id"] + col_selections) if col_selections else "id"

            query = f"SELECT {select_columns} FROM records {where_clause}"
            if export_format == 'csv':
                download_name = f"{metadata.get('filename', 'export')}_{export_type}.{export_format}"
                return stream_query_csv_response(db_path, query, params, mappings, download_name)

            df = query_to_dataframe(db_path, query, params, mappings)
            
            # Write to file
            if export_format == 'xlsx':
                export_excel(df, output_path)
            elif export_format == 'json':
                export_json(df, output_path)
            else:
                return jsonify({"error": "HTML report not supported for records list. Use Excel/CSV."}), 400
                
        elif export_type == 'stats':
            # Precompute stats for all fields
            stats_list = []
            for path in mappings.keys():
                stat = get_field_stats(db_path, path, mappings)
                if stat:
                    stats_list.append(stat)
                    
            if export_format == 'html':
                export_html_report(metadata, stats_list, output_path)
            elif export_format == 'csv':
                df = pd.DataFrame(stats_list)
                download_name = f"{metadata.get('filename', 'export')}_{export_type}.{export_format}"
                return csv_download_response(df, download_name)
            elif export_format == 'xlsx':
                df = pd.DataFrame(stats_list)
                export_excel(df, output_path)
            elif export_format == 'json':
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(stats_list, f, indent=2, ensure_ascii=False)
                    
        elif export_type == 'duplicates':
            field_path = data.get('field')
            if not field_path:
                return jsonify({"error": "Field is required for duplicate export"}), 400
            dups = find_duplicates(db_path, field_path, mappings)
            df = pd.DataFrame(dups)
            
            if export_format == 'csv':
                download_name = f"{metadata.get('filename', 'export')}_{export_type}.{export_format}"
                return csv_download_response(df, download_name)
            elif export_format == 'xlsx':
                export_excel(df, output_path)
            elif export_format == 'json':
                export_json(df, output_path)
                
        # Send file download
        download_name = f"{metadata.get('filename', 'export')}_{export_type}.{export_format}"
        
        # We delete the file after sending using a generator or cleanup background thread,
        # but send_file handles sending. To prevent clogging disk, let's register a clean-up.
        return send_file(
            output_path,
            as_attachment=True,
            download_name=download_name
        )
    except Exception as e:
        logger.error(f"Failed exporting data: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/delete_feed/<task_id>', methods=['POST'])
def delete_feed(task_id):
    """Deletes cache DB and uploads associated with the feed."""
    db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
    
    # Clean up DB
    if os.path.exists(db_path):
        try:
            # Delete journal files if they exist (WAL mode creates .db-shm and .db-wal)
            for ext in ('', '-shm', '-wal'):
                path = db_path + ext
                if os.path.exists(path):
                    os.remove(path)
            logger.info(f"Deleted DB cache for feed {task_id}")
        except Exception as e:
            logger.error(f"Failed deleting db files: {e}")
            return jsonify({"error": "Failed to delete database cache files"}), 500
            
    # Clean up uploaded raw files in uploads
    if os.path.exists(config.UPLOAD_FOLDER):
        for f in os.listdir(config.UPLOAD_FOLDER):
            if f.startswith(task_id):
                try:
                    os.remove(os.path.join(config.UPLOAD_FOLDER, f))
                    logger.info(f"Deleted upload file {f}")
                except Exception as e:
                    logger.error(f"Failed to delete upload file: {e}")
                    
    return jsonify({"success": True})

if __name__ == '__main__':
    import webbrowser
    from threading import Timer
    
    def open_browser():
        webbrowser.open_new("http://127.0.0.1:5050/")
        
    # Open browser on startup, skipping when Werkzeug reloader runs in debug mode
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        Timer(1.5, open_browser).start()
        
    app.run(debug=True, host='127.0.0.1', port=5050)
