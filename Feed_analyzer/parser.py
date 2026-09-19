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

try:
    import feed_core_rs
    HAS_RUST_CORE = True
except ImportError:
    HAS_RUST_CORE = False

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
    """Scans the beginning of an XML file to detect the repeating job element tag accurately."""
    if HAS_RUST_CORE:
        try:
            return feed_core_rs.detect_xml_job_element_rs(file_path, limit_bytes)
        except Exception as e:
            logger.debug(f"Rust XML detection fallback to Python: {e}")

    import math

    tag_counts = Counter()
    tag_depths = {}
    tag_parents = {}
    tag_child_tags = {}
    exact_casing = {}

    ROOT_CONTAINERS = {
        "root", "root-node", "source", "sources", "jobs", "jobfeed", "feed", "feeds", 
        "channel", "rss", "document", "results", "response", "data", "catalog", "items",
        "postings", "vacancies", "openings", "positions", "listings", "records", "array"
    }

    JOB_KEYWORDS = {
        "job": 100,
        "posting": 90,
        "position": 90,
        "vacancy": 90,
        "opening": 90,
        "opportunity": 85,
        "listing": 85,
        "career": 80,
        "offer": 80,
        "item": 75,
        "entry": 75,
        "record": 70,
        "requisition": 70,
        "work": 60,
    }

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

    with open(file_path, 'rb') as f:
        limited_f = LimitedReader(f, limit_bytes)
        try:
            stack = []
            context = ET.iterparse(limited_f, events=('start', 'end'))
            for event, elem in context:
                raw_tag = elem.tag.split('}', 1)[1] if '}' in elem.tag else elem.tag
                tag_lower = raw_tag.lower()
                if tag_lower not in exact_casing:
                    exact_casing[tag_lower] = raw_tag

                if event == 'start':
                    depth = len(stack)
                    parent_tag = stack[-1] if stack else None
                    stack.append(tag_lower)
                    
                    if parent_tag:
                        if tag_lower not in tag_parents:
                            tag_parents[tag_lower] = set()
                        tag_parents[tag_lower].add(parent_tag)

                        if parent_tag not in tag_child_tags:
                            tag_child_tags[parent_tag] = set()
                        tag_child_tags[parent_tag].add(tag_lower)

                    if tag_lower not in tag_depths or depth < tag_depths[tag_lower]:
                        tag_depths[tag_lower] = depth

                elif event == 'end':
                    if stack and stack[-1] == tag_lower:
                        stack.pop()
                    tag_counts[tag_lower] += 1
                    
                    # Only clear shallow elements to keep memory low
                    if len(stack) <= 1:
                        elem.clear()
        except Exception:
            pass

    # Score candidates
    candidates = {}
    for tag, count in tag_counts.items():
        depth = tag_depths.get(tag, 1)
        num_children = len(tag_child_tags.get(tag, set()))
        
        # Leaf tags (no children) cannot be the job record container
        if num_children == 0:
            continue
            
        # Root document tag (depth 0) cannot be the individual job
        if depth == 0:
            continue

        score = 0.0

        # Base score from keyword priority
        score += JOB_KEYWORDS.get(tag, 0)

        # Plural-to-singular parent match (e.g. parent <jobs> -> child <job>, <positions> -> <position>)
        parents = tag_parents.get(tag, set())
        for parent in parents:
            if parent in ROOT_CONTAINERS:
                score += 50
            if parent == tag + "s" or parent == tag + "es":
                score += 80

        # Prefer depth 1 or 2 (top-level records), heavily penalize deeply nested elements (depth >= 3)
        if depth == 1:
            score += 40
        elif depth == 2:
            score += 35
        elif depth == 3:
            score -= 40
        else:
            score -= 80

        # Elements with multiple diverse children are much more likely to be the full job record
        score += min(num_children * 5, 50)
        
        # Frequency bonus
        score += math.log2(count + 1) * 5

        # Penalize if this tag is inside a known job container
        for parent in parents:
            if parent in JOB_KEYWORDS:
                score -= 80

        candidates[tag] = (score, count, depth, num_children)

    if not candidates:
        return "job"

    best_tag_lower = max(candidates.keys(), key=lambda t: candidates[t][0])
    return exact_casing.get(best_tag_lower, best_tag_lower)

