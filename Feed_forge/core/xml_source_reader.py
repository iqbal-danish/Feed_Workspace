import os
import requests
from lxml import etree
from collections import Counter

class XMLSourceReader:
    """Helper class to load XML files or URLs and extract fields and previews for column mapping."""
    
    @staticmethod
    def _clean_tag(tag: str) -> str:
        """Remove namespace prefix from tag name if present."""
        if tag and '}' in tag:
            return tag.split('}', 1)[1]
        return tag

    @classmethod
    def detect_repeating_xpath(cls, root) -> str:
        """
        Auto-detect repeating records XPath.
        Builds full paths of all elements with child nodes, and finds the most frequent path.
        """
        paths = []
        
        def traverse(element, current_path):
            tag = cls._clean_tag(element.tag)
            path = f"{current_path}/{tag}" if current_path else f"/{tag}"
            
            # Only consider elements that contain child elements as potential repeat nodes
            if len(element) > 0:
                paths.append(path)
                
            for child in element:
                traverse(child, path)
                
        traverse(root, "")
        
        if not paths:
            # Fallback if no nested elements exist (e.g. root contains only leaf tags)
            if len(root) > 0:
                first_child = cls._clean_tag(root[0].tag)
                return f"/{cls._clean_tag(root.tag)}/{first_child}"
            return f"/{cls._clean_tag(root.tag)}"
            
        # Count frequencies
        counter = Counter(paths)
        # Find the path with highest frequency > 1
        most_common = counter.most_common()
        for xpath, freq in most_common:
            if freq > 1:
                return xpath
                
        # If all paths appear once, pick the deepest path that is not a leaf
        return most_common[0][0]

    @classmethod
    def flatten_node(cls, node, prefix="", root_row=None) -> dict:
        """
        Recursively flatten an XML node's children and attributes into a dictionary.
        Returns a dictionary mapping field keys to values.
        """
        if root_row is None:
            root_row = {}
            
        # Extract attributes
        for attr_name, attr_val in node.attrib.items():
            clean_attr = cls._clean_tag(attr_name)
            attr_key = f"{prefix}@{clean_attr}" if prefix else f"@{clean_attr}"
            root_row[attr_key] = attr_val
            # Also store bare attribute if not already present
            if clean_attr not in root_row:
                root_row[clean_attr] = attr_val
                
        # Extract children
        has_children = False
        for child in node:
            has_children = True
            child_tag = cls._clean_tag(child.tag)
            child_prefix = f"{prefix}{child_tag}/" if prefix else f"{child_tag}/"
            
            # Recurse
            cls.flatten_node(child, child_prefix, root_row)
            
            # If the child is a leaf node, also expose its bare tag name
            if len(child) == 0:
                text_val = child.text.strip() if child.text else ""
                if child_tag not in root_row:
                    root_row[child_tag] = text_val
                    
        # If this is a leaf node, store its text
        if not has_children:
            text_val = node.text.strip() if node.text else ""
            leaf_key = prefix.rstrip('/') if prefix else cls._clean_tag(node.tag)
            root_row[leaf_key] = text_val
        return root_row

    @classmethod
    def detect_repeating_xpath_stream(cls, filepath_or_stream) -> str:
        """
        Auto-detect repeating records XPath incrementally using iterparse.
        Builds full paths of all elements with child nodes, and finds the most frequent path.
        Exits early after scanning 15,000 elements to avoid memory exhaustion and stay fast.
        """
        paths = []
        element_stack = []
        node_count = 0
        
        # We listen to both start and end events to maintain an active path stack
        context = etree.iterparse(filepath_or_stream, events=('start', 'end'))
        
        try:
            for event, elem in context:
                tag = cls._clean_tag(elem.tag)
                if event == 'start':
                    element_stack.append(tag)
                    node_count += 1
                    if node_count > 15000:
                        break
                elif event == 'end':
                    if len(elem) > 0:
                        current_path = "/" + "/".join(element_stack)
                        if current_path.count('/') <= 3:
                            paths.append(current_path)
                    
                    if element_stack:
                        element_stack.pop()
        except Exception:
            pass
            
        if not paths:
            return "/root/item"
            
        # Count frequencies
        counter = Counter(paths)
        most_common = counter.most_common()
        # Sort by frequency descending, then by depth (number of /) ascending to prefer shallower paths
        sorted_paths = sorted(most_common, key=lambda x: (-x[1], x[0].count('/')))
        for xpath, freq in sorted_paths:
            if freq > 1:
                return xpath
                
        return sorted_paths[0][0]

    @classmethod
    def detect_repeating_xpath(cls, root) -> str:
        """Legacy detection for backwards compatibility where root is already parsed."""
        paths = []
        
        def traverse(element, current_path):
            tag = cls._clean_tag(element.tag)
            path = f"{current_path}/{tag}" if current_path else f"/{tag}"
            if len(element) > 0:
                if path.count('/') <= 3:
                    paths.append(path)
            for child in element:
                traverse(child, path)
                
        traverse(root, "")
        if not paths:
            if len(root) > 0:
                first_child = cls._clean_tag(root[0].tag)
                return f"/{cls._clean_tag(root.tag)}/{first_child}"
            return f"/{cls._clean_tag(root.tag)}"
            
        counter = Counter(paths)
        most_common = counter.most_common()
        # Sort by frequency descending, then by depth (number of /) ascending to prefer shallower paths
        sorted_paths = sorted(most_common, key=lambda x: (-x[1], x[0].count('/')))
        for xpath, freq in sorted_paths:
            if freq > 1:
                return xpath
        return sorted_paths[0][0]

    @classmethod
    def get_records_from_tree(cls, root, record_xpath: str = None) -> list[dict]:
        """Legacy method for backwards compatibility."""
        if not record_xpath or not record_xpath.strip():
            record_xpath = cls.detect_repeating_xpath(root)
            
        if not record_xpath.startswith('/'):
            record_xpath = f"//{record_xpath}"
            
        nodes = root.xpath(record_xpath)
        records = []
        for node in nodes:
            records.append(cls.flatten_node(node))
        return records, record_xpath

    @classmethod
    def load_records_from_file(cls, filepath: str, record_xpath: str = None) -> tuple[list[dict], str]:
        """Parse XML file using etree.iterparse to stream records efficiently."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"XML file not found: {filepath}")
            
        # Auto-detect if not provided
        if not record_xpath or not record_xpath.strip():
            record_xpath = cls.detect_repeating_xpath_stream(filepath)
            
        # Standardize xpath
        if not record_xpath.startswith('/'):
            record_xpath = f"//{record_xpath}"
            
        target_tag = record_xpath.split('/')[-1]
        
        records = []
        element_stack = []
        
        context = etree.iterparse(filepath, events=('start', 'end'))
        try:
            for event, elem in context:
                tag = cls._clean_tag(elem.tag)
                if event == 'start':
                    element_stack.append(tag)
                elif event == 'end':
                    current_path = "/" + "/".join(element_stack)
                    path_matches = False
                    if current_path == record_xpath:
                        path_matches = True
                    elif record_xpath.startswith('//') and current_path.endswith(record_xpath[2:]):
                        path_matches = True
                        
                    if path_matches:
                        records.append(cls.flatten_node(elem))
                        elem.clear()
                        if elem.getparent() is not None:
                            while elem.getprevious() is not None:
                                del elem.getparent()[0]
                        
                    if element_stack:
                        element_stack.pop()
        except Exception:
            pass
            
        return records, record_xpath

    @classmethod
    def load_records_from_url(cls, url: str, record_xpath: str = None, auth_config: dict = None) -> tuple[list[dict], str]:
        """Fetch XML from URL, save to temp stream, and parse using etree.iterparse to keep memory footprint low."""
        headers = {}
        auth = None
        auth_config = auth_config or {}
        auth_type = auth_config.get('auth_type', 'none')
        
        if auth_type == 'basic':
            username = auth_config.get('username', '')
            password = auth_config.get('password', '')
            auth = (username, password)
        elif auth_type == 'bearer':
            token = auth_config.get('token', '')
            headers['Authorization'] = f"Bearer {token}"
        elif auth_type == 'apikey':
            header_name = auth_config.get('header_name', 'X-API-Key')
            header_value = auth_config.get('header_value', '')
            headers[header_name] = header_value
            
        try:
            response = requests.get(url, headers=headers, auth=auth, timeout=15)
            response.raise_for_status()
        except Exception as e:
            raise ValueError(f"Failed to fetch XML from URL: {str(e)}")
            
        import io
        xml_stream = io.BytesIO(response.content)
        
        # Auto-detect if not provided
        if not record_xpath or not record_xpath.strip():
            record_xpath = cls.detect_repeating_xpath_stream(xml_stream)
            xml_stream.seek(0)
            
        # Standardize xpath
        if not record_xpath.startswith('/'):
            record_xpath = f"//{record_xpath}"
            
        target_tag = record_xpath.split('/')[-1]
        
        records = []
        element_stack = []
        
        context = etree.iterparse(xml_stream, events=('start', 'end'))
        try:
            for event, elem in context:
                tag = cls._clean_tag(elem.tag)
                if event == 'start':
                    element_stack.append(tag)
                elif event == 'end':
                    current_path = "/" + "/".join(element_stack)
                    path_matches = False
                    if current_path == record_xpath:
                        path_matches = True
                    elif record_xpath.startswith('//') and current_path.endswith(record_xpath[2:]):
                        path_matches = True
                        
                    if path_matches:
                        records.append(cls.flatten_node(elem))
                        elem.clear()
                        if elem.getparent() is not None:
                            while elem.getprevious() is not None:
                                del elem.getparent()[0]
                        
                    if element_stack:
                        element_stack.pop()
        except Exception:
            pass
            
        return records, record_xpath

    @classmethod
    def get_preview(cls, records: list[dict], max_rows: int = 100) -> dict:
        """
        Takes list of record dictionaries and formats it for AG Grid.
        Exposes all discovered fields as columns.
        """
        # Discover all unique fields across records
        unique_fields = set()
        for r in records:
            unique_fields.update(r.keys())
            
        # Sort fields so simpler fields come first (e.g. tag vs tag/subtag)
        sorted_fields = sorted(list(unique_fields), key=lambda x: (x.count('/'), x.count('@'), x))
        
        # Build AG Grid column definitions
        columns = []
        for i, field in enumerate(sorted_fields):
            field_id = f"col_{i}"
            columns.append({
                "headerName": field,
                "field": field_id,
                "original_field": field  # Carry original XML field key for column mapping
            })
            
        # Re-map record keys to col_index names
        preview_data = []
        for r in records[:max_rows]:
            row_data = {}
            for col in columns:
                orig = col["original_field"]
                row_data[col["field"]] = r.get(orig, None)
            preview_data.append(row_data)
            
        return {
            "columns": columns,
            "data": preview_data,
            "total_rows": len(records)
        }
