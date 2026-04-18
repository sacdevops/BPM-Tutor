"""LION format encoder."""

import re
from typing import Any, Dict, List, Tuple
from datetime import datetime, date, time


class LionEncoder:
    __slots__ = ('pretty', 'indent_size', '_indent_cache')
    
    _DATE_PATTERNS = tuple(
        re.compile(pattern) for pattern in (
            r'^\d{4}-\d{2}-\d{2}([T\s]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$',
            r'^\d{4}[/.]\d{2}[/.]\d{2}([T\s]\d{2}:\d{2}(:\d{2})?)?$',
            r'^\d{1,2}:\d{2}(:\d{2})?(\.\d+)?$'
        )
    )
    
    _SPECIAL_CHARS = frozenset('{}[](),: "\\\n\t\r')
    
    _ESCAPE_TABLE = str.maketrans({
        '"': '\\"',
        '\\': '\\\\',
        '\t': '\\t',
    })

    def __init__(self, pretty: bool = True, indent_size: int = 2):
        self.pretty = pretty
        self.indent_size = indent_size
        self._indent_cache = tuple(' ' * (i * indent_size) for i in range(20))

    def encode(self, data: Any) -> str:
        if isinstance(data, dict):
            return self._encode_root_dict(data)
        elif isinstance(data, list):
            return self._encode_root_list(data)
        else:
            return self._format_primitive(data)

    def _encode_root_dict(self, data: Dict) -> str:
        if not data:
            return "{}"

        if len(data) == 1:
            key, value = next(iter(data.items()))
            if isinstance(value, dict):
                if self.pretty:
                    inner = self._encode_object_fields(value, 1)
                    return f"{key} {{\n{inner}\n}}"
                else:
                    inner = self._encode_object_fields(value, 0)
                    return f"{key}{{{inner}}}"

        if self.pretty:
            return self._encode_object_fields(data, 0)
        else:
            keys = sorted(data.keys())
            parts = [self._encode_field(k, data[k], 0) for k in keys]
            return ",".join(parts)

    def _encode_root_list(self, data: List) -> str:
        if not data:
            return "[]"

        if self.pretty and self._is_simple_list(data):
            parts = [self._format_primitive(v) for v in data]
            return f"[{','.join(parts)}]"

        first = data[0]
        if isinstance(first, dict) and self._is_uniform_list(data):
            header_parts, keys, field_schemas = self._analyze_list_schema(data)
            header_str = ",".join(header_parts)
            list_body = self._encode_schematized_list_body2(data, keys, field_schemas, 0)
            if self.pretty:
                return f"({header_str}): {list_body}"
            return f"({header_str}):{list_body}"
        else:
            return self._encode_list_standard(data, 0)

    def _encode_object(self, data: Dict, level: int) -> str:
        if not data:
            return "{}"

        if self.pretty:
            inner = self._encode_object_fields(data, level)
            brace_indent = self._get_indent(level - 1) if level > 0 else ""
            return f"{{\n{inner}\n{brace_indent}}}"
        else:
            inner = self._encode_object_fields(data, level)
            return f"{{{inner}}}"

    def _encode_object_fields(self, data: Dict, level: int) -> str:
        keys = sorted(data.keys())
        
        if self.pretty:
            indent = self._get_indent(level)
            parts = [f"{indent}{self._encode_field(k, data[k], level)}" for k in keys]
            return ",\n".join(parts)
        else:
            parts = [self._encode_field(k, data[k], level) for k in keys]
            return ",".join(parts)

    def _encode_field(self, key: str, value: Any, level: int) -> str:
        sep = ": " if self.pretty else ":"
        

        if isinstance(value, list) and value and isinstance(value[0], dict) and self._is_uniform_list(value):
            header_parts, keys, field_schemas = self._analyze_list_schema(value)
            header_str = ",".join(header_parts)
            list_body = self._encode_schematized_list_body2(value, keys, field_schemas, level)
            return f"{key}({header_str}){sep}{list_body}"

        if isinstance(value, dict):
            obj_str = self._encode_object(value, level + 1)
            return f"{key}{sep}{obj_str}"

        if isinstance(value, list):
            list_str = self._encode_list_standard(value, level)
            return f"{key}{sep}{list_str}"

        return f"{key}{sep}{self._format_primitive(value)}"

    def _analyze_list_schema(self, data: List[Dict[str, Any]]) -> Tuple[List[str], List[str], Dict[str, Dict[str, Any]]]:
        if not data:
            return [], [], {}

        sample = data[0]
        keys = sorted(sample.keys())
        field_schemas: Dict[str, Dict[str, Any]] = {}
        header_parts: List[str] = []

        for key in keys:
            schema = self._analyze_field_across_items(data, key)
            field_schemas[key] = schema
            header_parts.append(schema["header_repr"])

        return header_parts, keys, field_schemas

    def _analyze_field_across_items(self, data: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
        values = [item.get(key) for item in data]

        schema: Dict[str, Any] = {
            "kind": "plain",
            "header_repr": key,
            "sub_keys": None
        }

        if any(v is None for v in values):
            return schema

        if all(isinstance(v, dict) for v in values):
            first = values[0]
            if not first:
                return schema
            base_keys = set(first.keys())
            if base_keys and all(set(v.keys()) == base_keys for v in values):
                sub_keys_sorted = sorted(base_keys)
                schema["kind"] = "dict_with_schema"
                schema["sub_keys"] = sub_keys_sorted
                schema["header_repr"] = f"{key}({','.join(sub_keys_sorted)})"
            return schema

        if all(isinstance(v, list) for v in values):
            sample_subkeys = None
            any_non_empty = False

            for v in values:
                if not v:
                    continue
                if not isinstance(v[0], dict):
                    return schema
                if not self._is_uniform_list(v):
                    return schema

                keys_v = set(v[0].keys())
                if sample_subkeys is None:
                    sample_subkeys = keys_v
                elif keys_v != sample_subkeys:
                    return schema
                any_non_empty = True

            if any_non_empty and sample_subkeys:
                sub_keys_sorted = sorted(sample_subkeys)
                schema["kind"] = "list_of_dicts_with_schema"
                schema["sub_keys"] = sub_keys_sorted
                schema["header_repr"] = f"{key}({','.join(sub_keys_sorted)})"

            return schema

        return schema

    def _encode_schematized_list_body2(
        self,
        data: List[Dict[str, Any]],
        keys: List[str],
        field_schemas: Dict[str, Dict[str, Any]],
        level: int
    ) -> str:
        item_level = level + 1
        parts = [self._encode_schematized_row2(item, keys, field_schemas, item_level) for item in data]
        content = self._join_parts(parts, item_level)

        if self.pretty:
            indent = self._get_indent(level)
            return f"[{content}\n{indent}]"
        return f"[{content}]"

    def _encode_dict_values_as_tuple(
        self,
        value: Dict[str, Any],
        sub_keys: List[str],
        level: int
    ) -> str:
        """Encodes a Dict with a known subschema (sub_keys) as a tuple."""
        cells: List[str] = []
        complex_row = False
        nested_level = level + 1 if self.pretty else level

        for sk in sub_keys:
            v_sub = value.get(sk)
            if isinstance(v_sub, dict):
                cell = self._encode_object(v_sub, nested_level)
                complex_row = True
            elif isinstance(v_sub, list):
                cell = self._encode_list_standard(v_sub, level)
                complex_row = complex_row or "\n" in cell
            else:
                cell = self._format_primitive(v_sub)
            cells.append(cell)

        if self.pretty and complex_row:
            inner_indent = self._get_indent(nested_level)
            outer_indent = self._get_indent(level)
            content = f",\n{inner_indent}".join(cells)
            return f"{{\n{inner_indent}{content}\n{outer_indent}}}"
        else:
            return f"{{{','.join(cells)}}}"

    def _encode_schematized_row2(
        self,
        item: Dict[str, Any],
        keys: List[str],
        field_schemas: Dict[str, Dict[str, Any]],
        level: int
    ) -> str:
        """Row within a list that knows a global schema (field_schemas)."""
        cells: List[str] = []
        complex_row = False
        cell_encoding_level = level + 1 if self.pretty else level

        for k in keys:
            v = item.get(k)
            schema = field_schemas.get(k, {"kind": "plain", "sub_keys": None})

            if schema["kind"] == "list_of_dicts_with_schema" and isinstance(v, list):
                sub_keys = schema["sub_keys"]
                cell = self._encode_schematized_list_body(v, sub_keys, cell_encoding_level)
                cells.append(cell)
                complex_row = complex_row or "\n" in cell

            elif schema["kind"] == "dict_with_schema" and isinstance(v, dict):
                sub_keys = schema["sub_keys"]
                cell = self._encode_dict_values_as_tuple(v, sub_keys, cell_encoding_level)
                cells.append(cell)
                complex_row = True

            elif isinstance(v, list) and v and isinstance(v[0], dict) and self._is_uniform_list(v):
                header_parts, sub_keys, sub_schemas = self._analyze_list_schema(v)
                header = f"{k}({','.join(header_parts)})"
                body = self._encode_schematized_list_body2(v, sub_keys, sub_schemas, cell_encoding_level)
                sep = ": " if self.pretty else ":"
                cell = f"{header}{sep}{body}"
                cells.append(cell)
                complex_row = complex_row or "\n" in cell

            elif isinstance(v, dict):
                cell = self._encode_object(v, cell_encoding_level)
                cells.append(cell)
                complex_row = True

            elif isinstance(v, list):
                cell = self._encode_list_standard(v, cell_encoding_level)
                cells.append(cell)
                complex_row = complex_row or "\n" in cell

            else:
                cells.append(self._format_primitive(v))

        if self.pretty and complex_row:
            inner_indent = self._get_indent(cell_encoding_level)
            outer_indent = self._get_indent(level)
            content = f",\n{inner_indent}".join(cells)
            return f"{{\n{inner_indent}{content}\n{outer_indent}}}"
        else:
            return f"{{{','.join(cells)}}}"

    def _encode_schematized_row(self, item: Dict[str, Any], keys: List[str], level: int) -> str:
        cells: List[str] = []
        complex_row = False
        cell_encoding_level = level + 1 if self.pretty else level
        sep = ": " if self.pretty else ":"

        for k in keys:
            v = item.get(k)

            if isinstance(v, list) and v and isinstance(v[0], dict) and self._is_uniform_list(v):
                sub_keys = sorted(v[0].keys())
                header = f"{k}({','.join(sub_keys)})"
                body = self._encode_schematized_list_body(v, sub_keys, cell_encoding_level)
                cell = f"{header}{sep}{body}"
                cells.append(cell)
                complex_row = complex_row or "\n" in cell

            elif isinstance(v, dict):
                cell = self._encode_object(v, cell_encoding_level)
                cells.append(cell)
                complex_row = True

            elif isinstance(v, list):
                cell = self._encode_list_standard(v, cell_encoding_level)
                cells.append(cell)
                complex_row = complex_row or "\n" in cell

            else:
                cells.append(self._format_primitive(v))

        if self.pretty and complex_row:
            inner_indent = self._get_indent(cell_encoding_level)
            outer_indent = self._get_indent(level)
            content = f",\n{inner_indent}".join(cells)
            return f"{{\n{inner_indent}{content}\n{outer_indent}}}"
        else:
            return f"{{{','.join(cells)}}}"

    def _encode_schematized_list_body(self, data: List[Dict], keys: List[str], level: int) -> str:
        item_level = level + 1
        parts = [self._encode_schematized_row(item, keys, item_level) for item in data]
        content = self._join_parts(parts, item_level)

        if self.pretty:
            indent = self._get_indent(level)
            return f"[{content}\n{indent}]"
        return f"[{content}]"

    def _encode_list_standard(self, data: List, level: int) -> str:
        if self.pretty and self._is_simple_list(data):
            parts = [self._encode_fallback_value(v, level + 1) for v in data]
            return f"[{','.join(parts)}]"

        content_level = level + 1
        parts = [self._encode_fallback_value(v, content_level) for v in data]
        content = self._join_parts(parts, content_level)

        if self.pretty:
            indent = self._get_indent(level)
            return f"[{content}\n{indent}]"
        return f"[{content}]"

    def _encode_fallback_value(self, value: Any, level: int) -> str:
        if isinstance(value, dict):
            if self.pretty:
                return self._encode_object(value, level + 1)
            else:
                return self._encode_object(value, 0)
        elif isinstance(value, list):
            if value and isinstance(value[0], dict) and self._is_uniform_list(value):
                header_parts, keys, field_schemas = self._analyze_list_schema(value)
                header_str = ",".join(header_parts)
                list_body = self._encode_schematized_list_body2(value, keys, field_schemas, level)
                if self.pretty:
                    return f"({header_str}): {list_body}"
                else:
                    return f"({header_str}):{list_body}"
            return self._encode_list_standard(value, level)
        else:
            return self._format_primitive(value)

    def _join_parts(self, parts: List[str], level: int) -> str:
        if self.pretty:
            indent = self._get_indent(level)
            return f"\n{indent}" + f",\n{indent}".join(parts)
        return ",".join(parts)

    def _get_indent(self, level: int) -> str:
        if level < len(self._indent_cache):
            return self._indent_cache[level]
        return " " * (level * self.indent_size)

    def _is_uniform_list(self, data: List) -> bool:
        if not data:
            return True
        first = data[0]
        if not isinstance(first, dict):
            return False
        keys = first.keys()
        for item in data[1:]:
            if not isinstance(item, dict) or item.keys() != keys:
                return False
        return True

    def _is_simple_list(self, data: List) -> bool:
        return all(not isinstance(item, (dict, list)) for item in data)

    def _is_date_string(self, text: str) -> bool:
        return any(pattern.match(text) for pattern in self._DATE_PATTERNS)

    def _needs_quoting(self, s: str) -> bool:
        return bool(self._SPECIAL_CHARS.intersection(s))

    def _escape_string(self, s: str) -> str:
        return s.translate(self._ESCAPE_TABLE)

    def _format_primitive(self, value: Any) -> str:
        if isinstance(value, str):
            if not value:
                return '""'
            if value == "null":
                return '"null"'
            if self._needs_quoting(value):
                return f'"{value.translate(self._ESCAPE_TABLE)}"'
            if self._is_date_string(value):
                return value
            return value
        if value is None:
            return 'null'
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return str(value)
        if isinstance(value, (datetime, date, time)):
            return value.isoformat()
        return str(value)


def dumps(data: Any, pretty: bool = True) -> str:
    """Encode data to LION format string."""
    return LionEncoder(pretty).encode(data)
