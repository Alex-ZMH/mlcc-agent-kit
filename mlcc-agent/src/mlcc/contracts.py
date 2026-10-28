"""Strict JSON and an intentionally small, fail-closed JSON Schema profile."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re


class FrameworkError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise FrameworkError("INVALID_JSON", f"Duplicate key: {key}")
        out[key] = value
    return out


def _constant(value):
    raise FrameworkError("INVALID_JSON", f"Non-finite JSON number: {value}")


def loads(raw: str):
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        # Also rejects exponent overflow (e.g. 1e999), including nested values.
        json.dumps(value, allow_nan=False)
        return value
    except (ValueError, TypeError) as exc:
        if isinstance(exc, FrameworkError):
            raise
        raise FrameworkError("INVALID_JSON", str(exc)) from exc


def read_json(path: Path):
    try:
        return loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise FrameworkError("FILE_ERROR", str(exc)) from exc


def dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def confined(root: Path, relative: str, *, must_exist=True) -> Path:
    """Reject absolute paths, traversal, links and Windows reparse points."""
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise FrameworkError("UNSAFE_PATH", f"Expected a relative POSIX path: {relative!r}")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts) or Path(relative).is_absolute():
        raise FrameworkError("UNSAFE_PATH", f"Invalid path: {relative}")
    current = root.resolve()
    for part in parts:
        current /= part
        if current.is_symlink() or (current.exists() and getattr(current, "is_junction", lambda: False)()):
            raise FrameworkError("UNSAFE_PATH", f"Link or junction rejected: {relative}")
        if current.exists() and getattr(current.stat(), "st_file_attributes", 0) & 0x400:
            raise FrameworkError("UNSAFE_PATH", f"Reparse point rejected: {relative}")
    if not current.resolve().is_relative_to(root.resolve()):
        raise FrameworkError("UNSAFE_PATH", f"Path escapes root: {relative}")
    if must_exist and not current.is_file():
        raise FrameworkError("FILE_ERROR", f"Missing regular file: {relative}")
    return current


KEYWORDS = {"$schema", "$id", "title", "description", "type", "properties", "required",
            "additionalProperties", "items", "enum", "const", "minimum", "maximum",
            "minLength", "maxLength", "pattern", "minItems", "maxItems"}
TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}


def check_schema(schema):
    if not isinstance(schema, dict):
        raise FrameworkError("INVALID_SCHEMA", "Schema must be an object")
    if set(schema) - KEYWORDS:
        raise FrameworkError("UNSUPPORTED_SCHEMA", f"Unsupported keywords: {sorted(set(schema) - KEYWORDS)}")
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    if not isinstance(types, list) or ('type' in schema and not types) or any(not isinstance(t, str) or t not in TYPES for t in types):
        raise FrameworkError("INVALID_SCHEMA", "Invalid type declaration")
    if "required" in schema and (not isinstance(schema["required"], list) or
                                any(not isinstance(k, str) for k in schema["required"])):
        raise FrameworkError("INVALID_SCHEMA", "required must be a list of strings")
    if "properties" in schema:
        if not isinstance(schema["properties"], dict):
            raise FrameworkError("INVALID_SCHEMA", "properties must be an object")
        for child in schema["properties"].values():
            check_schema(child)
    if "items" in schema:
        check_schema(schema["items"])
    if "additionalProperties" in schema:
        additional = schema["additionalProperties"]
        if not isinstance(additional, bool):
            check_schema(additional)
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        raise FrameworkError("INVALID_SCHEMA", "enum must be a nonempty list")
    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except (re.error, TypeError) as exc:
            raise FrameworkError("INVALID_SCHEMA", str(exc)) from exc
    for key in ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"):
        if key in schema:
            number = schema[key]
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise FrameworkError("INVALID_SCHEMA", f"{key} must be finite numeric")
            if key not in {"minimum", "maximum"} and (not isinstance(number, int) or number < 0):
                raise FrameworkError("INVALID_SCHEMA", f"{key} must be a nonnegative integer")


def _equal(a, b):
    # JSON booleans must not compare equal to numbers.
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[key], b[key]) for key in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return (type(a) is type(b) and a == b) or (type(a) in (int, float) and type(b) in (int, float) and a == b)


def validate(value, schema, path="$"):
    check_schema(schema)
    kinds = {"object": isinstance(value, dict), "array": isinstance(value, list),
             "string": isinstance(value, str), "boolean": type(value) is bool,
             "number": type(value) in (int, float) and math.isfinite(value),
             "integer": type(value) in (int, float) and math.isfinite(value) and int(value) == value,
             "null": value is None}
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types

    def fail(message):
        raise FrameworkError("CONTRACT_ERROR", f"{path}: {message}")

    if types and not any(kinds[t] for t in types):
        fail(f"expected {types}")
    if "enum" in schema and not any(_equal(value, candidate) for candidate in schema["enum"]):
        fail("value outside enum")
    if "const" in schema and not _equal(value, schema["const"]):
        fail("incorrect constant")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                fail(f"missing {key}")
        properties = schema.get("properties", {})
        for key, child in value.items():
            if key in properties:
                validate(child, properties[key], f"{path}.{key}")
            elif schema.get("additionalProperties", True) is False:
                fail(f"unexpected property {key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate(child, schema["additionalProperties"], f"{path}.{key}")
    if isinstance(value, list):
        for key, op in (("minItems", lambda n: len(value) < n), ("maxItems", lambda n: len(value) > n)):
            if key in schema and op(schema[key]):
                fail(key)
        if "items" in schema:
            for i, item in enumerate(value):
                validate(item, schema["items"], f"{path}[{i}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", math.inf):
            fail("string length outside bounds")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            fail("pattern mismatch")
    if type(value) in (float, int):
        if not math.isfinite(value) or value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            fail("number outside finite bounds")
