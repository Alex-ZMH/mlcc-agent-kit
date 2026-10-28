"""Module-owned stdlib wire and fixed-schema validation, no Main imports."""
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


class ModuleError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require(condition, message, code='INVALID_INPUT'):
    if not condition:
        raise ModuleError(code, message)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def loads(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'Duplicate JSON key: ' + k, 'INVALID_JSON')
            result[k] = v
        return result

    def number(v):
        f = float(v)
        require(math.isfinite(f), 'Nonfinite JSON number', 'INVALID_JSON')
        # Reject nonzero decimal literals which underflow before unit handling.
        from decimal import Decimal
        require(f != 0 or Decimal(v) == 0, 'Nonzero JSON underflow', 'INVALID_JSON')
        return f

    def constant(v):
        raise ModuleError('INVALID_JSON', 'Invalid constant: ' + v)

    return json.loads(raw, object_pairs_hook=pairs, parse_float=number, parse_constant=constant)


def read_json(path):
    return loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as f:
        f.write(dumps(data) + '\n')


def digest(data):
    return hashlib.sha256(dumps(data).encode()).hexdigest()


def file_hash(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def validate(value, schema, path='$'):
    """Subset used by the module's inline schemas; no arbitrary external schema."""
    types = schema.get('type', [])
    types = [types] if isinstance(types, str) else types
    matches = {'object': isinstance(value, dict), 'array': isinstance(value, list),
               'string': isinstance(value, str), 'boolean': type(value) is bool,
               'null': value is None, 'integer': type(value) is int,
               'number': type(value) in (int, float)}
    require(not types or any(matches[t] for t in types), path + ': incorrect type')
    if type(value) in (int, float):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        require(finite, path + ': nonfinite number')
        require(schema.get('minimum', -math.inf) <= value <= schema.get('maximum', math.inf), path + ': bounds')
    if 'const' in schema:
        require(type(value) is type(schema['const']) and value == schema['const'], path + ': constant')
    if 'enum' in schema:
        require(any(type(value) is type(v) and value == v for v in schema['enum']), path + ': enum')
    if isinstance(value, dict):
        props = schema.get('properties', {})
        require(set(schema.get('required', [])) <= value.keys(), path + ': missing fields')
        require(schema.get('additionalProperties') is not False or value.keys() <= props.keys(), path + ': unknown fields')
        for k, v in value.items():
            child = props.get(k, schema.get('additionalProperties', {}))
            if isinstance(child, dict):
                validate(v, child, path + '/' + k)
    if isinstance(value, list):
        require(schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', math.inf), path + ': array bounds')
        for i, v in enumerate(value):
            validate(v, schema.get('items', {}), path + '/' + str(i))
    if isinstance(value, str):
        require(schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', math.inf), path + ': text bounds')
        require('pattern' not in schema or re.search(schema['pattern'], value), path + ': unsafe text')


def artifacts(out):
    media = {'.json': 'application/json', '.csv': 'text/csv', '.png': 'image/png', '.txt': 'text/plain', '.log': 'text/plain', '.cir': 'text/plain'}
    rows = []
    if out is None:
        return rows
    for p in sorted(Path(out).rglob('*')):
        rel = p.relative_to(out)
        if p.is_file() and not p.is_symlink() and not any(x in rel.parts for x in ('__pycache__', '.cache')):
            rows.append({'path': 'artifacts/' + rel.as_posix(), 'media_type': media.get(p.suffix, 'application/octet-stream'), 'description': 'SPICE task evidence; failure artifacts are diagnostic only'})
    return rows
