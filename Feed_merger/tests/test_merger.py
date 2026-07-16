import sqlite3
from pathlib import Path
from lxml import etree
import pytest

from config import MergerConfig
from core.deduplicator import SQLiteDeduplicator
from core.parser import XMLFeedParser
from core.validator import FileValidator
from core.writer import get_stream_writer, XMLStreamWriter, JSONStreamWriter


def test_file_validator(tmp_path: Path):
    validator = FileValidator()
    
    # Valid XML file
    valid_xml = tmp_path / "valid.xml"
    valid_xml.write_text("<root><child>text</child></root>", encoding="utf-8")
    assert validator.validate_file(valid_xml) is True

    # Invalid XML file
    invalid_xml = tmp_path / "invalid.xml"
    invalid_xml.write_text("<root><child>text</child>", encoding="utf-8")
    assert validator.validate_file(invalid_xml) is False

    # Valid JSON file
    valid_json = tmp_path / "valid.json"
    valid_json.write_text('[{"title": "Job 1"}]', encoding="utf-8")
    assert validator.validate_file(valid_json) is True

    # Invalid JSON file
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text('[{"title": "Job 1"', encoding="utf-8")
    assert validator.validate_file(invalid_json) is False


def test_parser_and_release(tmp_path: Path):
    xml_data = """<?xml version="1.0" encoding="UTF-8"?>
    <source>
        <job>
            <id>job_1</id>
            <title>Software Engineer</title>
        </job>
        <item>
            <id>job_2</id>
            <title>Data Scientist</title>
        </item>
        <other_tag>Not a job</other_tag>
    </source>
    """
    feed_file = tmp_path / "feed.xml"
    feed_file.write_text(xml_data, encoding="utf-8")

    config = MergerConfig(job_node_names=("job", "item"))
    parser = XMLFeedParser(config)
    
    jobs = list(parser.iter_jobs(feed_file))
    assert len(jobs) == 2
    
    titles = []
    for job in jobs:
        # Note: Since iter_jobs yields elements and then clears them in the next iteration,
        # we can only read properties if we do it inside a loop or read them before clearing.
        # But wait, in our test list(parser.iter_jobs(feed_file)) immediately calls next() on iter_jobs,
        # which clears the previous job element! So elements inside `jobs` might have already been cleared.
        # Let's check how iter_jobs releases them: it calls clear() in the next iteration.
        # So we should extract titles inline in the generator.
        pass

    # Let's re-run and extract titles inline to verify correct values before they are cleared:
    titles_inline = []
    for job in parser.iter_jobs(feed_file):
        title_el = job.find("title")
        if title_el is not None:
            titles_inline.append(title_el.text)
            
    assert titles_inline == ["Software Engineer", "Data Scientist"]


def test_sqlite_deduplicator(tmp_path: Path):
    db_path = tmp_path / "duplicates.sqlite3"
    duplicate_fields = ("id", "url")
    
    # Job 1: Has id and url
    job_1_xml = etree.fromstring("<job><id>123</id><url>http://example.com/123</url></job>")
    # Job 2: Has same id, no url (should be treated as duplicate by ID)
    job_2_xml = etree.fromstring("<job><id>123</id></job>")
    # Job 3: Has different id, same url (should be treated as duplicate by URL)
    job_3_xml = etree.fromstring("<job><id>456</id><url>http://example.com/123</url></job>")
    # Job 4: Has different id, different url (should be unique)
    job_4_xml = etree.fromstring("<job><id>456</id><url>http://example.com/456</url></job>")
    # Job 5: Has nested company id but no job id (should NOT match job 123)
    job_5_xml = etree.fromstring("<job><company><id>123</id></company><title>Title</title></job>")

    with SQLiteDeduplicator(db_path, duplicate_fields) as dedupe:
        # Job 1 is first seen, so not a duplicate
        assert dedupe.seen(job_1_xml) is False
        
        # Job 2 shares ID '123', so it is a duplicate
        assert dedupe.seen(job_2_xml) is True
        
        # Job 3 shares URL 'http://example.com/123', so it is a duplicate
        assert dedupe.seen(job_3_xml) is True
        
        # Job 4 has unique ID '456' and unique URL 'http://example.com/456', so unique
        assert dedupe.seen(job_4_xml) is False

        # Job 5 has no top-level job ID. Its nested company ID should not be matched.
        # It has no unique fields, so it falls back to XML hash. First seen, so unique.
        assert dedupe.seen(job_5_xml) is False


def test_xml_stream_writer(tmp_path: Path):
    output_file = tmp_path / "output.xml"
    
    with XMLStreamWriter(output_file, "root_node") as writer:
        el = etree.fromstring("<job><title>Job Title</title></job>")
        writer.write_element(el)
        
    content = output_file.read_text(encoding="utf-8")
    assert '<?xml version="1.0" encoding="UTF-8"?>' in content
    assert "<root_node>" in content
    assert "<job>" in content
    assert "<title>Job Title</title>" in content
    assert "</root_node>" in content


def test_json_parser(tmp_path: Path):
    # Test 1: Flat JSON array with .json extension
    json_data1 = '[{"title": "Job 1", "company": "Acme"}, {"title": "Job 2", "company": "Global"}]'
    feed_file1 = tmp_path / "feed.json"
    feed_file1.write_text(json_data1, encoding="utf-8")

    config = MergerConfig()
    parser = XMLFeedParser(config)
    
    jobs1 = list(parser.iter_jobs(feed_file1))
    assert len(jobs1) == 2
    assert "".join(jobs1[0].find("title").itertext()).strip() == "Job 1"
    assert "".join(jobs1[1].find("company").itertext()).strip() == "Global"

    # Test 2: Nested JSON array with root wrapper and disguised as .xml extension
    json_data2 = '{"nowfullfeed": {"jobfeed": {"jobs": [{"title": "Job 3", "company": {"name": "Tech Corp"}}]}}}'
    feed_file2 = tmp_path / "feed.xml"  # XML extension, but content is JSON!
    feed_file2.write_text(json_data2, encoding="utf-8")

    jobs2 = list(parser.iter_jobs(feed_file2))
    assert len(jobs2) == 1
    assert "".join(jobs2[0].find("title").itertext()).strip() == "Job 3"
    
    # Nested field company.name should be flattened to company_name
    assert "".join(jobs2[0].find("company_name").itertext()).strip() == "Tech Corp"


def test_json_stream_writer(tmp_path: Path):
    output_file = tmp_path / "output.json"
    
    with get_stream_writer(output_file, "root_node") as writer:
        el = etree.fromstring("<job><title>Job Title</title><company>Acme</company></job>")
        writer.write_element(el)
        
    content = output_file.read_text(encoding="utf-8")
    import json
    data = json.loads(content)
    assert len(data) == 1
    assert data[0]["title"] == "Job Title"
    assert data[0]["company"] == "Acme"
