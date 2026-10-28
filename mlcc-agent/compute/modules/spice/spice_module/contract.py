"""One deterministic input path for preflight and execution."""
from copy import deepcopy
import math
import subprocess
import sys
from .common import ROOT, ModuleError, require, read_json, loads, dumps, validate

KINDS = {'capacitance_F': ('capacitance', 'F'), 'esr_ohm': ('resistance', 'ohm'),
         'esl_H': ('inductance', 'H'), 'leakage_resistance_ohm': ('resistance', 'ohm'),
         'fmin_Hz': ('frequency', 'Hz'), 'fmax_Hz': ('frequency', 'Hz'),
         'supply_V': ('electric_potential', 'V'), 'source_resistance_ohm': ('resistance', 'ohm'),
         'line_inductance_H': ('inductance', 'H'), 'baseline_A': ('current', 'A'), 'step_A': ('current', 'A'),
         **{k: ('time', 's') for k in ('delay_s', 'rise_s', 'hold_s', 'fall_s', 'stop_s', 'maxstep_s')},
         'points_per_decade': ('count', '1')}
OPERATIONS = ('ac_impedance_si', 'transient_si', 'ac_impedance', 'transient')


def rpc(request):
    core = ROOT.parents[1] / 'mlcc/units.py'
    try:
        p = subprocess.run([sys.executable, '-I', str(core)], input=dumps({'schema_version': 'mlcc.units-request.v1', **request}),
                           capture_output=True, text=True, encoding='utf-8', timeout=2, shell=False)
        require(len(p.stdout) < 2*1024*1024, 'Oversized UNIT response', 'UNITS_PROTOCOL')
        x = loads(p.stdout)
        require(x.get('schema_version') == 'mlcc.units-response.v1' and x.get('core_version') == '1.0.0', 'UNIT engine/protocol mismatch', 'UNITS_PROTOCOL')
        require(p.returncode == 0 and x.get('ok') is True and isinstance(x.get('result'), dict), str(x.get('errors')), 'UNITS_REJECTED')
        return x['result']
    except ModuleError:
        raise
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        raise ModuleError('UNITS_UNAVAILABLE', str(e)) from e


def fields(payload, operation):
    result = {}
    def add(prefix, container):
        for key, value in container.items():
            if key in KINDS and value is not None:
                result[prefix + '/' + key] = {'kind': KINDS[key][0]}
    if operation.startswith('ac_'):
        for i, m in enumerate(payload['models']):
            add('/models/' + str(i), m)
        add('', payload)
    else:
        if payload['model'] is not None:
            add('/model', payload['model'])
        add('/circuit', payload['circuit'])
        add('', payload)
    return result


def validate_si(c, operation):
    from .model import MLCC
    models = c['models'] if operation.startswith('ac_') else ([c['model']] if c['model'] else [])
    names = {}
    for raw in models:
        m = MLCC.from_dict(raw)
        key = m.model_name.lower()
        require(key not in names or names[key] == raw, 'Conflicting case-insensitive model identifiers')
        names[key] = raw
    if operation.startswith('ac_'):
        lo, hi, count = c['fmin_Hz'], c['fmax_Hz'], c['points_per_decade']
        require(0 < lo <= hi and type(count) is int and 1 <= count <= 1600, 'Positive frequency / integer sampling required')
        require((c['single_frequency'] and lo == hi and count == 1) or (not c['single_frequency'] and lo < hi), 'Single-frequency and sweep relations invalid')
        # ngspice DEC count includes endpoints only when their log ratio aligns.
        # Reject rather than silently dropping the requested last frequency.
        n = count * math.log10(hi / lo)
        require(c['single_frequency'] or abs(n-round(n)) < 1e-7, 'DEC endpoints must align to explicit points_per_decade grid')
        return math.ceil(n) + 1
    cfg = c['circuit']; h = c['maxstep_s']
    require(cfg['source_resistance_ohm'] > 0 and cfg['rise_s'] > 0 and cfg['fall_s'] > 0 and h > 0, 'Positive finite source R, edges, maxstep required')
    end = sum(cfg[k] for k in ('delay_s', 'rise_s', 'hold_s', 'fall_s'))
    require(0 < cfg['delay_s'] and 0 < cfg['hold_s'] and math.isfinite(end) and end < cfg['stop_s'] and h <= cfg['stop_s'], 'Full delayed pulse and recovery required')
    require(math.isfinite(cfg['baseline_A'] + cfg['step_A']), 'Load overflow')
    require(cfg['delay_s'] + cfg['rise_s'] + 1e-7 <= cfg['stop_s'], '100 ns post-edge diagnostic must lie in timeline')
    return math.ceil(cfg['stop_s'] / h) + 1


def canonicalize(payload, operation):
    require(operation in OPERATIONS, 'Unknown operation', 'UNSUPPORTED_OPERATION')
    validate(payload, read_json(ROOT / ('schemas/' + operation + '.input.schema.json')))
    original = deepcopy(payload)
    mappings = fields(payload, operation)
    cat = rpc({'action': 'catalog'})
    require(isinstance(cat.get('catalog_version'), str) and isinstance(cat.get('kinds'), dict), 'Malformed catalog', 'UNITS_PROTOCOL')
    typed = not operation.endswith('_si')
    missing = {kind: unit for kind, unit in KINDS.values() if kind not in cat['kinds'] or cat['kinds'][kind].get('canonical_unit') != unit}
    if typed:
        require(not missing, 'Main UNIT extension pending: ' + str(missing), 'UNITS_CATALOG_GAP')
        norm = rpc({'action': 'normalize_fields', 'payload': payload, 'fields': mappings})
        fixed = {}
    else:
        # SI compatibility is an explicit existing representation, not a local converter.
        # Available kinds still get the one shared-core audit; missing kinds retain
        # their named fixed-SI contract and are labelled separately, never forged records.
        fixed, admitted = {}, {}
        for pointer, mapping in mappings.items():
            key = pointer.rsplit('/', 1)[-1]; kind, unit = KINDS[key]
            if kind in missing:
                fixed[pointer] = {'kind': kind, 'unit': unit, 'admission': 'explicit_fixed_si_compatibility; full UNIT not_checked'}
            else:
                admitted[pointer] = dict(mapping, **({} if kind == 'count' else {'bare_unit': unit}), source={'kind': 'legacy_si', 'reference': 'Explicit _si operation and input model metadata'})
        norm = rpc({'action': 'normalize_fields', 'payload': payload, 'fields': admitted})
    c = norm['payload']
    require(isinstance(norm.get('records'), dict) and set(norm['records']) == (set(mappings) - set(fixed)), 'UNIT audit coverage mismatch', 'UNITS_PROTOCOL')
    # Counts are never obtained by truncation or scaling.
    if operation.startswith('ac_'):
        require(type(original['points_per_decade']) is int, 'Count must be a JSON integer')
        c['points_per_decade'] = original['points_per_decade']
    si_op = operation if operation.endswith('_si') else operation + '_si'
    validate(c, read_json(ROOT / ('schemas/' + si_op + '.input.schema.json')))
    estimate = validate_si(c, operation)
    require(payload == original, 'Input mutated by normalization', 'UNITS_PROTOCOL')
    return c, {'core_version': '1.0.0', 'catalog_version': cat['catalog_version'], 'representation': 'quantities' if typed else 'explicit_fixed_si_compatibility', 'records': norm['records'], 'fixed_si_fields': fixed, 'missing_catalog_kinds': missing, 'estimated_samples': estimate}
