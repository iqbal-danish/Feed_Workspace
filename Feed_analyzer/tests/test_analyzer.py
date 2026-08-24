import os
import sys
import unittest
import sqlite3
import tempfile
import json
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from parser import (
    detect_xml_job_element,
    detect_json_record_path,
    stream_xml_records,
    stream_json_records,
    element_to_dict
)
import lxml.etree as ET
from analyzer import FeedAnalyzerDb
from filters import compile_filters
from search import compile_search
from app import app as flask_app
import config

class TestFeedAnalyzer(unittest.TestCase):
    def setUp(self):
        # Create temp files for testing
        self.temp_xml = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
        self.temp_json = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close() # Close it so SQLite can bind to it
        
        # Mock XML Content
        self.xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
        <jobs_feed>
            <job id="1">
                <title>Software Engineer</title>
                <employer>Google</employer>
                <location>
                    <city>Mountain View</city>
                    <state>CA</state>
                </location>
                <tags>Python</tags>
                <tags>Flask</tags>
            </job>
            <job id="2">
                <title>Data Scientist</title>
                <employer>Meta</employer>
                <location>
                    <city>Seattle</city>
                    <state>WA</state>
                </location>
                <tags>SQL</tags>
                <tags>Pandas</tags>
            </job>
        </jobs_feed>
        """
        self.temp_xml.write(self.xml_content)
        self.temp_xml.close()
        
        # Mock JSON Content
        self.json_content = json.dumps({
            "positions": [
                {
                    "title": "Backend Dev",
                    "company": "Amazon",
                    "skills": ["Python", "AWS"]
                },
                {
                    "title": "Frontend Dev",
                    "company": "Apple",
                    "skills": ["JS", "React"]
                }
            ]
        }).encode('utf-8')
        self.temp_json.write(self.json_content)
        self.temp_json.close()

    def tearDown(self):
        # Clean up temp files
        os.remove(self.temp_xml.name)
        os.remove(self.temp_json.name)
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)

    def test_xml_detection(self):
        """Verifies XML repeating record element auto-detection."""
        detected = detect_xml_job_element(self.temp_xml.name)
        self.assertEqual(detected, "job")

    def test_complex_greenhouse_xml_detection(self):
        """Verifies nested Greenhouse XML detects job rather than inner data_compliance."""
        complex_xml = '''<?xml version="1.0" encoding="UTF-8"?>
        <root-node>
          <jobs type="array">
            <job>
              <absolute_url>https://boards.greenhouse.io/spacex/jobs/1</absolute_url>
              <data_compliance type="array">
                <data_compliance>
                  <type>gdpr</type>
                  <requires_consent>false</requires_consent>
                </data_compliance>
              </data_compliance>
              <title>Accountant</title>
              <company_name>SpaceX</company_name>
            </job>
            <job>
              <absolute_url>https://boards.greenhouse.io/spacex/jobs/2</absolute_url>
              <data_compliance type="array">
                <data_compliance>
                  <type>gdpr</type>
                  <requires_consent>false</requires_consent>
                </data_compliance>
              </data_compliance>
              <title>Engineer</title>
              <company_name>SpaceX</company_name>
            </job>
          </jobs>
        </root-node>'''
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode="w", encoding="utf-8")
        temp.write(complex_xml)
        temp.close()
        try:
            detected = detect_xml_job_element(temp.name)
            self.assertEqual(detected, "job")
        finally:
            if os.path.exists(temp.name):
                os.remove(temp.name)

    def test_json_detection(self):
        """Verifies JSON repeating record path auto-detection."""
        detected = detect_json_record_path(self.temp_json.name)
        self.assertEqual(detected, "positions.item")

    def test_xml_streaming(self):
        """Verifies streaming XML parser output."""
        with open(self.temp_xml.name, 'rb') as f:
            records = list(stream_xml_records(f, "job"))
            
        self.assertEqual(len(records), 2)
        rec1_dict, rec1_raw = records[0]
        self.assertEqual(rec1_dict["title"], "Software Engineer")
        self.assertEqual(rec1_dict["@id"], "1")
        self.assertEqual(rec1_dict["location"]["city"], "Mountain View")
        # Repeating elements check: "tags" should be parsed as a list!
        self.assertIsInstance(rec1_dict["tags"], list)
        self.assertEqual(rec1_dict["tags"], ["Python", "Flask"])
        self.assertIn("<job id=\"1\">", rec1_raw)

    def test_json_streaming(self):
        """Verifies streaming JSON parser output."""
        with open(self.temp_json.name, 'rb') as f:
            records = list(stream_json_records(f, "positions.item"))
            
        self.assertEqual(len(records), 2)
        rec1_dict, rec1_raw = records[0]
        self.assertEqual(rec1_dict["title"], "Backend Dev")
        self.assertEqual(rec1_dict["company"], "Amazon")
        self.assertEqual(rec1_dict["skills"], ["Python", "AWS"])

    def test_sqlite_db_insertion(self):
        """Verifies database insertion and schema dynamic column creation."""
        db = FeedAnalyzerDb(self.temp_db.name)
        
        # Insert records batch
        records_batch = [
            ({"title": "Dev", "employer": "Google", "loc": {"city": "Austin"}}, "<job>1</job>"),
            ({"title": "PM", "employer": "Meta", "salary": 120000}, "<job>2</job>")
        ]
        db.insert_records(records_batch)
        db.close()
        
        # Check column mappings
        self.assertIn("title", db.field_mappings)
        self.assertIn("employer", db.field_mappings)
        self.assertIn("loc/city", db.field_mappings)
        self.assertIn("salary", db.field_mappings)
        
        # Verify database contents
        conn = sqlite3.connect(self.temp_db.name)
        cursor = conn.execute("SELECT COUNT(*) FROM records")
        self.assertEqual(cursor.fetchone()[0], 2)
        conn.close()

    def test_filters_compilation(self):
        """Verifies visual query filter-to-SQL compilation."""
        mappings = {
            "title": "col_0",
            "employer": "col_1",
            "salary": "col_2"
        }
        
        filters = [
            {"field": "title", "operator": "Contains", "value": "Engineer"},
            {"field": "salary", "operator": "Greater Than", "value": "100000"},
            {"field": "employer", "operator": "Exists"}
        ]
        
        where_sql, params = compile_filters(filters, mappings)
        self.assertIn("col_0 ILIKE ?", where_sql)
        self.assertIn("CAST(col_2 AS REAL) > ?", where_sql)
        self.assertIn("col_1 IS NOT NULL AND col_1 != ''", where_sql)
        
        self.assertEqual(params[0], "%Engineer%")
        self.assertEqual(params[1], 100000.0)

    def test_search_compilation(self):
        """Verifies simple and multi-field text search compilation."""
        mappings = {
            "title": "col_0",
            "employer": "col_1"
        }
        
        # 1. Search in specific field
        where_sql, params = compile_search("Google", "Exact Match", "employer", mappings)
        self.assertEqual(where_sql, "col_1 = ?")
        self.assertEqual(params, ["Google"])
        
        # 2. Search all fields
        where_sql, params = compile_search("Python", "Contains", "all", mappings)
        self.assertIn("col_0 ILIKE ?", where_sql)
        self.assertIn("col_1 ILIKE ?", where_sql)
        self.assertIn("OR", where_sql)
        self.assertEqual(params, ["%Python%", "%Python%"])


class TestFeedAnalyzerExports(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.original_db_folder = config.DB_FOLDER
        self.original_report_folder = config.REPORT_FOLDER
        config.DB_FOLDER = os.path.join(self.temp_root, "databases")
        config.REPORT_FOLDER = os.path.join(self.temp_root, "reports")
        os.makedirs(config.DB_FOLDER, exist_ok=True)
        os.makedirs(config.REPORT_FOLDER, exist_ok=True)

        self.task_id = "export-test"
        self.db_path = os.path.join(config.DB_FOLDER, f"{self.task_id}.db")
        db = FeedAnalyzerDb(self.db_path)
        db.insert_records([
            ({"title": "Engineer", "company": "Acme"}, '{"title":"Engineer"}'),
            ({"title": "Analyst", "company": "Beta"}, '{"title":"Analyst"}'),
        ])
        db.save_metadata({"filename": "sample_feed"})
        db.close()

        flask_app.config["TESTING"] = True
        self.client = flask_app.test_client()

    def tearDown(self):
        config.DB_FOLDER = self.original_db_folder
        config.REPORT_FOLDER = self.original_report_folder
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_export_csv_accepts_json_payload(self):
        response = self.client.post(
            f"/export/{self.task_id}/csv",
            json={"export_type": "query", "filters": []}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(response.mimetype, ("text/csv", "application/vnd.ms-excel"))
        self.assertIn("attachment;", response.headers.get("Content-Disposition", ""))
        self.assertIn("sample_feed_query.csv", response.headers.get("Content-Disposition", ""))
        self.assertIn("title", response.get_data(as_text=True))
        self.assertNotIn("Raw XML/JSON Content", response.get_data(as_text=True))

    def test_export_csv_accepts_form_payload(self):
        response = self.client.post(
            f"/export/{self.task_id}/csv",
            data={"payload": json.dumps({"export_type": "query", "filters": []})}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(response.mimetype, ("text/csv", "application/vnd.ms-excel"))
        self.assertIn("attachment;", response.headers.get("Content-Disposition", ""))
        self.assertIn("sample_feed_query.csv", response.headers.get("Content-Disposition", ""))
        self.assertIn("Engineer", response.get_data(as_text=True))
        self.assertNotIn('{"title":"Engineer"}', response.get_data(as_text=True))

if __name__ == '__main__':
    unittest.main()
