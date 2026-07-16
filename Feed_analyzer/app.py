import os
import uuid
import time
import logging
import threading
import datetime
import pandas as pd
from flask import Flask, render_template, request, jsonify, Response, send_file, redirect, url_for
from werkzeug.utils import secure_filename
import config
from utils import configure_logging, get_memory_usage_mb, format_size, ProgressEstimator
from parser import stream_xml_records, stream_json_records, get_url_stream, detect_xml_job_element, detect_json_record_path
from analyzer import FeedAnalyzerDb, get_db_connection
from filters import compile_filters
from search import compile_search
from statistics import get_field_stats, get_multi_group_by, get_global_statistics
from duplicates import find_duplicates
from reports import generate_missing_value_report, generate_duplicate_summary
from exporters import query_to_dataframe, export_csv, export_excel, export_json, export_html_report
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

def get_recent_feeds():
    """Reads available database files and returns their cached metadata."""
    feeds = []
    if not os.path.exists(config.DB_FOLDER):
        return []
    for filename in os.listdir(config.DB_FOLDER):
        if filename.endswith(".db"):
            task_id = filename[:-3]
            db_path = os.path.join(config.DB_FOLDER, filename)
            try:
                db = FeedAnalyzerDb(db_path)
                meta = db.get_metadata()
                if meta:
                    meta["task_id"] = task_id
                    feeds.append(meta)
            except Exception as e:
                logger.error(f"Error loading metadata for {filename}: {e}")
    return sorted(feeds, key=lambda x: x.get("filename", ""))

def run_parsing_task(
    task_id: str,
    source_path_or_url: str,
    is_url: bool,
    job_element_or_path: str,
    original_filename: str
) -> None:
    """Background thread function that parses the feed and populates the SQLite database."""
    logger.info(f"Starting parsing task {task_id} for {original_filename}")
    stream = None
    db = None
    try:
        # 1. Open stream and get total size
        if is_url:
            stream, total_size = get_url_stream(source_path_or_url, config.DEFAULT_TIMEOUT_SECONDS)
            file_type = "xml" if "xml" in source_path_or_url.lower() else "json"
        else:
            total_size = os.path.getsize(source_path_or_url)
            stream = open(source_path_or_url, 'rb')
            file_type = "xml" if source_path_or_url.lower().endswith('.xml') else "json"

        # 2. Setup SQLite Cache
        db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
        db = FeedAnalyzerDb(db_path)

        # 3. Auto-detect job element/path if set to Auto
        if not job_element_or_path or job_element_or_path.lower() == "auto":
            if not is_url:
                if file_type == "xml":
                    job_element_or_path = detect_xml_job_element(source_path_or_url)
                else:
                    job_element_or_path = detect_json_record_path(source_path_or_url)
            else:
                job_element_or_path = "job" if file_type == "xml" else "item"

        # Update initial task info
        with tasks_lock:
            parsing_tasks[task_id].update({
                "job_element": job_element_or_path,
                "file_type": file_type.upper()
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

        # 5. Determine correct generator
        if file_type == "xml":
            records_gen = stream_xml_records(stream, job_element_or_path, progress_callback)
        else:
            records_gen = stream_json_records(stream, job_element_or_path, progress_callback)

        # 6. Stream parse and insert in batches
        batch = []
        start_time = time.time()
        
        for record_dict, raw_content in records_gen:
            batch.append((record_dict, raw_content))
            estimator.update(1, estimator.processed_bytes)
            
            # Periodically update records count and speed
            if estimator.processed_records % 100 == 0:
                with tasks_lock:
                    parsing_tasks[task_id].update({
                        "records_count": estimator.processed_records,
                        "speed": round(estimator.speed_records_per_sec, 1)
                    })
                    
            if len(batch) >= config.BATCH_SIZE:
                db.insert_records(batch)
                batch.clear()

        # Insert remaining records
        if batch:
            db.insert_records(batch)
            
        if stream:
            stream.close()

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
    
    task_id = str(uuid.uuid4())
    is_url = False
    source_path = ""
    filename = ""

    if source_type == 'file':
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
        args=(task_id, source_path, is_url, job_element, filename)
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
    """Renders the analytical dashboard for a specific feed."""
    db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
    if not os.path.exists(db_path):
        return redirect(url_for('index'))
        
    db = FeedAnalyzerDb(db_path)
    metadata = db.get_metadata()
    global_stats = get_global_statistics(db_path, db.field_mappings)
    
    # Merge metadata and global stats
    metadata.update(global_stats)
    
    return render_template(
        'dashboard.html',
        task_id=task_id,
        metadata=metadata,
        schema_tree=db.get_schema_tree()
    )

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
        
    conn = get_db_connection(db_path)
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
            SELECT {col_name} as [Value], COUNT(*) as [Count]
            FROM records
            GROUP BY {col_name}
            ORDER BY [Count] DESC
        """
        df = pd.read_sql_query(query, conn)
        
        temp_filename = f"field_values_{uuid.uuid4().hex}.csv"
        output_path = os.path.join(config.REPORT_FOLDER, temp_filename)
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        
        download_name = f"{metadata.get('filename', 'export')}_{field_path.replace('/', '_')}_values.csv"
        return send_file(output_path, as_attachment=True, download_name=download_name)
    except Exception as e:
        logger.error(f"Error exporting values for {field_path}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/query/<task_id>', methods=['POST'])
def run_query(task_id):
    """Executes filtering and group-by visual queries against the feed database."""
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

    conn = get_db_connection(db_path)
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
                col_selections.append(f"{col} as [{path}]")
            col_selections_str = ", " + ", ".join(col_selections) if col_selections else ""
            
            query = f"""
                SELECT id as [_row_id], raw_content as [_raw_content] {col_selections_str}
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
    db_path = os.path.join(config.DB_FOLDER, f"{task_id}.db")
    if not os.path.exists(db_path):
        return jsonify({"error": "Database not found"}), 404
        
    db = FeedAnalyzerDb(db_path)
    metadata = db.get_metadata()
    mappings = db.field_mappings
    
    # 1. Check if we're exporting standard visual query results or just general reports
    data = request.json or {}
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
            
            query = f"SELECT id, raw_content, * FROM records {where_clause}"
            df = query_to_dataframe(db_path, query, params, mappings)
            
            # Write to file
            if export_format == 'csv':
                export_csv(df, output_path)
            elif export_format == 'xlsx':
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
                export_csv(df, output_path)
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
                export_csv(df, output_path)
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
