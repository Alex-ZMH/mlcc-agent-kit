"""MLCC units engine 1.0.0, additive catalog 1.2.0. Stdlib-only JSON stdio.

Adapted deterministic parsing/finite/linear conversion principles from the
read-only fem-general UnitNormalizer; see docs/units-source.md for fingerprints.
No CaseSpec, framework/runtime, solver, provider or external repository imports.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import json
import math
import re
import sys

CORE_VERSION = '1.0.0'
# Engine/protocol/record semantics stay fixed. Version additive whitelist data
# separately so existing strict 1.0.0 consumers and historical records still work.
CATALOG_VERSION = '1.2.0'
REQUEST_VERSION = 'mlcc.units-request.v1'
RESPONSE_VERSION = 'mlcc.units-response.v1'
QUANTITY_VERSION = 'mlcc.quantity.v1'
MAX_INPUT_BYTES = 2 * 1024 * 1024


class UnitError(ValueError):
    def __init__(self, code, message, path='$'):
        super().__init__(message)
        self.code, self.path = code, path


# Only this file contains the unit/dimension/factor registry.
_DIMENSIONS = {
    'length': 'm', 'time': 's', 'electric_potential': 'V', 'electric_field': 'V/m',
    'charge_per_area': 'C/m^2', 'absolute_permittivity': 'F/m',
    'gradient_coefficient': 'J*m^3/C^2', 'energy_density': 'J/m^3',
    'energy': 'J', 'energy_per_length': 'J/m', 'charge': 'C',
    'temperature': 'K', 'temperature_delta': 'K', 'dimensionless': '1',
    'frequency': 'Hz', 'current': 'A', 'electrical_conductivity': 'S/m',
    'thermal_conductivity': 'W/(m K)', 'heat_transfer_coefficient': 'W/(m^2 K)',
    'capacitance': 'F', 'resistance': 'ohm', 'inductance': 'H',
}
_KINDS = {key: key for key in _DIMENSIONS if key not in {'charge_per_area', 'dimensionless'}}
_KINDS.update(polarization='charge_per_area', electric_displacement='charge_per_area',
              relative_permittivity='dimensionless', reduced_permittivity='dimensionless',
              dimensionless_parameter='dimensionless', algorithm_step='dimensionless',
              count='dimensionless', seed='dimensionless')
_UNITS = {}


def _register(unit, dimension, factor='1', offset='0'):
    _UNITS[unit] = (dimension, factor, offset)


for _unit, _factor in (('m','1'),('cm','1e-2'),('mm','1e-3'),('um','1e-6'),('nm','1e-9')):
    _register(_unit, 'length', _factor)
for _unit, _factor in (('s','1'),('ms','1e-3'),('us','1e-6'),('ns','1e-9'),('ps','1e-12')):
    _register(_unit, 'time', _factor)
for _unit, _factor in (('V','1'),('mV','1e-3'),('kV','1e3')):
    _register(_unit, 'electric_potential', _factor)
for _unit, _factor in (('V/m','1'),('kV/m','1e3'),('MV/m','1e6'),('V/mm','1e3'),
                       ('kV/mm','1e6'),('kV/cm','1e5'),('MV/cm','1e8'),('V/um','1e6')):
    _register(_unit, 'electric_field', _factor)
for _unit, _factor in (('C/m^2','1'),('mC/m^2','1e-3'),('uC/m^2','1e-6'),('uC/cm^2','1e-2')):
    _register(_unit, 'charge_per_area', _factor)
for _unit, _factor in (('F/m','1'),('pF/m','1e-12'),('nF/m','1e-9'),('uF/m','1e-6')):
    _register(_unit, 'absolute_permittivity', _factor)
_register('J*m^3/C^2', 'gradient_coefficient')
_register('V*m^3/C', 'gradient_coefficient')
for _unit, _factor in (('J/m^3','1'),('kJ/m^3','1e3'),('MJ/m^3','1e6'),('J/cm^3','1e6')):
    _register(_unit, 'energy_density', _factor)
for _unit, _factor in (('J','1'),('mJ','1e-3'),('uJ','1e-6'),('nJ','1e-9'),('pJ','1e-12')):
    _register(_unit, 'energy', _factor)
for _unit, _factor in (('J/m','1'),('mJ/m','1e-3'),('uJ/m','1e-6'),('nJ/m','1e-9')):
    _register(_unit, 'energy_per_length', _factor)
for _unit, _factor in (('C','1'),('mC','1e-3'),('uC','1e-6'),('nC','1e-9'),('pC','1e-12')):
    _register(_unit, 'charge', _factor)
_register('K', 'temperature')
_register('°C', 'temperature', offset='273.15')
_register('1', 'dimensionless')
for _unit, _factor in (('Hz','1'),('kHz','1e3'),('MHz','1e6'),('GHz','1e9')):
    _register(_unit, 'frequency', _factor)
for _unit, _factor in (('A','1'),('mA','1e-3'),('uA','1e-6'),('nA','1e-9')):
    _register(_unit, 'current', _factor)
for _unit, _factor in (('S/m','1'),('S/cm','1e2'),('mS/m','1e-3'),('uS/m','1e-6'),
                       ('nS/m','1e-9'),('kS/m','1e3'),('MS/m','1e6'),
                       ('mS/cm','1e-1'),('uS/cm','1e-4')):
    _register(_unit, 'electrical_conductivity', _factor)
for _unit, _factor in (('W/(m K)','1'),('mW/(m K)','1e-3'),('kW/(m K)','1e3'),
                       ('W/(cm K)','1e2'),('W/(mm K)','1e3')):
    _register(_unit, 'thermal_conductivity', _factor)
for _unit, _factor in (('W/(m^2 K)','1'),('mW/(m^2 K)','1e-3'),('kW/(m^2 K)','1e3'),
                       ('W/(cm^2 K)','1e4'),('W/(mm^2 K)','1e6')):
    _register(_unit, 'heat_transfer_coefficient', _factor)
for _unit, _factor in (('F','1'),('mF','1e-3'),('uF','1e-6'),('nF','1e-9'),('pF','1e-12')):
    _register(_unit, 'capacitance', _factor)
for _unit, _factor in (('ohm','1'),('mohm','1e-3'),('kohm','1e3'),('Mohm','1e6')):
    _register(_unit, 'resistance', _factor)
for _unit, _factor in (('H','1'),('mH','1e-3'),('uH','1e-6'),('nH','1e-9'),('pH','1e-12')):
    _register(_unit, 'inductance', _factor)
_ALIASES = {'J m^3/C^2': 'J*m^3/C^2', 'V m^3/C': 'V*m^3/C',
            'Ω': 'ohm', 'mΩ': 'mohm', 'kΩ': 'kohm', 'MΩ': 'Mohm'}
for _unit in _UNITS:
    if ' K)' in _unit:
        _ALIASES[_unit.replace(' K)', '*K)')] = _unit
    if '^2' in _unit or '^3' in _unit:
        _compact = _unit.replace('^2','2').replace('^3','3')
        _ALIASES[_compact] = _unit
        if ' K)' in _unit:
            _ALIASES[_compact.replace(' K)', '*K)')] = _unit
_NUMBER = re.compile(r'^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(.*?)\s*$')


def _keys(value, required, optional=(), path='$'):
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise UnitError('INVALID_CONTAINER', 'Expected a JSON object with string keys', path)
    missing, extra = set(required) - value.keys(), value.keys() - set(required) - set(optional)
    if missing or extra:
        raise UnitError('INVALID_CONTAINER', f'Missing fields {sorted(missing)}; unknown fields {sorted(extra)}', path)


def _json_copy(value):
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise UnitError('NONFINITE_OR_INVALID_JSON', 'Value must be finite, JSON-serializable data') from exc
    return deepcopy(value)


def _unit_key(unit):
    if not isinstance(unit, str) or not unit.strip():
        raise UnitError('UNIT_REQUIRED', 'A nonempty explicit unit is required')
    # Typography only. No general expression evaluation or inferred SI prefixes.
    key = unit.strip().replace('µ','u').replace('μ','u').replace('²','^2').replace('³','^3').replace('·','*').replace('⋅','*')
    key = re.sub(r'\s*([/*^])\s*', r'\1', re.sub(r'\s+', ' ', key))
    key = _ALIASES.get(key, key)
    if key not in _UNITS:
        raise UnitError('UNKNOWN_UNIT', f'Unit is not in the finite whitelist: {unit!r}')
    return key


def _finite_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise UnitError('INVALID_VALUE', 'Quantity value must be a scalar finite number')
    try:
        decimal = Decimal(str(value))
        numeric = float(decimal)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise UnitError('NONFINITE_VALUE', 'Quantity must be a finite representable number') from exc
    if not decimal.is_finite() or not math.isfinite(numeric):
        raise UnitError('NONFINITE_VALUE', 'Quantity must be finite')
    if decimal != 0 and numeric == 0:
        raise UnitError('UNIT_UNDERFLOW', 'Nonzero quantity is below the supported float range')
    return decimal, numeric


def _same(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x,y) for x,y in zip(a,b))
    if type(a) in (int, float) and type(b) in (int, float):
        return a == b
    return type(a) is type(b) and a == b


def _source(value):
    if value is None:
        return {'kind': 'unspecified'}
    if not isinstance(value, dict) or not value or any(not isinstance(k,str) for k in value):
        raise UnitError('INVALID_SOURCE', 'source must be a nonempty JSON object; caller owns its scientific meaning')
    return _json_copy(value)


def _repeat(record, kind, bare_unit, source):
    _keys(record, ('schema_version','kind','dimension','original','normalized','conversion'))
    if record['kind'] != kind:
        raise UnitError('QUANTITY_KIND_MISMATCH', 'A normalized record cannot change semantic kind')
    original = record['original']
    _keys(original, ('representation','value','unit','source','bare_unit'))
    if bare_unit is not None and (original['bare_unit'] is None or _unit_key(bare_unit) != _unit_key(original['bare_unit'])):
        raise UnitError('CONFLICTING_UNIT_CONTEXT', 'Repeat must not reinterpret the original unit context')
    if source is not None and not _same(_source(source), original['source']):
        raise UnitError('SOURCE_CONFLICT', 'Repeat cannot overwrite original source')
    if isinstance(original['representation'], dict) and 'schema_version' in original['representation']:
        raise UnitError('INVALID_NORMALIZATION_RECORD', 'Nested normalization records are not valid original inputs')
    expected = normalize_quantity(original['representation'], kind=kind,
                                  bare_unit=original['bare_unit'], source=original['source'])
    if not _same(expected, record):
        raise UnitError('INVALID_NORMALIZATION_RECORD', 'Normalized record does not match recomputed original quantity/rule')
    return _json_copy(record)


def normalize_quantity(quantity, *, kind, bare_unit=None, source=None):
    """Return a verified audit record; never infer a field kind or global unit system."""
    if not isinstance(kind, str) or kind not in _KINDS:
        raise UnitError('UNKNOWN_QUANTITY_KIND', f'Unknown quantity kind: {kind!r}')
    _json_copy(quantity)
    if isinstance(quantity, dict) and quantity.get('schema_version') == QUANTITY_VERSION:
        return _repeat(quantity, kind, bare_unit, source)
    dimension = _KINDS[kind]
    canonical_unit = _DIMENSIONS[dimension]
    raw, explicit_unit, container_source = quantity, None, None
    if kind in {'count','seed'}:
        if type(quantity) is not int or quantity < 0 or bare_unit is not None:
            raise UnitError('INVALID_INTEGER_COUNT', 'count/seed require a bare nonnegative integer, with no unit context')
    elif isinstance(quantity, dict):
        _keys(quantity, ('value','unit'), ('source',))
        if 'source' in quantity and quantity['source'] is None:
            raise UnitError('INVALID_SOURCE', 'Explicit source cannot be null')
        raw, explicit_unit, container_source = quantity['value'], quantity['unit'], quantity.get('source')
        explicit_unit = _unit_key(explicit_unit)
    if container_source is not None and source is not None and not _same(_source(container_source), _source(source)):
        raise UnitError('SOURCE_CONFLICT', 'Container and caller sources disagree')
    provenance = _source(container_source if container_source is not None else source)
    if bare_unit is not None:
        _unit_key(bare_unit)
    embedded_unit = None
    if isinstance(raw, str):
        match = _NUMBER.fullmatch(raw)
        if not match:
            raise UnitError('INVALID_QUANTITY_TEXT', 'Expected exactly one number and one explicit whitelist unit')
        number_text, suffix = match.groups()
        if suffix:
            embedded_unit = _unit_key(suffix)
        raw_decimal, raw_number = _finite_decimal(number_text)
    else:
        raw_decimal, raw_number = _finite_decimal(raw)
    if embedded_unit is not None and explicit_unit is not None and embedded_unit != explicit_unit:
        raise UnitError('CONFLICTING_EXPLICIT_UNITS', 'Embedded and container units disagree, including for zero')
    chosen = embedded_unit or explicit_unit
    unit_origin = 'explicit'
    if chosen is None:
        if bare_unit is not None:
            chosen, unit_origin = _unit_key(bare_unit), 'declared_field_context'
        elif dimension == 'dimensionless':
            chosen, unit_origin = '1', 'declared_semantic_kind'
        else:
            raise UnitError('UNIT_REQUIRED', 'Dimensional bare values require an explicit per-field bare_unit')
    actual_dimension, factor, offset = _UNITS[chosen]
    if dimension == 'temperature_delta' and actual_dimension == 'temperature':
        actual_dimension, offset = 'temperature_delta', '0'
    if actual_dimension != dimension:
        raise UnitError('INVALID_UNIT_DIMENSION', f'Expected {kind} ({dimension}), got {chosen} ({actual_dimension})')
    try:
        with localcontext() as context:
            context.prec = 40
            exact = raw_decimal * Decimal(factor) + Decimal(offset)
        normalized = float(exact)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise UnitError('NONFINITE_CONVERSION', 'Unit conversion cannot be represented finitely') from exc
    if not math.isfinite(normalized):
        raise UnitError('NONFINITE_CONVERSION', 'Converted quantity is not finite')
    if exact != 0 and normalized == 0:
        raise UnitError('UNIT_UNDERFLOW', 'Nonzero converted quantity underflowed to zero')
    if kind in {'count','seed'}:
        normalized, raw_number = quantity, quantity
    return {'schema_version': QUANTITY_VERSION, 'kind': kind, 'dimension': dimension,
            'original': {'representation': _json_copy(quantity), 'value': raw_number,
                         'unit': (quantity['unit'] if isinstance(quantity,dict) else
                                  match.group(2) if isinstance(raw,str) and embedded_unit is not None else None),
                         'source': provenance, 'bare_unit': bare_unit},
            'normalized': {'value': normalized, 'unit': canonical_unit},
            'conversion': {'core_version': CORE_VERSION, 'unit_key': chosen, 'factor': float(factor),
                           'offset': float(offset), 'rule': f'SI = raw * {factor} + {offset}',
                           'unit_origin': unit_origin,
                           'status': 'identity' if Decimal(factor) == 1 and Decimal(offset) == 0 else 'converted'}}


def _pointer(path):
    if not isinstance(path, str) or not path.startswith('/') or path == '/' or re.search(r'~(?![01])', path):
        raise UnitError('INVALID_FIELD_PATH', 'Expected a non-root JSON Pointer without wildcards')
    parts = [p.replace('~1','/').replace('~0','~') for p in path[1:].split('/')]
    if any(p in {'','*'} for p in parts):
        raise UnitError('INVALID_FIELD_PATH', 'Empty tokens and wildcards are unsupported', path)
    return parts


def _field(container, token, path):
    if isinstance(container, list):
        # Reject oversized indices before int(): Python's digit limit must not
        # turn a malformed JSON Pointer into an unstructured process exception.
        if (not re.fullmatch(r'0|[1-9][0-9]*', token)
                or len(token) > len(str(len(container))) or int(token) >= len(container)):
            raise UnitError('MISSING_QUANTITY_FIELD', 'Invalid or missing list index', path)
        return int(token)
    if not isinstance(container, dict) or token not in container:
        raise UnitError('MISSING_QUANTITY_FIELD', 'Declared quantity field is missing', path)
    return token


def normalize_fields(payload, fields):
    """Explicit paths only; all-or-nothing copy, with the raw payload kept separately."""
    if not isinstance(payload, dict) or not isinstance(fields, dict):
        raise UnitError('INVALID_CONTAINER', 'payload and fields must be objects')
    normalized_payload, records, parsed = _json_copy(payload), {}, {}
    for path, spec in fields.items():
        parts = _pointer(path)
        for previous in parsed.values():
            if parts[:len(previous)] == previous or previous[:len(parts)] == parts:
                raise UnitError('OVERLAPPING_FIELD_PATHS', 'Quantity field paths must not overlap', path)
        parsed[path] = parts
        try:
            _keys(spec, ('kind',), ('bare_unit','source'), path)
            parent = normalized_payload
            for token in parts[:-1]:
                parent = parent[_field(parent, token, path)]
            token = _field(parent, parts[-1], path)
            record = normalize_quantity(parent[token], **spec)
            parent[token] = record['normalized']['value']
            records[path] = record
        except UnitError as exc:
            exc.path = path
            raise
    return {'payload': normalized_payload, 'records': records, 'core_version': CORE_VERSION}


def catalog():
    return {'catalog_version': CATALOG_VERSION,
            'kinds': {kind: {'dimension': dim, 'canonical_unit': _DIMENSIONS[dim]} for kind,dim in _KINDS.items()},
            'units': {unit: {'dimension': dim, 'factor': float(factor), 'offset': float(offset)}
                      for unit,(dim,factor,offset) in _UNITS.items()},
            'typography': ['micro signs µ/μ normalize to u', '²/³ normalize to ^2/^3', 'middle dot normalizes to *'],
            'aliases': deepcopy(_ALIASES), 'expression_evaluation': False}


def dispatch(request):
    action = request.get('action') if isinstance(request,dict) else None
    try:
        if action == 'normalize':
            _keys(request, ('schema_version','action','kind','quantity'), ('bare_unit','source'))
        elif action == 'normalize_fields':
            _keys(request, ('schema_version','action','payload','fields'))
        elif action == 'catalog':
            _keys(request, ('schema_version','action'))
        else:
            raise UnitError('UNKNOWN_UNITS_ACTION', 'Supported actions: catalog, normalize, normalize_fields')
        if request['schema_version'] != REQUEST_VERSION:
            raise UnitError('UNSUPPORTED_UNITS_PROTOCOL', f'Expected {REQUEST_VERSION}')
        if action == 'normalize':
            result = normalize_quantity(request['quantity'], kind=request['kind'],
                                        bare_unit=request.get('bare_unit'), source=request.get('source'))
        elif action == 'normalize_fields':
            result = normalize_fields(request['payload'], request['fields'])
        else:
            result = catalog()
        return {'schema_version': RESPONSE_VERSION, 'core_version': CORE_VERSION, 'ok': True, 'result': result, 'errors': []}
    except UnitError as exc:
        return {'schema_version': RESPONSE_VERSION, 'core_version': CORE_VERSION, 'ok': False,
                'result': None, 'errors': [{'code': exc.code, 'message': str(exc), 'path': exc.path}]}


def _pairs(items):
    result = {}
    for key,value in items:
        if key in result:
            raise UnitError('INVALID_JSON', f'Duplicate object key: {key}')
        result[key] = value
    return result


def _constant(value):
    raise UnitError('NONFINITE_VALUE', f'JSON constant {value} is not finite')


def loads_request(raw):
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        _json_copy(value)
        return value
    except (json.JSONDecodeError, UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, UnitError):
            raise
        raise UnitError('INVALID_JSON', str(exc)) from exc


def process_json(raw):
    """Same strict wire decoder used by the standalone script and common CLI."""
    try:
        if not isinstance(raw, (bytes,str)):
            raise UnitError('INVALID_JSON', 'Expected UTF-8 bytes or JSON text')
        if len(raw if isinstance(raw,bytes) else raw.encode('utf-8')) > MAX_INPUT_BYTES:
            raise UnitError('UNITS_INPUT_LIMIT', 'Unit request exceeds 2 MiB')
        if isinstance(raw,bytes):
            raw = raw.decode('utf-8-sig')
        return dispatch(loads_request(raw))
    except (UnitError, UnicodeError) as exc:
        return {'schema_version': RESPONSE_VERSION, 'core_version': CORE_VERSION, 'ok': False,
                'result': None, 'errors': [{'code': getattr(exc,'code','INVALID_JSON'),
                                           'message': str(exc), 'path': getattr(exc,'path','$')}]}


def main(argv=None):
    # No file/system commands in the protocol. stdin only; the common CLI may read a chosen input file.
    if argv or len(sys.argv) > 1 and argv is None:
        response = {'schema_version': RESPONSE_VERSION, 'core_version': CORE_VERSION, 'ok': False,
                    'result': None, 'errors': [{'code': 'INVALID_ARGUMENT',
                    'message': 'Standalone core takes no arguments; supply JSON on stdin', 'path': '$'}]}
    else:
        response = process_json(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1))
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(response,ensure_ascii=False,allow_nan=False))
    return 0 if response['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
