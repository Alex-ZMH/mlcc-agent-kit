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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation: no silent reuse of a previous task's evidence.
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(dumps(value) + '\n')


def digest(value):
    return hashlib.sha256(dumps(value).encode('utf-8')).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


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
