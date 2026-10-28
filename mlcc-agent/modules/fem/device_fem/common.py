"""Small, standard-library contracts shared by Windows and the scientific entry."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


class ModuleError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def loads(text):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ModuleError('INVALID_JSON', f'Duplicate JSON key: {key}')
            value[key] = item
        return value

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ModuleError('INVALID_JSON', 'Non-finite JSON number')
        return result

    def constant(value):
        raise ModuleError('INVALID_JSON', f'Invalid JSON constant: {value}')

    return json.loads(text, object_pairs_hook=pairs, parse_float=finite_float,
                      parse_constant=constant)


def read_json(path):
    return loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    serialized = dumps(value) + '\n'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation: no silent reuse of a previous task's evidence.
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(serialized)


def digest(value):
    return hashlib.sha256(dumps(value).encode('utf-8')).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def validate_shape(value, schema, path='input'):
    """Validate the module's fixed, inline schemas, independently of mlcc imports."""
    if 'type' in schema:
        kind = schema['type']
        if isinstance(kind,list):
            for option in kind:
                try:
                    validate_shape(value,{'type':option},path)
                    break
                except ModuleError:
                    pass
            else:
                raise ModuleError('INVALID_INPUT',f'{path}: expected one of {kind}')
            rest=dict(schema); rest.pop('type')
            return validate_shape(value,rest,path)
        if kind=='null':
            if value is not None: raise ModuleError('INVALID_INPUT',f'{path}: expected null')
            return
        types = {'object': dict, 'array': list, 'string': str, 'boolean': bool,
                 'integer': int, 'number': (int, float)}
        valid = isinstance(value, types[kind])
        if kind in ('integer', 'number'):
            valid = valid and not isinstance(value, bool)
            try:
                valid = valid and math.isfinite(value)
            except OverflowError:
                valid = False
        if not valid:
            raise ModuleError('INVALID_INPUT', f'{path}: expected finite {kind}')
    if 'const' in schema and (value != schema['const'] or
                              isinstance(schema['const'], bool) and type(value) is not bool):
        raise ModuleError('INVALID_INPUT', f'{path}: expected {schema["const"]!r}')
    if 'enum' in schema and value not in schema['enum']:
        raise ModuleError('INVALID_INPUT', f'{path}: unsupported value')
    if isinstance(value, dict):
        required = set(schema.get('required', []))
        if required - value.keys():
            raise ModuleError('INVALID_INPUT', f'{path}: missing {sorted(required - value.keys())}')
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False and value.keys() - props.keys():
            raise ModuleError('INVALID_INPUT', f'{path}: unknown {sorted(value.keys() - props.keys())}')
        for key, item in value.items():
            if key in props:
                validate_shape(item, props[key], path + '.' + key)
    elif isinstance(value, list):
        if len(value)>schema.get('maxItems',float('inf')):
            raise ModuleError('INVALID_INPUT',path+': too many items')
        if len(value) < schema.get('minItems', 0):
            raise ModuleError('INVALID_INPUT', path + ': too few items')
        for index, item in enumerate(value):
            validate_shape(item, schema.get('items', {}), f'{path}[{index}]')
    elif isinstance(value, str):
        import re
        if len(value) < schema.get('minLength', 0):
            raise ModuleError('INVALID_INPUT', path + ': empty string')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            raise ModuleError('INVALID_INPUT', path + ': invalid string')
    if type(value) in (int, float):
        if value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf):
            raise ModuleError('INVALID_INPUT', path + ': out of supported bounds')


def artifact_path(root, reference):
    """Reject traversal, Windows separators, links, and missing/empty artifacts."""
    if not isinstance(reference, str) or '\\' in reference or ':' in reference:
        raise ModuleError('INVALID_SCIENTIFIC_RESULT', 'Invalid artifact reference')
    parts = PurePosixPath(reference).parts
    if reference != PurePosixPath(reference).as_posix() or len(parts) < 2 or parts[0] != 'artifacts' or any(p in ('.', '..') for p in parts):
        raise ModuleError('INVALID_SCIENTIFIC_RESULT', 'Artifact is outside artifacts/')
    root = Path(root).resolve()
    path = root
    for part in parts[1:]:
        path = path / part
        if path.is_symlink():
            raise ModuleError('INVALID_SCIENTIFIC_RESULT', 'Symlink artifact rejected')
    if not path.resolve().is_relative_to(root) or not path.is_file() or path.stat().st_size <= 0:
        raise ModuleError('INVALID_SCIENTIFIC_RESULT', 'Missing, empty or escaped artifact')
    return path