def detect_json_record_path(file_path: str, limit_bytes: int = 5*1024*1024) -> str:
    """Scans the beginning of a JSON file to detect the repeating record path."""
    if HAS_RUST_CORE:
        try:
            return feed_core_rs.detect_json_record_path_rs(file_path, limit_bytes)
        except Exception as e:
            logger.debug(f"Rust JSON detection fallback to Python: {e}")

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
    progress_callback: Optional[Callable[[int], None]] = None,
    reject_log_path: Optional[str] = None,
    strict_mode: bool = False,
    store_raw_content: bool = True
) -> Generator[Tuple[Dict[str, Any], str], None, None]:
    """Streams job element records from an XML file-like object using native Rust when available."""
    if HAS_RUST_CORE and hasattr(file_obj, 'name') and isinstance(file_obj.name, str) and os.path.isfile(file_obj.name) and not strict_mode:
        try:
            file_path = file_obj.name
            total_size = os.path.getsize(file_path)
            streamer = feed_core_rs.XmlRecordStreamer(file_path, job_element_tag, store_raw_content)
            record_idx = 0
            for json_str, raw_xml in streamer:
                record_idx += 1
                if progress_callback and (record_idx % 500 == 0):
                    progress_callback(min(total_size, record_idx * 1024))
                record_dict = json.loads(json_str)
                yield record_dict, raw_xml
            if record_idx == 0 and total_size == 0 and reject_log_path:
                os.makedirs(os.path.dirname(os.path.abspath(reject_log_path)), exist_ok=True)
                with open(reject_log_path, "a", encoding="utf-8") as rf:
                    rf.write("Parser level XML syntax error: no element found\n")
            if progress_callback:
                progress_callback(total_size)
            return
        except Exception as e_rust:
            if reject_log_path:
                os.makedirs(os.path.dirname(os.path.abspath(reject_log_path)), exist_ok=True)
                with open(reject_log_path, "a", encoding="utf-8") as rf:
                    rf.write(f"Parser level XML syntax error: {e_rust}\n")
            logger.debug(f"Rust XmlRecordStreamer fallback to iterparse: {e_rust}")
            if hasattr(file_obj, 'seek'):
                try:
                    file_obj.seek(0)
                except Exception:
                    pass

    wrapped_file = ProgressFileWrapper(file_obj, progress_callback)
    
    # Enable recovery directly inside iterparse to heal malformed tags
    try:
        context = ET.iterparse(wrapped_file, events=('end',), tag=job_element_tag, recover=not strict_mode)
        for event, elem in context:
            record_dict = element_to_dict(elem)
            raw_xml = ET.tostring(elem, encoding='utf-8', pretty_print=True).decode('utf-8') if store_raw_content else ""
            yield record_dict, raw_xml
            
            elem.clear()
            parent = elem.getparent()
            if parent is not None:
                while elem.getprevious() is not None:
                    del parent[0]
    except Exception as exc:
        if strict_mode:
            raise
        if reject_log_path:
            os.makedirs(os.path.dirname(os.path.abspath(reject_log_path)), exist_ok=True)
            with open(reject_log_path, "a", encoding="utf-8") as rf:
                rf.write(f"Parser level XML syntax error: {exc}\n")
        logger.warning(f"XML parse error encountered: {exc}")

def stream_json_records(
    file_obj: Any, 
    record_path: str, 
    progress_callback: Optional[Callable[[int], None]] = None,
    reject_log_path: Optional[str] = None,
    strict_mode: bool = False,
    store_raw_content: bool = True
) -> Generator[Tuple[Dict[str, Any], str], None, None]:
    """Streams record items from a JSON file-like object using ijson."""
    wrapped_file = ProgressFileWrapper(file_obj, progress_callback)
    
    try:
        items = ijson.items(wrapped_file, record_path)
        for item in items:
            if not isinstance(item, dict):
                record_dict = {"value": item}
            else:
                record_dict = item
                
            raw_json = json.dumps(item, indent=2, ensure_ascii=False) if store_raw_content else ""
            yield record_dict, raw_json
    except Exception as exc:
        if strict_mode:
            raise
        if reject_log_path:
            os.makedirs(os.path.dirname(os.path.abspath(reject_log_path)), exist_ok=True)
            with open(reject_log_path, "a", encoding="utf-8") as rf:
                rf.write(f"Parser level JSON syntax error: {exc}\n")
        logger.warning(f"JSON parse error encountered: {exc}")
