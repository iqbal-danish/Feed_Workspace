import re
from lxml import etree

class TemplateParser:
    """Helper class to validate XML templates and extract variables (placeholders)."""
    
    @staticmethod
    def extract_placeholders(xml_content: str) -> list[str]:
        """
        Scan XML text for double curly braces `{{ placeholder }}` and return
        a list of unique placeholders, preserving their order of appearance.
        """
        # Match alphanumeric and underscore characters inside {{ }}
        pattern = r'\{\{\s*([a-zA-Z0-9_]+)\s*\}\}'
        matches = re.findall(pattern, xml_content)
        
        # Remove duplicates while preserving original order
        seen = set()
        unique_placeholders = []
        for placeholder in matches:
            if placeholder not in seen:
                seen.add(placeholder)
                unique_placeholders.append(placeholder)
                
        return unique_placeholders

    @staticmethod
    def validate_template(xml_content: str) -> tuple[bool, str | None]:
        """
        Validate if the XML content is well-formed.
        Returns a tuple: (is_valid, error_message).
        """
        if not xml_content.strip():
            return False, "Template is empty."
            
        try:
            # Parse XML bytes to check for well-formedness
            # Since lxml parses XML, it expects a single root element
            etree.fromstring(xml_content.strip().encode('utf-8'))
            return True, None
        except etree.XMLSyntaxError as e:
            return False, f"XML Syntax Error: {str(e)}"
        except Exception as e:
            return False, f"Template Validation Error: {str(e)}"
