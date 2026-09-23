import os
import tempfile
import unittest
import json
import duckdb
from config import BASE_DIR
from parser import stream_xml_records, stream_json_records, stream_xml_batches
from analyzer import FeedAnalyzerDb, get_analytics_connection
from filters import compile_filters

class TestStreamingPipeline(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for databases and logs
        self.test_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.test_dir.name, "test_task.db")
        self.duckdb_path = os.path.join(self.test_dir.name, "test_task.duckdb")
        self.reject_log_path = os.path.join(self.test_dir.name, "test_reject.log")

    def tearDown(self):
        self.test_dir.cleanup()

    def test_xml_streaming_and_reject_logging(self):
        # 1. Test non-strict mode: empty document writes to reject log
        xml_content = b""
        
        feed_file = os.path.join(self.test_dir.name, "feed.xml")
        with open(feed_file, "wb") as f:
            f.write(xml_content)

        with open(feed_file, "rb") as f:
            records = list(stream_xml_records(
                f, 
                "job", 
                reject_log_path=self.reject_log_path, 
                strict_mode=False
            ))

        self.assertEqual(len(records), 0)
        self.assertTrue(os.path.exists(self.reject_log_path))
        with open(self.reject_log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            self.assertTrue(len(lines) >= 1)
            self.assertIn("Parser level XML syntax error", lines[0])

        # 2. Test strict mode: malformed text raises exception
        with open(feed_file, "rb") as f:
            with self.assertRaises(Exception):
                list(stream_xml_records(
                    f, 
                    "job", 
                    strict_mode=True
                ))

    def test_json_streaming_and_reject_logging(self):
        # 1. Test non-strict mode JSON parsing error logs to reject log
        json_content = b"This is not JSON at all"
        
        feed_file = os.path.join(self.test_dir.name, "feed.json")
        with open(feed_file, "wb") as f:
            f.write(json_content)

        with open(feed_file, "rb") as f:
            records = list(stream_json_records(
                f, 
                "item", 
                reject_log_path=self.reject_log_path, 
                strict_mode=False
            ))

        self.assertEqual(len(records), 0)
        
        # 2. Test strict mode raises exception
        with open(feed_file, "rb") as f:
            with self.assertRaises(Exception):
                list(stream_json_records(
                    f, 
                    "item", 
                    strict_mode=True
                ))

    def test_duckdb_ingest_and_indexing(self):
        # Initialize analyzer db
        db = FeedAnalyzerDb(self.db_path)
        db.open()

        # Insert some records
        records_batch = [
            ({"title": "Frontend Engineer", "company": "Vercel", "Location": {"City": "NY"}}, "raw1"),
            ({"title": "Backend Engineer", "company": "Supabase", "Location": {"City": "SF"}}, "raw2")
        ]
        
        db.insert_records(records_batch)
        db.create_indexes()
        db.close()

        # Connect to DuckDB analytics connection
        conn = get_analytics_connection(self.db_path)
        
        # Test basic count
        res = conn.execute("SELECT COUNT(*) as cnt FROM records").fetchone()
        self.assertEqual(res[0], 2)
        conn.close() # Close first to release the DuckDB file lock

        # Test dynamic column queries (location city mapping)
        db = FeedAnalyzerDb(self.db_path)
        col_city = db.field_mappings.get("Location/City")
        col_company = db.field_mappings.get("company")
        self.assertIsNotNone(col_city)

        # Test compiled filter queries
        where_sql, params = compile_filters([
            {"field": "Location/City", "operator": "Equals", "value": "SF"}
        ], db.field_mappings)

        # Re-open connection to query
        conn = get_analytics_connection(self.db_path)
        query = f"SELECT {col_company} FROM records WHERE {where_sql}"
        row = conn.execute(query, params).fetchone()
        self.assertEqual(row[0], "Supabase")
        
        conn.close()
        db.close()

    def test_peekable_stream(self):
        from parser import PeekableStream
        import io
        raw = io.BytesIO(b" world from stream")
        peek = b"Hello"
        s = PeekableStream(raw, peek)
        self.assertEqual(s.read(5), b"Hello")
        self.assertEqual(s.read(6), b" world")
        self.assertEqual(s.read(), b" from stream")

    def test_detect_content_type_from_bytes(self):
        from parser import detect_content_type_from_bytes
        # XML standard
        self.assertEqual(detect_content_type_from_bytes(b'<?xml version="1.0"?><root></root>'), "xml")
        # XML without declaration
        self.assertEqual(detect_content_type_from_bytes(b'   <jobs><job><title>Engineer</title></job></jobs>'), "xml")
        # XML from PHP URL
        self.assertEqual(detect_content_type_from_bytes(b'<?xml version="1.0" encoding="UTF-8"?><source></source>', "getFeed.php?jobBoard=123"), "xml")
        # JSON Object
        self.assertEqual(detect_content_type_from_bytes(b'{"jobs": [{"title": "Dev"}]}'), "json")
        # JSON Array
        self.assertEqual(detect_content_type_from_bytes(b'[{"title": "Dev"}]'), "json")
        # Fallback hint
        self.assertEqual(detect_content_type_from_bytes(b'', "feed.xml"), "xml")
        self.assertEqual(detect_content_type_from_bytes(b'', "feed.json"), "json")

    def test_duckdb_alias_compatibility(self):
        conn = duckdb.connect(":memory:")
        conn.execute("CREATE TABLE records (id INTEGER, raw_content TEXT, col_1 TEXT)")
        conn.execute("INSERT INTO records VALUES (1, '{\"a\": 1}', 'Acme')")
        query = 'SELECT id as "_row_id", raw_content as "_raw_content", col_1 as "job/title" FROM records'
        row = conn.execute(query).fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], '{"a": 1}')
        self.assertEqual(row[2], 'Acme')
        conn.close()

    def test_handle_compressed_file(self):
        from utils import handle_compressed_file
        import gzip
        import zipfile

        # 1. Test GZIP XML
        gz_path = os.path.join(self.test_dir.name, "feed.xml.gz")
        xml_data = b'<?xml version="1.0"?><jobs><job><title>GZ Engineer</title></job></jobs>'
        with gzip.open(gz_path, "wb") as gz:
            gz.write(xml_data)

        decomp_path, inner_name = handle_compressed_file(gz_path, "task_gz_1", self.test_dir.name)
        self.assertEqual(inner_name, "feed.xml")
        self.assertEqual(decomp_path, gz_path)
        with open(gz_path, "rb") as f:
            batches = list(stream_xml_batches(f, "job", batch_size=10))
            self.assertEqual(len(batches), 1)
            self.assertEqual(batches[0][0][0]["title"], "GZ Engineer")

        # 2. Test ZIP JSON
        zip_path = os.path.join(self.test_dir.name, "bundle.zip")
        json_data = b'{"jobs": [{"title": "Zip Engineer"}]}'
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "some info")
            zf.writestr("data/jobs.json", json_data)

        extracted_path, inner_name = handle_compressed_file(zip_path, "task_zip_1", self.test_dir.name)
        self.assertEqual(inner_name, "jobs.json")
        self.assertTrue(os.path.isfile(extracted_path))
        with open(extracted_path, "rb") as f:
            self.assertEqual(f.read(), json_data)

        # 3. Test plain XML passthrough
        plain_path = os.path.join(self.test_dir.name, "plain.xml")
        with open(plain_path, "wb") as f:
            f.write(xml_data)
        out_path, inner_name = handle_compressed_file(plain_path, "task_plain_1", self.test_dir.name)
        self.assertEqual(out_path, plain_path)
        self.assertEqual(inner_name, "plain.xml")

if __name__ == '__main__':
    unittest.main()
