from pathlib import Path
from lxml import etree
from validator.parser import StreamingXMLParser
from validator.models import ErrorCategory

def test_catches_boolean_attribute_deep_in_file(tmp_path: Path):
    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<root>']
    # 200 items before the bad tag
    for i in range(200):
        xml_lines.append(f'<job id="{i}"><title>Job {i}</title></job>')
    xml_lines.append('<include_ai_disclaind control>bad attribute</include_ai_disclaind>')
    for i in range(200):
        xml_lines.append(f'<job id="{i+200}"><title>Job {i+200}</title></job>')
    xml_lines.append('</root>')

    test_file = tmp_path / "deep_error.xml"
    test_file.write_text("\n".join(xml_lines), encoding="utf-8")

    parser = StreamingXMLParser()
    errors, file_info = parser.parse(test_file)

    assert len(errors) >= 1
    # Check that the error at line 203 (or the bad tag line) is caught
    error_messages = [e.message for e in errors]
    assert any("control" in msg or "attribute" in msg.lower() for msg in error_messages)
    error_lines = [e.line for e in errors]
    assert any(e.line >= 200 for e in errors)
