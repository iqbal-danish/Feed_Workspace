import os
import re
import pandas as pd
import numpy as np
from lxml import etree
from jinja2 import Template
from xml.sax.saxutils import escape

class XMLGenerator:
    """Core XML template compilation engine supporting deep nesting and dynamic configurations."""
    
    @staticmethod
    def _find_lca(nodes):
        """Find the Lowest Common Ancestor of a list of xml element nodes."""
        if not nodes:
            return None
        if len(nodes) == 1:
            return nodes[0]
            
        # Build path from root for each node
        paths = []
        for node in nodes:
            path = [node] + list(node.iterancestors())
            path.reverse()
            paths.append(path)
            
        # Find the longest common prefix
        lca = None
        min_len = min(len(p) for p in paths)
        for i in range(min_len):
            current_node = paths[0][i]
            if all(p[i] == current_node for p in paths):
                lca = current_node
            else:
                break
        return lca
        
    @classmethod
    def _detect_repeating_element(cls, root, mapping):
        """
        Detect which tag in the template represents the repeating record
        using Lowest Common Ancestor (LCA) of nodes containing mapped placeholders.
        """
        mapped_placeholders = set(mapping.values())
        mapped_nodes = []
        pattern = re.compile(r'\{\{\s*([a-zA-Z0-9_]+)\s*\}\}')
        
        for elem in root.iter():
            placeholders = []
            if elem.text:
                placeholders.extend(pattern.findall(elem.text))
            for attr_val in elem.attrib.values():
                placeholders.extend(pattern.findall(attr_val))
                
            if any(pl in mapped_placeholders for pl in placeholders):
                mapped_nodes.append(elem)
                
        lca = cls._find_lca(mapped_nodes)
        if lca is None:
            return root[0]
            
        # Walk up if LCA is a simple leaf element (no children) and parent is not root
        while lca.getparent() is not None and lca.getparent() != root and len(lca) == 0:
            lca = lca.getparent()
            
        return lca

    @staticmethod
    def _resolve_dynamic_value(field_cfg, row, static_fields, entities):
        """Resolve value from either Excel column name or static configuration."""
        if not field_cfg:
            return ""
        source_type = field_cfg.get('source_type')
        val_name = field_cfg.get('value', '')
        
        if source_type == 'column':
            if val_name in row:
                val = row[val_name]
                return escape(str(val), entities) if val is not None else ""
            return ""
        elif source_type == 'static':
            return escape(str(val_name), entities) if val_name is not None else ""
        return ""

    @classmethod
    def _load_records(cls, source_type: str, filepath: str, sheet_name: str = None, source_config: dict = None) -> list[dict]:
        """Dispatches data loading depending on the source type: excel, xml_file, or xml_url."""
        if source_type == 'excel':
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"Excel file not found: {filepath}")
            df = pd.read_excel(filepath, sheet_name=sheet_name, engine='openpyxl')
            # Clean dataframe values (convert NaNs and infinities to None)
            df = df.replace([np.inf, -np.inf], None)
            df = df.replace({np.nan: None})
            
            # Convert datetime columns to string
            for col in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[col]):
                    df[col] = df[col].apply(
                        lambda val: val.strftime('%Y-%m-%d %H:%M:%S') if pd.notnull(val) else None
                    )
            return df.to_dict(orient='records')
            
        elif source_type == 'xml_file':
            from core.xml_source_reader import XMLSourceReader
            record_xpath = (source_config or {}).get('record_xpath')
            records, _ = XMLSourceReader.load_records_from_file(filepath, record_xpath)
            return records
            
        elif source_type == 'xml_url':
            from core.xml_source_reader import XMLSourceReader
            url = (source_config or {}).get('url')
            record_xpath = (source_config or {}).get('record_xpath')
            auth_config = {
                'auth_type': (source_config or {}).get('auth_type', 'none'),
                'username': (source_config or {}).get('username', ''),
                'password': (source_config or {}).get('password', ''),
                'token': (source_config or {}).get('token', ''),
                'header_name': (source_config or {}).get('header_name', 'X-API-Key'),
                'header_value': (source_config or {}).get('header_value', '')
            }
            records, _ = XMLSourceReader.load_records_from_url(url, record_xpath, auth_config)
            return records
            
        else:
            raise ValueError(f"Unknown source type: {source_type}")

    @classmethod
    def generate(cls, excel_path: str, sheet_name: str, template_path: str, mapping: dict, static_fields: dict,
                 campaign_custom_fields: list = None, awm_config: dict = None, salary_config: dict = None,
                 headers_config: dict = None, disabled_fields: list = None,
                 source_type: str = "excel", source_config: dict = None, transforms: list = None) -> str:
        """
        Generate pretty-printed XML, dynamically injecting Headers, Salary, AWM,
        and Campaign custom fields according to UI parameters. Preserves CDATA structures.
        Supports field transformations prior to Jinja compilation.
        """
        if source_type == "excel" or source_type == "xml_file":
            if not os.path.exists(excel_path):
                raise FileNotFoundError(f"Source file not found: {excel_path}")
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template file not found: {template_path}")
            
        try:
            # 1. Parse XML template structure (preserves CDATA with strip_cdata=False)
            with open(template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
                
            parser = etree.XMLParser(remove_blank_text=True, strip_cdata=False)
            root = etree.fromstring(template_content.strip().encode('utf-8'), parser=parser)
            
            # Detect repeating element in the tree
            repeating_element = cls._detect_repeating_element(root, mapping)
            parent_element = repeating_element.getparent()
            
            if parent_element is None:
                raise ValueError("Repeating record element has no parent container.")
                
            # Serialize the repeating element template
            repeating_template_str = etree.tostring(repeating_element, encoding='utf-8').decode('utf-8')
            
            # Remove repeating node from parent container in the template tree
            parent_element.remove(repeating_element)
            
            # 2. Load record data from Excel/XML/URL
            records = cls._load_records(source_type, excel_path, sheet_name, source_config)
            
            # Escape definitions for XML compatibility
            entities = {
                "\"": "&quot;",
                "'": "&apos;"
            }
            
            # 3. Dynamic Feed Headers injection at the root level (inserted at the top of the root element)
            if headers_config:
                for idx, field in enumerate(['provider', 'providerurl', 'isfullfeed', 'part', 'islast']):
                    field_cfg = headers_config.get(field, {})
                    source_type_header = field_cfg.get('source_type')
                    val_name = field_cfg.get('value', '')
                    
                    if source_type_header == 'column':
                        if records and val_name in records[0]:
                            val = records[0][val_name]
                            text = str(val) if val is not None else ""
                        else:
                            text = ""
                    else:
                        text = str(val_name) if val_name is not None else ""
                    
                    el = etree.Element(field)
                    el.text = text
                    root.insert(idx, el)
            
            # 4. Assemble repeating rows
            for row in records:
                context = {}
                
                # Add custom static fields first (raw values)
                for k, v in static_fields.items():
                    context[k] = str(v) if v is not None else ""
                    
                # Add mapped Excel/XML fields (raw values)
                for excel_col, xml_tag in mapping.items():
                    if excel_col in row:
                        val = row[excel_col]
                        context[xml_tag] = str(val) if val is not None else ""
                
                # Apply transformations
                if transforms:
                    from core.field_transforms import TransformEngine
                    context = TransformEngine.apply(context, transforms, row)
                
                # Now escape all values in context for XML safety
                for k, v in context.items():
                    context[k] = escape(v, entities)
                
                # Render repeating template block
                rendered_str = Template(repeating_template_str).render(context)
                child_node = etree.fromstring(rendered_str.strip().encode('utf-8'), parser=parser)
                
                # Omit disabled fields from the repeating node tree at any depth level
                if disabled_fields:
                    for field_name in disabled_fields:
                        for el in list(child_node.iter(field_name)):
                            parent = el.getparent()
                            if parent is not None:
                                parent.remove(el)
                
                # Dynamic Custom Fields injection inside <campaign>
                if campaign_custom_fields:
                    campaign_el = child_node.find('campaign')
                    if campaign_el is None:
                        campaign_el = etree.Element('campaign')
                        child_node.append(campaign_el)
                        
                    customfields_el = etree.Element('customfields')
                    for field_cfg in campaign_custom_fields:
                        field_name = field_cfg.get('name', '').strip()
                        if not field_name:
                            continue
                        val = cls._resolve_dynamic_value(field_cfg, row, static_fields, entities)
                        
                        customfield_el = etree.Element('customfield')
                        name_el = etree.Element('name')
                        name_el.text = field_name
                        val_el = etree.Element('value')
                        val_el.text = val
                        
                        customfield_el.append(name_el)
                        customfield_el.append(val_el)
                        customfields_el.append(customfield_el)
                    campaign_el.append(customfields_el)
                
                # Dynamic Salary block injection inside <job>
                if salary_config and salary_config.get('enabled'):
                    salary_el = etree.Element('salary')
                    for field in ['min', 'max', 'type', 'currency']:
                        field_cfg = salary_config.get('fields', {}).get(field, {})
                        val = cls._resolve_dynamic_value(field_cfg, row, static_fields, entities)
                        child = etree.Element(field)
                        child.text = val
                        salary_el.append(child)
                    child_node.append(salary_el)
                
                # Dynamic AWM block injection inside <job>
                if awm_config and awm_config.get('enabled'):
                    awm_el = etree.Element('awm')
                    for field in ['method', 'format', 'email', 'apikey']:
                        field_cfg = awm_config.get('fields', {}).get(field, {})
                        val = cls._resolve_dynamic_value(field_cfg, row, static_fields, entities)
                        child = etree.Element(field)
                        child.text = val
                        awm_el.append(child)
                    child_node.append(awm_el)
                
                parent_element.append(child_node)
                
            # 5. Serialize entire tree
            output_xml = etree.tostring(
                root,
                xml_declaration=True,
                encoding='utf-8',
                pretty_print=True
            ).decode('utf-8')
            
            # Substitute any residual outer static field placeholders if necessary
            if static_fields:
                escaped_statics = {
                    k: escape(str(v), entities) if v is not None else ""
                    for k, v in static_fields.items()
                }
                output_xml = Template(output_xml).render(escaped_statics)
            
            return output_xml
            
        except Exception as e:
            raise ValueError(f"XML Generation failed: {str(e)}")
