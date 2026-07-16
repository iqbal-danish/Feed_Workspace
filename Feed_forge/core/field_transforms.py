import re
from datetime import datetime

class TransformEngine:
    """Stateless transformation engine that applies a list of rules to mutate record fields."""
    
    @staticmethod
    def concat(context: dict, raw_row: dict, separator: str, *field_refs) -> str:
        """Concatenate values of fields or literal strings with a separator."""
        resolved = []
        for ref in field_refs:
            if isinstance(ref, str) and ref.startswith('$'):
                field_name = ref[1:]
                val = None
                if raw_row and field_name in raw_row:
                    val = raw_row[field_name]
                elif field_name in context:
                    val = context[field_name]
                resolved.append(str(val) if val is not None else '')
            else:
                resolved.append(str(ref))
        return separator.join(resolved)
        
    @staticmethod
    def substring(val: str, start: str, end: str) -> str:
        """Safely slice a string."""
        if not val:
            return ""
        try:
            s = int(start)
            e = int(end) if end else None
            return val[s:e]
        except ValueError:
            return val

    @staticmethod
    def tokenize(val: str, delimiter: str, index: str) -> str:
        """Split a string by a delimiter and extract the token at a specific 0-based index."""
        if not val:
            return ""
        try:
            idx = int(index)
            tokens = val.split(delimiter)
            if 0 <= idx < len(tokens):
                return tokens[idx]
            return ""
        except (ValueError, IndexError):
            return ""

    @staticmethod
    def replace(val: str, search_str: str, replace_str: str) -> str:
        """Replace occurrences of a substring."""
        if not val:
            return ""
        return val.replace(search_str, replace_str)

    @staticmethod
    def upper(val: str) -> str:
        """Convert to uppercase."""
        return val.upper() if val else ""

    @staticmethod
    def lower(val: str) -> str:
        """Convert to lowercase."""
        return val.lower() if val else ""

    @staticmethod
    def strip(val: str) -> str:
        """Trim leading and trailing whitespace."""
        return val.strip() if val else ""

    @staticmethod
    def title_case(val: str) -> str:
        """Convert string to Title Case."""
        return val.title() if val else ""

    @classmethod
    def default(cls, val: str, fallback: str) -> str:
        """Return fallback if value is empty/falsy."""
        if not val or not val.strip():
            return fallback
        return val

    @staticmethod
    def date_format(val: str, in_fmt: str, out_fmt: str) -> str:
        """Parse datetime string and convert it to another format. Returns original on error."""
        if not val:
            return ""
        try:
            dt = datetime.strptime(val.strip(), in_fmt)
            return dt.strftime(out_fmt)
        except Exception:
            return val

    @staticmethod
    def regex_replace(val: str, pattern: str, replacement: str) -> str:
        """Replace occurrences using regular expressions. Returns original on invalid regex."""
        if not val:
            return ""
        try:
            return re.sub(pattern, replacement, val)
        except Exception:
            return val

    @staticmethod
    def url_encode(val: str) -> str:
        """URL encode a string query safely."""
        if not val:
            return ""
        import urllib.parse
        return urllib.parse.quote(val)

    @staticmethod
    def url_decode(val: str) -> str:
        """URL decode an encoded string safely."""
        if not val:
            return ""
        import urllib.parse
        return urllib.parse.unquote(val)

    @staticmethod
    def contains(val: str, search_str: str, match_value: str, otherwise_value: str) -> str:
        """Return match_value if search_str is found in val, otherwise return otherwise_value."""
        if val is None:
            val = ""
        if str(search_str) in str(val):
            return match_value
        return otherwise_value

    @classmethod
    def apply(cls, row: dict, transforms: list[dict], raw_row: dict = None) -> dict:
        """
        Apply a list of transform dicts to mutate row values in-place.
        Each transform dict: { "target_field": str, "function": str, "args": list }
        """
        if not transforms:
            return row
            
        # Copy row to avoid modifying original reference
        row_copy = row.copy()
        
        # Sort transforms to ensure dependencies are handled if needed, 
        # or execute sequentially as defined in UI order.
        for t in transforms:
            target = t.get('target_field')
            func_name = t.get('function')
            args = t.get('args', [])
            
            if not target or not func_name:
                continue
                
            # Expose mapping function dictionary
            func_map = {
                'concat': lambda val, *a: cls.concat(row_copy, raw_row, *a),
                'substring': lambda val, *a: cls.substring(val, *a),
                'tokenize': lambda val, *a: cls.tokenize(val, *a),
                'replace': lambda val, *a: cls.replace(val, *a),
                'upper': lambda val, *a: cls.upper(val),
                'lower': lambda val, *a: cls.lower(val),
                'strip': lambda val, *a: cls.strip(val),
                'title_case': lambda val, *a: cls.title_case(val),
                'default': lambda val, *a: cls.default(val, *a),
                'date_format': lambda val, *a: cls.date_format(val, *a),
                'regex_replace': lambda val, *a: cls.regex_replace(val, *a),
                'url_encode': lambda val, *a: cls.url_encode(val),
                'url_decode': lambda val, *a: cls.url_decode(val),
                'contains': lambda val, *a: cls.contains(val, *a)
            }
            
            if func_name in func_map:
                current_val = str(row_copy.get(target, '') or '')
                try:
                    # Apply transform function and store result
                    res = func_map[func_name](current_val, *args)
                    row_copy[target] = res
                except Exception:
                    # Keep original value on failure
                    pass
                    
        return row_copy
