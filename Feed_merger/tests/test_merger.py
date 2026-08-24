import asyncio
import json
import sqlite3
from pathlib import Path
from lxml import etree
import pytest

from config import MergerConfig
from core.deduplicator import SQLiteDeduplicator
from core.merger import FeedMerger
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

    titles_inline = []
    for job in parser.iter_jobs(feed_file):
        title_el = job.find("title")
        if title_el is not None:
            titles_inline.append(title_el.text)
            
    assert titles_inline == ["Software Engineer", "Data Scientist"]


def test_parser_custom_repeating_tag(tmp_path: Path):
    xml_data = """<?xml version="1.0" encoding="UTF-8"?>
    <custom_export>
        <opportunity>
            <req_id>req_99</req_id>
            <title>Project Manager</title>
        </opportunity>
        <opportunity>
            <req_id>req_100</req_id>
            <title>DevOps Engineer</title>
        </opportunity>
    </custom_export>
    """
    feed_file = tmp_path / "custom.xml"
    feed_file.write_text(xml_data, encoding="utf-8")

    config = MergerConfig()
    parser = XMLFeedParser(config)

    titles = []
    for job in parser.iter_jobs(feed_file):
        title_el = job.find("title")
        if title_el is not None:
            titles.append(title_el.text)

    assert titles == ["Project Manager", "DevOps Engineer"]


def test_sqlite_deduplicator(tmp_path: Path):
    db_path = tmp_path / "duplicates.sqlite3"
    duplicate_fields = ("id", "url")
    
    job_1_xml = etree.fromstring("<job><id>123</id><url>http://example.com/123</url></job>")
    job_2_xml = etree.fromstring("<job><id>123</id></job>")
    job_3_xml = etree.fromstring("<job><id>456</id><url>http://example.com/123</url></job>")
    job_4_xml = etree.fromstring("<job><id>456</id><url>http://example.com/456</url></job>")
    job_5_xml = etree.fromstring("<job><company><id>123</id></company><title>Title</title></job>")

    with SQLiteDeduplicator(db_path, duplicate_fields) as dedupe:
        assert dedupe.seen(job_1_xml) is False
        assert dedupe.seen(job_2_xml) is True
        assert dedupe.seen(job_3_xml) is True
        assert dedupe.seen(job_4_xml) is False
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
    json_data1 = '[{"title": "Job 1", "company": "Acme"}, {"title": "Job 2", "company": "Global"}]'
    feed_file1 = tmp_path / "feed.json"
    feed_file1.write_text(json_data1, encoding="utf-8")

    config = MergerConfig()
    parser = XMLFeedParser(config)
    
    jobs1 = list(parser.iter_jobs(feed_file1))
    assert len(jobs1) == 2
    assert "".join(jobs1[0].find("title").itertext()).strip() == "Job 1"
    assert "".join(jobs1[1].find("company").itertext()).strip() == "Global"


def test_json_stream_writer(tmp_path: Path):
    output_file = tmp_path / "output.json"
    
    with get_stream_writer(output_file, "root_node") as writer:
        el = etree.fromstring("<job><title>Job Title</title><company>Acme</company></job>")
        writer.write_element(el)
        
    content = output_file.read_text(encoding="utf-8")
    data = json.loads(content)
    assert len(data) == 1
    assert data[0]["title"] == "Job Title"
    assert data[0]["company"] == "Acme"


def test_full_pipeline_merger(tmp_path: Path):
    feed1 = tmp_path / "feed1.xml"
    feed1.write_text("""<?xml version="1.0"?>
    <source>
        <job><id>1</id><title>Dev 1</title></job>
        <job><id>2</id><title>Dev 2</title></job>
    </source>
    """, encoding="utf-8")

    feed2 = tmp_path / "feed2.xml"
    feed2.write_text("""<?xml version="1.0"?>
    <source>
        <job><id>2</id><title>Dev 2 Duplicate</title></job>
        <job><id>3</id><title>Dev 3</title></job>
    </source>
    """, encoding="utf-8")

    feeds_json = tmp_path / "feeds.json"
    feeds_json.write_text(json.dumps([
        {"type": "file", "path": str(feed1)},
        {"type": "file", "path": str(feed2)}
    ]), encoding="utf-8")

    output_xml = tmp_path / "merged.xml"
    db_path = tmp_path / "dedupe.sqlite3"

    config = MergerConfig(
        output_file=output_xml,
        feeds_file=tmp_path / "feeds.txt",
        duplicate_db=db_path,
        downloads_dir=tmp_path / "downloads",
        logs_dir=tmp_path / "logs",
        temp_dir=tmp_path / "tmp",
        statistics_file=tmp_path / "stats.json"
    )

    merger = FeedMerger(config)
    asyncio.run(merger.run(config.feeds_file))

    assert merger.statistics.total_feeds == 2
    assert merger.statistics.successful_feeds == 2
    assert merger.statistics.jobs_parsed == 4
    assert merger.statistics.jobs_written == 3
    assert merger.statistics.duplicates_removed == 1

    validator = FileValidator()
    assert validator.validate_file(output_xml) is True


def test_merger_with_source_tagging(tmp_path: Path):
    feed1 = tmp_path / "feed_src.xml"
    feed1.write_text("""<?xml version="1.0"?>
    <source>
        <job><id>job_alpha</id><title>Software Engineer</title></job>
    </source>
    """, encoding="utf-8")

    feeds_json = tmp_path / "feeds.json"
    feeds_json.write_text(json.dumps([
        {"type": "file", "path": str(feed1)}
    ]), encoding="utf-8")

    output_xml = tmp_path / "tagged.xml"
    db_path = tmp_path / "dedupe_tag.sqlite3"

    config = MergerConfig(
        output_file=output_xml,
        feeds_file=tmp_path / "feeds.txt",
        duplicate_db=db_path,
        downloads_dir=tmp_path / "downloads",
        logs_dir=tmp_path / "logs",
        temp_dir=tmp_path / "tmp",
        statistics_file=tmp_path / "stats.json",
        tag_source_feed=True,
        source_tag_name="source_feed_url"
    )

    merger = FeedMerger(config)
    asyncio.run(merger.run(config.feeds_file))

    content = output_xml.read_text(encoding="utf-8")
    assert "<source_feed_url>" in content
    assert str(feed1) in content

