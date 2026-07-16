import os
import urllib.request
import urllib.error
import json
import logging
from collections import Counter
from typing import Generator, Dict, Any, Tuple, Optional, Callable
import lxml.etree as ET
import ijson

logger = logging.getLogger(__name__)

class ProgressFileWrapper:
    """Wraps a file-like object and reports bytes read to a callback."""
    def __init__(self, file_obj: Any, callback: Optional[Callable[[int], None]] = None):
        self.file_obj = file_obj
        self.callback = callback
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        data = self.file_obj.read(size)
        self.bytes_read += len(data)
        if self.callback:
            self.callback(self.bytes_read)
        return data

    def readline(self, limit: int = -1) -> bytes:
        data = self.file_obj.readline(limit)
        self.bytes_read += len(data)
        if self.callback:
            self.callback(self.bytes_read)
        return data

    def seek(self, offset: int, whence: int = 0) -> int:
        res = self.file_obj.seek(offset, whence)
        if whence == 0:
            self.bytes_read = offset
        elif whence == 1:
            self.bytes_read += offset
        else:
            self.bytes_read = self.file_obj.tell()
        return res

    def tell(self) -> int:
        return self.file_obj.tell()

    def close(self) -> None:
        if hasattr(self.file_obj, 'close'):
            self.file_obj.close()

def get_url_stream(url: str, timeout: int = 30) -> Tuple[Any, int]:
    """Downloads a URL as a stream and returns the stream and content length."""
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) XML Feed Analyzer'}
    )
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
        content_length = response.headers.get('Content-Length')
        size = int(content_length) if content_length else 0
        return response, size
    except urllib.error.URLError as e:
        logger.error(f"URL Error: {e.reason}")
        raise ValueError(f"Failed to connect to URL: {e.reason}")
    except Exception as e:
        logger.error(f"Failed to stream URL: {e}")
        raise ValueError(f"Network error: {str(e)}")

def detect_xml_job_element(file_path: str, limit_bytes: int = 5*1024*1024) -> str:
    """Scans the beginning of an XML file to detect the repeating job element tag."""
    tags = Counter()
    depths = {}
    has_children = set()
    
    with open(file_path, 'rb') as f:
        class LimitedReader:
            def __init__(self, f, limit):
                self.f = f
                self.limit = limit
                self.read_bytes = 0
            def read(self, size=-1):
                if self.read_bytes >= self.limit:
                    return b""
                chunk = self.f.read(min(size, self.limit - self.read_bytes))
                self.read_bytes += len(chunk)
                return chunk
                
        limited_f = LimitedReader(f, limit_bytes)
        try:
            context = ET.iterparse(limited_f, events=('end',))
            for event, elem in context:
                tag = elem.tag
                if '}' in tag:
                    tag = tag.split('}', 1)[1] # Strip namespaces
                
                # Element has children, suggesting it is a container/job element
                if len(elem) > 0:
                    tags[tag] += 1
                    has_children.add(tag)
                    
                    # Calculate depth
                    depth = 0
                    parent = elem.getparent()
                    while parent is not None:
                        depth += 1
                        parent = parent.getparent()
                        
                    if tag not in depths or depth < depths[tag]:
                        depths[tag] = depth
                elem.clear()
        except Exception:
            # Parse errors are expected when truncating the file
            pass

    # Find the tag with the highest score: count / (depth + 0.1)
    # We ignore depth 0 (which is the root tag)
    best_tag = "job"
    best_score = -1.0
    
    for tag, count in tags.items():
        if tag in has_children:
            depth = depths.get(tag, 1)
            if depth == 0 or depth > 3:
                continue # Skip root tag and deeply nested child elements (e.g. customfield)
            score = count / (depth + 0.1)
            if score > best_score:
                best_score = score
                best_tag = tag
                
    return best_tag

def detect_json_record_path(file_path: str, limit_bytes: int = 5*1024*1024) -> str:
    """Scans the beginning of a JSON file to detect the repeating record path."""
    prefixes = Counter()
    
    with open(file_path, 'rb') as f:
        class LimitedReader:
            def __init__(self, f, limit):
                self.f = f
                self.limit = limit
                self.read_bytes = 0
            def read(self, size=-1):
                if self.read_bytes >= self.limit:
                    return b""
                chunk = self.f.read(min(size, self.limit - self.read_bytes))
                self.read_bytes += len(chunk)
                return chunk
                
        limited_f = LimitedReader(f, limit_bytes)
        try:
            parser = ijson.parse(limited_f)
            for prefix, event, value in parser:
                if event in ('start_map', 'start_array') and prefix:
                    if prefix.endswith('.item') or prefix == 'item':
                        prefixes[prefix] += 1
        except Exception:
            pass

    if prefixes:
        return prefixes.most_common(1)[0][0]
    return "item"

def element_to_dict(element: ET._Element) -> Any:
    """Converts an XML element and its children into a nested dictionary."""
    d: Dict[str, Any] = {}
    
    # Extract attributes
    for k, v in element.attrib.items():
        attr_name = k.split('}', 1)[1] if '}' in k else k
        d[f"@{attr_name}"] = v
    
    # Extract text content
    text = element.text.strip() if element.text else ""
    
    # Process children
    has_children = False
    for child in element:
        has_children = True
        child_tag = child.tag.split('}', 1)[1] if '}' in child.tag else child.tag
        child_data = element_to_dict(child)
        
        if child_tag in d:
            if isinstance(d[child_tag], list):
                d[child_tag].append(child_data)
            else:
                d[child_tag] = [d[child_tag], child_data]
        else:
            d[child_tag] = child_data
            
    if not has_children:
        if d: # If attributes exist, store text in '#text'
            if text:
                d["#text"] = text
            return d
        return text
        
    if text:
        d["#text"] = text
    return d

def stream_xml_records(
    file_obj: Any, 
    job_element_tag: str, 
    progress_callback: Optional[Callable[[int], None]] = None
) -> Generator[Tuple[Dict[str, Any], str], None, None]:
    """Streams job element records from an XML file-like object."""
    wrapped_file = ProgressFileWrapper(file_obj, progress_callback)
    
    # Enable recovery directly inside iterparse to heal malformed tags
    context = ET.iterparse(wrapped_file, events=('end',), tag=job_element_tag, recover=True)
    
    for event, elem in context:
        # Convert element to dictionary
        record_dict = element_to_dict(elem)
        
        # Serialize raw XML representation
        raw_xml = ET.tostring(elem, encoding='utf-8', pretty_print=True).decode('utf-8')
        
        yield record_dict, raw_xml
        
        # Clear elements to save memory
        elem.clear()
        parent = elem.getparent()
        if parent is not None:
            parent.remove(elem)
def stream_json_records(
    file_obj: Any, 
    record_path: str, 
    progress_callback: Optional[Callable[[int], None]] = None
) -> Generator[Tuple[Dict[str, Any], str], None, None]:
    """Streams record items from a JSON file-like object using ijson."""
    wrapped_file = ProgressFileWrapper(file_obj, progress_callback)
    
    # ijson.items yields dictionary objects directly
    items = ijson.items(wrapped_file, record_path)
    
    for item in items:
        # Standardize record representation (must be a dictionary)
        if not isinstance(item, dict):
            # Wrap primitives in a dictionary
            record_dict = {"value": item}
        else:
            record_dict = item
            
        # Serialize raw JSON string representation
        raw_json = json.dumps(item, indent=2, ensure_ascii=False)
        
        yield record_dict, raw_json
