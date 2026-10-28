"""Deterministic scientific validation. No solver imports, default injection or LLM."""
import math
from . import EPSILON_0
from .common import ROOT, ModuleError, read_json, validate_shape

LENGTHS = ('body_length_m', 'dielectric_gap_m', 'electrode_thickness_m',
           'electrode_overlap_m', 'left_margin_m', 'right_margin_m',
           'top_cover_m', 'bottom_cover_m')


def body_height(payload):
    p = payload['geometry']
    n = p['active_gap_count'] + 1
    return p['bottom_cover_m'] + p['top_cover_m'] + n*p['electrode_thickness_m'] + (n-1)*p['dielectric_gap_m']


def validate_input(payload):
    validate_shape(payload, read_json(ROOT / 'schemas/electrostatics.input.schema.json'))
    validate_geometry(payload)
    if payload['material']['relative_permittivity'] <= 0 or not payload['material']['source_reference'].strip():
        raise ModuleError('INVALID_MATERIAL', 'Positive relative permittivity and nonblank source are required')
    epsilon = EPSILON_0*payload['material']['relative_permittivity']
    if not math.isfinite(epsilon) or epsilon <= 0:
        raise ModuleError('INVALID_MATERIAL', 'Absolute permittivity is not positive/representable in the supported floating-point model')
    a, b = payload['potentials']['terminal_a_V'], payload['potentials']['terminal_b_V']
    dv = a-b
    if not math.isfinite(dv) or dv == 0 or not math.isfinite(dv*dv) or dv*dv == 0:
        raise ModuleError('INVALID_POTENTIALS', 'Distinct finite potentials with representable squared difference are required')
    if not math.isfinite(body_height(payload)):
        raise ModuleError('INVALID_GEOMETRY', 'Derived body height is not finite')
    return payload


def estimate_cells(payload):
    """Conservative planning indicator, not an accuracy/quality claim or a hard mesh bound."""
    p = payload['geometry']
    h = min(payload['mesh']['target_size_m'], p['dielectric_gap_m'], p['electrode_thickness_m'])
    estimate = 2 * (p['body_length_m']/h) * (body_height(payload)/h)
    if not math.isfinite(estimate):
        raise ModuleError('RESOURCE_LIMIT', 'Non-finite mesh resource estimate')
    return math.ceil(estimate)


def validate_result(results, payload):
    try:
        validate_shape(results, read_json(ROOT / 'schemas/electrostatics.output.schema.json'), 'results')
        if results['model'] != payload['model'] or results['out_of_plane_thickness_m'] != payload['out_of_plane_thickness_m']:
            raise ValueError('Model/depth differs from requested model')
        t = payload['out_of_plane_thickness_m']
        dv = abs(payload['potentials']['terminal_a_V'] - payload['potentials']['terminal_b_V'])
        # These are representation/normalization contracts, not physical acceptance tolerances.
        def same(a, b):
            return math.isclose(a, b, rel_tol=1e-12, abs_tol=0)
        for total, per in (('energy_total_J','energy_per_unit_depth_J_per_m'),
                           ('capacitance_energy_total_F','capacitance_energy_per_unit_depth_F_per_m')):
            if results[total] <= 0 or not same(results[total]/t, results[per]):
                raise ValueError('Invalid total/per-depth normalization')
        for name in ('ELECTRODE_A', 'ELECTRODE_B'):
            if not same(results['charge_total_C'][name]/t, results['charge_per_unit_depth_C_per_m'][name]):
                raise ValueError('Invalid charge depth normalization')
        if not same(results['capacitance_energy_total_F'], 2*results['energy_total_J']/dv**2):
            raise ValueError('Inconsistent energy capacitance')
        if not same(results['capacitance_raw_flux_total_F'], abs(results['charge_total_C']['ELECTRODE_A'])/dv):
            raise ValueError('Inconsistent raw-flux capacitance')
        if not same(results['body_height_m'], body_height(payload)):
            raise ValueError('Incorrect derived body height')
        q = list(results['charge_total_C'].values())
        balance = abs(sum(q))/max(*(abs(value) for value in q),1e-30)
        difference = abs(results['capacitance_raw_flux_total_F']-results['capacitance_energy_total_F'])/results['capacitance_energy_total_F']
        if not same(balance,results['charge_balance_relative']) or not same(difference,results['capacitance_methods_relative']):
            raise ValueError('Inconsistent balance/capacitance diagnostics')
        if results['potential_min_V'] > results['potential_max_V']:
            raise ValueError('Reversed field range')
    except (ModuleError, ValueError, KeyError, ZeroDivisionError, OverflowError) as exc:
        raise ModuleError('INVALID_SCIENTIFIC_RESULT', str(exc)) from exc


def validate_geometry(payload):
    p = payload['geometry']
    for name in LENGTHS:
        if p[name] <= 0:
            raise ModuleError('INVALID_GEOMETRY', f'geometry.{name} must be positive')
    if not math.isclose(p['body_length_m'], p['left_margin_m'] + p['electrode_overlap_m'] + p['right_margin_m'],
                        rel_tol=1e-9, abs_tol=1e-15):
        raise ModuleError('INVALID_GEOMETRY', 'left_margin + electrode_overlap + right_margin must equal body_length')
    if payload['out_of_plane_thickness_m'] <= 0 or payload['mesh']['target_size_m'] <= 0:
        raise ModuleError('INVALID_INPUT', 'Depth and mesh target size must be positive')
    if not math.isfinite(body_height(payload)):
        raise ModuleError('INVALID_GEOMETRY','Derived body height is not finite')
    return payload
