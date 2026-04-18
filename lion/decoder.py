"""LION format decoder."""

import re
from typing import Any, Dict, List, Tuple


class LionDecoder:
    __slots__ = ('_pos', '_text', '_len')
    
    _IDENTIFIER_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*')
    _NUMBER_PATTERN = re.compile(r'^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?')
    _DATE_PATTERN = re.compile(
        r'^\d{4}-\d{2}-\d{2}([T\s]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$'
    )
    
    def __init__(self):
        self._pos = 0
        self._text = ""
        self._len = 0
    
    def decode(self, text: str) -> Any:
        self._text = text.strip()
        self._len = len(self._text)
        self._pos = 0
        
        if not self._text:
            return None
        
        result = self._parse_value()
        self._skip_whitespace()
        
        if self._pos < self._len:
            if isinstance(result, dict):
                while self._pos < self._len:
                    self._skip_whitespace()
                    if self._pos >= self._len:
                        break
                    if self._peek() == ',':
                        self._pos += 1
                        self._skip_whitespace()
                    if self._pos >= self._len:
                        break
                    key = self._parse_key()
                    if not key:
                        break
                    self._skip_whitespace()
                    
                    if self._pos < self._len and self._peek() == '(':
                        header = self._parse_header()
                        self._skip_whitespace()
                        self._expect(':')
                        self._skip_whitespace()
                        arr = self._parse_array()
                        result[key] = self._reconstruct_from_schema(arr, header)
                    else:
                        self._expect(':')
                        self._skip_whitespace()
                        value = self._parse_value()
                        result[key] = value
        
        return result
    
    def _parse_value(self) -> Any:
        self._skip_whitespace()
        
        if self._pos >= self._len:
            return None
        
        ch = self._peek()
        
        if ch == '{':
            return self._parse_object()
        
        if ch == '[':
            return self._parse_array()
        
        if ch == '(':
            return self._parse_schematized_list()
        
        if ch == '"':
            return self._parse_string()
        
        if ch.isalpha() or ch == '_':
            return self._parse_identifier_or_named()
        
        if ch == '-' or ch.isdigit():
            return self._parse_number()
        
        raise ValueError(f"Unexpected character '{ch}' at position {self._pos}")
    
    def _parse_identifier_or_named(self) -> Any:
        start_pos = self._pos
        identifier = self._parse_identifier()
        
        if identifier == 'true':
            return True
        if identifier == 'false':
            return False
        if identifier == 'null':
            return None
        
        self._skip_whitespace()
        
        if self._pos < self._len and self._peek() == '{':
            obj = self._parse_object()
            return {identifier: obj}
        
        if self._pos < self._len and self._peek() == ':':
            self._pos += 1
            self._skip_whitespace()
            value = self._parse_value()
            return {identifier: value}
        
        if self._pos < self._len and self._peek() == '(':
            header = self._parse_header()
            self._skip_whitespace()
            if self._peek() == ':':
                self._pos += 1
                self._skip_whitespace()
            arr = self._parse_array()
            return {identifier: self._reconstruct_from_schema(arr, header)}
        
        if self._DATE_PATTERN.match(identifier):
            return identifier
        
        return identifier
    
    def _parse_object(self):
        self._expect('{')
        self._skip_whitespace()
        
        if self._pos >= self._len or self._peek() == '}':
            self._expect('}')
            return {}
        
        ch = self._peek()
        if ch == '-' or ch.isdigit():
            return self._parse_tuple_body()
        
        result = {}
        is_first = True
        
        while self._pos < self._len and self._peek() != '}':
            self._skip_whitespace()
            
            if self._peek() == '}':
                break
            
            key = self._parse_key()
            if not key:
                raise ValueError(
                    f"Expected key but got '{self._peek()}' at position {self._pos}"
                )
            self._skip_whitespace()
            
            if is_first and self._pos < self._len and self._peek() in (',', '}'):
                values = [key]
                while self._pos < self._len and self._peek() == ',':
                    self._pos += 1
                    self._skip_whitespace()
                    if self._pos >= self._len or self._peek() == '}':
                        break
                    values.append(self._parse_array_value())
                    self._skip_whitespace()
                self._expect('}')
                return values
            
            is_first = False
            
            if self._pos < self._len and self._peek() == '(':
                header = self._parse_header()
                self._skip_whitespace()
                self._expect(':')
                self._skip_whitespace()
                arr = self._parse_array()
                result[key] = self._reconstruct_from_schema(arr, header)
            else:
                self._expect(':')
                self._skip_whitespace()
                value = self._parse_value()
                result[key] = value
            
            self._skip_whitespace()
            if self._peek() == ',':
                self._pos += 1
                self._skip_whitespace()
        
        self._expect('}')
        return result
    
    def _parse_tuple_body(self) -> list:
        """Parse the body of a tuple {val1, val2, ...} after '{' has been consumed.
        Called when the first char after '{' is a non-key value (e.g. number)."""
        values = []
        values.append(self._parse_array_value())
        self._skip_whitespace()
        while self._pos < self._len and self._peek() == ',':
            self._pos += 1
            self._skip_whitespace()
            if self._pos >= self._len or self._peek() == '}':
                break
            values.append(self._parse_array_value())
            self._skip_whitespace()
        self._expect('}')
        return values
    
    def _parse_array(self) -> List[Any]:
        self._expect('[')
        self._skip_whitespace()
        
        result = []
        
        while self._pos < self._len and self._peek() != ']':
            self._skip_whitespace()
            
            if self._peek() == ']':
                break
            
            value = self._parse_array_value()
            result.append(value)
            
            self._skip_whitespace()
            if self._peek() == ',':
                self._pos += 1
                self._skip_whitespace()
        
        self._expect(']')
        return result
    
    def _parse_array_value(self) -> Any:
        self._skip_whitespace()
        
        if self._pos >= self._len:
            return None
        
        ch = self._peek()
        
        if ch == '"':
            return self._parse_string()
        
        if ch == '[':
            return self._parse_array()
        
        if ch == '{':
            return self._parse_object()
        
        if ch == '-' or ch.isdigit():
            saved_pos = self._pos
            num = self._parse_number()
            peek_pos = self._pos
            while peek_pos < self._len and self._text[peek_pos] in ' \t':
                peek_pos += 1
            if peek_pos < self._len and self._text[peek_pos] not in ',]}\n\r:':
                self._pos = saved_pos
                return self._parse_unquoted_value()
            return num
        
        return self._parse_unquoted_value()
    
    def _parse_unquoted_value(self) -> Any:
        start = self._pos
        delimiters = ',]}:'
        
        while self._pos < self._len and self._text[self._pos] not in delimiters:
            self._pos += 1
        
        value = self._text[start:self._pos].strip()
        
        if not value:
            raise ValueError(
                f"Expected value but got '{self._peek()}' at position {self._pos}"
            )
        
        if value == 'true':
            return True
        if value == 'false':
            return False
        if value == 'null':
            return None
        
        try:
            if '.' in value or 'e' in value.lower():
                return float(value)
            return int(value)
        except ValueError:
            pass
        
        return value
    
    def _parse_schematized_list(self) -> Any:
        header = self._parse_header()
        self._skip_whitespace()
        
        if self._peek() == ':':
            self._pos += 1
            self._skip_whitespace()
        
        arr = self._parse_array()
        return self._reconstruct_from_schema(arr, header)
    
    def _parse_header(self) -> List[str]:
        self._expect('(')
        self._skip_whitespace()
        
        keys = []
        
        while self._pos < self._len and self._peek() != ')':
            self._skip_whitespace()
            
            if self._peek() == ')':
                break
            
            key = self._parse_identifier()
            if not key:
                raise ValueError(
                    f"Expected identifier in header but got '{self._peek()}' at position {self._pos}"
                )
            
            if self._pos < self._len and self._peek() == '(':
                nested = self._parse_header()
                key = f"{key}({','.join(nested)})"
            
            keys.append(key)
            
            self._skip_whitespace()
            if self._peek() == ',':
                self._pos += 1
                self._skip_whitespace()
        
        self._expect(')')
        return keys
    
    def _parse_key(self) -> str:
        if self._peek() == '"':
            return self._parse_string()
        return self._parse_identifier()
    
    def _parse_identifier(self) -> str:
        start = self._pos
        
        if self._pos < self._len and (self._peek().isalpha() or self._peek() == '_'):
            self._pos += 1
        else:
            return ""
        
        while self._pos < self._len:
            ch = self._peek()
            if ch.isalnum() or ch == '_':
                self._pos += 1
            else:
                break
        
        return self._text[start:self._pos]
    
    def _parse_string(self) -> str:
        self._expect('"')
        
        result = []
        while self._pos < self._len:
            ch = self._peek()
            
            if ch == '"':
                self._pos += 1
                return ''.join(result)
            
            if ch == '\\':
                self._pos += 1
                if self._pos >= self._len:
                    raise ValueError("Unexpected end of string")
                
                escape_ch = self._peek()
                self._pos += 1
                
                if escape_ch == 'n':
                    result.append('\n')
                elif escape_ch == 't':
                    result.append('\t')
                elif escape_ch == 'r':
                    result.append('\r')
                elif escape_ch == '"':
                    result.append('"')
                elif escape_ch == '\\':
                    result.append('\\')
                else:
                    result.append(escape_ch)
            else:
                result.append(ch)
                self._pos += 1
        
        raise ValueError("Unterminated string")
    
    def _parse_number(self) -> Any:
        start = self._pos
        
        if self._peek() == '-':
            self._pos += 1
        
        if self._pos < self._len and self._peek() == '0':
            self._pos += 1
        else:
            while self._pos < self._len and self._peek().isdigit():
                self._pos += 1
        
        is_float = False
        if self._pos < self._len and self._peek() == '.':
            is_float = True
            self._pos += 1
            while self._pos < self._len and self._peek().isdigit():
                self._pos += 1
        
        if self._pos < self._len and self._peek() in 'eE':
            is_float = True
            self._pos += 1
            if self._pos < self._len and self._peek() in '+-':
                self._pos += 1
            while self._pos < self._len and self._peek().isdigit():
                self._pos += 1
        
        num_str = self._text[start:self._pos]
        
        if is_float:
            return float(num_str)
        return int(num_str)
    
    def _reconstruct_from_schema(self, arr: List[Any], header: List[str]) -> List[Dict[str, Any]]:
        result = []
        
        keys = []
        for h in header:
            if '(' in h:
                key_name = h.split('(')[0]
                keys.append(key_name)
            else:
                keys.append(h)
        
        for item in arr:
            if isinstance(item, dict) and not any(k in keys for k in item.keys()):
                if len(item) == 0:
                    obj = {k: None for k in keys}
                else:
                    values = list(item.values()) if isinstance(item, dict) else item
                    obj = {}
                    for i, key in enumerate(keys):
                        if i < len(values):
                            obj[key] = values[i]
                        else:
                            obj[key] = None
                result.append(obj)
            elif isinstance(item, dict):
                result.append(item)
            elif isinstance(item, (list, tuple)):
                obj = {}
                for i, key in enumerate(keys):
                    if i < len(item):
                        obj[key] = item[i]
                    else:
                        obj[key] = None
                result.append(obj)
            else:
                if keys:
                    result.append({keys[0]: item})
                else:
                    result.append(item)
        
        return result
    
    def _skip_whitespace(self):
        while self._pos < self._len:
            ch = self._text[self._pos]
            if ch in ' \t\n\r':
                self._pos += 1
            elif ch == '/' and self._pos + 1 < self._len and self._text[self._pos + 1] == '*':
                # Skip /* ... */ inline comments
                self._pos += 2
                while self._pos + 1 < self._len:
                    if self._text[self._pos] == '*' and self._text[self._pos + 1] == '/':
                        self._pos += 2  # skip closing */
                        break
                    self._pos += 1
                else:
                    if self._pos < self._len:
                        self._pos += 1  # skip last char if unclosed
            else:
                break
    
    def _peek(self) -> str:
        if self._pos < self._len:
            return self._text[self._pos]
        return ''
    
    def _expect(self, ch: str):
        if self._pos >= self._len:
            raise ValueError(f"Expected '{ch}' but reached end of input")
        if self._text[self._pos] != ch:
            raise ValueError(f"Expected '{ch}' but got '{self._text[self._pos]}' at position {self._pos}")
        self._pos += 1


def loads(text: str) -> Any:
    return LionDecoder().decode(text)
