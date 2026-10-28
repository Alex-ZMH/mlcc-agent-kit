"""Deterministic extended SI contracts. No scientific imports or new unit table."""
from copy import deepcopy
import math
from .common import ROOT, ModuleError, read_json, validate_shape
from .validation import LENGTHS, validate_geometry
from . import EPSILON_0
from .quantity_input import invoke_core, CORE_VERSION

OPERATIONS={'electrothermal_2d':'electrothermal','ac_eqs_2d':'ac_eqs','electromagnetic_2d':'electromagnetic'}
PHYSICAL_CHECKS=['model_applicability','material_provenance','independent_device_reference']
NUMERICAL_CHECKS=['mesh_semantics','linear_solver','field_finiteness','power_balance','source_transfer','thermal_balance','raw_flux_acceptance','mesh_convergence','analytic_reference','port_model_acceptance']


def validate_input(payload,operation):
    if operation not in OPERATIONS: raise ModuleError('UNSUPPORTED_OPERATION','Unknown extended operation')
    validate_shape(payload,read_json(ROOT/f'schemas/{OPERATIONS[operation]}.input.schema.json'))
    validate_geometry(payload)
    if not payload['source_reference'].strip():raise ModuleError('INVALID_INPUT','Geometry/parameter source must be nonblank')
    mats=payload['materials']; thermal=payload['thermal']
    for name,m in mats.items():
        if m['eps_r']<=0 or not math.isfinite(m['eps_r']*EPSILON_0) or m['eps_r']*EPSILON_0<=0 or not m['source_reference'].strip():raise ModuleError('INVALID_MATERIAL','Positive eps_r and material source required: '+name)
    if thermal['ceramic_k_W_per_m_K']<=0 or thermal['Ni_k_W_per_m_K']<=0 or thermal['ambient_K']<=0 or not thermal['source_reference'].strip():
        raise ModuleError('INVALID_INPUT','Positive thermal k, absolute ambient and nonblank source are required')
    if thermal['boundary_kind']=='robin' and thermal['convection_h_W_per_m2_K']<=0:raise ModuleError('INVALID_INPUT','Robin needs positive h; no steady insulated model')
    if thermal['boundary_kind']=='dirichlet' and thermal['convection_h_W_per_m2_K']!=0:raise ModuleError('INVALID_INPUT','Dirichlet requires h=0; losses/cooling not silently combined')
    f=payload['frequency_Hz']
    omega=2*math.pi*f
    if not math.isfinite(omega):raise ModuleError('INVALID_INPUT','Frequency not representable as angular frequency')
    for m in mats.values():
        kappa=complex(m['sigma_S_m']+omega*EPSILON_0*m['eps_r']*m['tan_delta'],omega*EPSILON_0*m['eps_r'])
        if not math.isfinite(kappa.real) or not math.isfinite(kappa.imag):raise ModuleError('INVALID_MATERIAL','Complex conductivity is not representable')
    if operation=='electromagnetic_2d':
        port=payload['port']; current=payload['current']
        if f<=0 or not all(port[x]>0 for x in ('bus_width_m','feed_air_m','bottom_air_m')) or not port['source_reference'].strip():raise ModuleError('INVALID_INPUT','Positive EM frequency/port dimensions and source required')
        I=complex(current['real_A_rms'],current['imag_A_rms'])
        try: current_squared=abs(I)**2
        except OverflowError: current_squared=float('inf')
        if not math.isfinite(current_squared) or current_squared==0:raise ModuleError('INVALID_INPUT','Nonzero representable RMS current required')
        if mats['Ni']['sigma_S_m']<=0 or mats['Ni']['tan_delta']!=0:raise ModuleError('INVALID_MATERIAL','Supported Ni is finite conducting, no extra dielectric loss')
        if mats['air']['sigma_S_m']!=0 or mats['air']['tan_delta']!=0 or mats['air']['eps_r']!=1:raise ModuleError('INVALID_MATERIAL','Air is explicitly lossless with eps_r=1')
    else:
        p=payload['potentials']; dv=complex(p['terminal_a_real_V']-p['terminal_b_real_V'],p['terminal_a_imag_V']-p['terminal_b_imag_V'])
        try: square=abs(dv)**2
        except OverflowError: square=float('inf')
        if not math.isfinite(square) or square==0:raise ModuleError('INVALID_POTENTIALS','Nonzero representable complex potential difference required')
        if payload['dielectric_layout']=='uniform' and any(mats['ceramic_lower'][k]!=mats['ceramic_upper'][k] for k in ('eps_r','sigma_S_m','tan_delta')):
            raise ModuleError('INVALID_MATERIAL','Uniform ceramic must have identical lower/upper coefficients')
        if operation=='electrothermal_2d':
            if not thermal['enabled'] or payload['dielectric_layout']!='uniform' or p['terminal_a_imag_V']!=0 or p['terminal_b_imag_V']!=0:raise ModuleError('INVALID_INPUT','Electrothermal needs enabled heat, uniform dielectric and real potentials')
            loss=payload['loss_model']; m=mats['ceramic_lower']
            if loss in ('dc','lossless') and (f!=0 or payload['voltage_convention']!='dc' or m['tan_delta']!=0):raise ModuleError('INVALID_INPUT','DC/lossless requires f=0, dc convention and tan_delta=0')
            if loss=='lossless' and m['sigma_S_m']!=0:raise ModuleError('INVALID_INPUT','Lossless requires sigma=0')
            if loss=='ac_prescribed' and (f<=0 or payload['voltage_convention']=='dc' or m['sigma_S_m']!=0):raise ModuleError('INVALID_INPUT','Prescribed AC uses dielectric loss only; f>0, rms/peak, sigma=0')
        elif f<=0 or payload['voltage_convention']=='dc':raise ModuleError('INVALID_INPUT','AC EQS requires f>0 and rms/peak convention; use static/DC operation for f=0')
    return payload


def canonicalize(payload,operation):
    validate_input(payload,operation)
    fields={f'/geometry/{name}':{'kind':'length','bare_unit':'m','source':{'kind':'input','reference':payload['source_reference']}} for name in LENGTHS}
    fields['/geometry/active_gap_count']={'kind':'count'}
    for path in ('/out_of_plane_thickness_m','/mesh/target_size_m'):
        fields[path]={'kind':'length','bare_unit':'m','source':{'kind':'input','reference':payload['source_reference']}}
    fields['/thermal/ambient_K']={'kind':'temperature','bare_unit':'K','source':{'kind':'input','reference':payload['thermal']['source_reference']}}
    for name,m in payload['materials'].items():fields[f'/materials/{name}/eps_r']={'kind':'relative_permittivity','source':{'kind':'parameter_reference','reference':m['source_reference']}}
    if operation=='electromagnetic_2d':
        for key in ('bus_width_m','feed_air_m','bottom_air_m'):fields['/port/'+key]={'kind':'length','bare_unit':'m','source':{'kind':'input','reference':payload['port']['source_reference']}}
    else:
        for key in payload['potentials']:fields['/potentials/'+key]={'kind':'electric_potential','bare_unit':'V','source':{'kind':'input','reference':payload['source_reference']}}
    batch=invoke_core({'schema_version':'mlcc.units-request.v1','action':'normalize_fields','payload':payload,'fields':fields})
    if set(batch.get('records',{}))!=set(fields) or batch.get('core_version')!=CORE_VERSION or batch.get('payload')!=payload:
        raise ModuleError('UNITS_CORE_FAILED','Explicit SI normalization changed payload or omitted evidence')
    canonical=deepcopy(batch['payload']); validate_input(canonical,operation)
    return canonical,{'schema_version':'fem.extended-units.v1','core_version':CORE_VERSION,'records':batch['records'],
        'other_fields':'Fixed SI suffix fields from strict schema; frequency Hz, conductivity S/m, k W/(m K), h W/(m2 K), RMS current A. No local conversions or inferred units.'}


def validate_result(results,payload):
    validate_shape(results,read_json(ROOT/'schemas/device.output.schema.json'),'results')
    if results['analysis']!=payload['analysis'] or results['out_of_plane_thickness_m']!=payload['out_of_plane_thickness_m'] or results['frequency_Hz']!=payload['frequency_Hz']:
        raise ModuleError('INVALID_SCIENTIFIC_RESULT','Extended result belongs to another model/depth/frequency')
    e=results['electrical']; total=e['loss_total_W']
    if not math.isclose(total,e['loss_ceramic_W']+e['loss_metal_W'],rel_tol=1e-12,abs_tol=1e-30):raise ModuleError('INVALID_SCIENTIFIC_RESULT','Loss split inconsistent')
    def same(a,b):return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-30)
    mode=payload['analysis']
    if mode=='electrothermal':
        dv=payload['potentials']['terminal_a_real_V']-payload['potentials']['terminal_b_real_V']
        if payload['voltage_convention']=='peak':dv/=math.sqrt(2)
        if e['electric_energy_J'] is None or e['capacitance_F'] is None or not same(e['capacitance_F'],2*e['electric_energy_J']/dv**2):raise ModuleError('INVALID_SCIENTIFIC_RESULT','Energy capacitance normalization differs')
        if e['admittance_S'] is not None or e['impedance_ohm'] is not None:raise ModuleError('INVALID_SCIENTIFIC_RESULT','Prescribed-loss ET cannot claim full complex admittance')
    else:
        if e['admittance_S'] is None or e['impedance_ohm'] is None:raise ModuleError('INVALID_SCIENTIFIC_RESULT','Missing complex port quantities')
        Y,Z=complex(*e['admittance_S']),complex(*e['impedance_ohm'])
        if abs(Y)==0 or abs(Y*Z-1)>1e-12:raise ModuleError('INVALID_SCIENTIFIC_RESULT','Reciprocal port normalization differs')
        if mode=='ac_eqs' and (e['capacitance_F'] is None or not same(e['capacitance_F'],Y.imag/(2*math.pi*payload['frequency_Hz']))):raise ModuleError('INVALID_SCIENTIFIC_RESULT','Parallel capacitance definition differs')
        if mode=='electromagnetic':
            I=complex(payload['current']['real_A_rms'],payload['current']['imag_A_rms'])
            if e['magnetic_energy_J'] is None or e['magnetic_inductance_H'] is None or not same(e['magnetic_inductance_H'],2*e['magnetic_energy_J']/abs(I)**2):raise ModuleError('INVALID_SCIENTIFIC_RESULT','Magnetic energy inductance normalization differs')
    if mode!='electromagnetic' and (e['loss_metal_W']!=0 or e['magnetic_energy_J'] is not None or e['magnetic_inductance_H'] is not None):raise ModuleError('INVALID_SCIENTIFIC_RESULT','Ideal electrodes cannot report Ni heating or magnetic response')
    t=results['thermal']
    if t['enabled']!=payload['thermal']['enabled']:raise ModuleError('INVALID_SCIENTIFIC_RESULT','Thermal flag differs')
    keys=set(t)-{'enabled'}
    if not t['enabled'] and any(t[k] is not None for k in keys):raise ModuleError('INVALID_SCIENTIFIC_RESULT','Disabled heat must not contain synthetic temperature data')
    if t['enabled']:
        if any(t[k] is None for k in keys-{'hotspot_thermal_resistance_K_per_W','mean_thermal_resistance_K_per_W'}):raise ModuleError('INVALID_SCIENTIFIC_RESULT','Missing thermal result')
        ambient=payload['thermal']['ambient_K']
        if not math.isclose(t['maximum_temperature_K'],ambient+t['maximum_rise_K'],rel_tol=1e-12,abs_tol=0) or not math.isclose(t['mean_temperature_K'],ambient+t['mean_rise_K'],rel_tol=1e-12,abs_tol=0):raise ModuleError('INVALID_SCIENTIFIC_RESULT','Temperature/rise normalization differs')
        if not math.isclose(t['source_power_W'],total,rel_tol=1e-12,abs_tol=1e-30):raise ModuleError('INVALID_SCIENTIFIC_RESULT','Transferred power differs from electrical loss')
        for rise,resistance in (('maximum_rise_K','hotspot_thermal_resistance_K_per_W'),('mean_rise_K','mean_thermal_resistance_K_per_W')):
            if total==0:
                if t[resistance] is not None:raise ModuleError('INVALID_SCIENTIFIC_RESULT','Zero-power thermal resistance undefined')
            elif t[resistance] is None or not math.isclose(t[resistance]*total,t[rise],rel_tol=1e-12,abs_tol=1e-30):raise ModuleError('INVALID_SCIENTIFIC_RESULT','Thermal resistance normalization differs')


def evaluate_checks(payload,diag):
    """Re-evaluate inherited numerical criteria from measured diagnostics on Windows."""
    a=payload['analysis'];r=diag['electrical'];s=r['solver']
    if a=='electrothermal':
        linear=s['reason']>0 and s['relative_residual']<1e-8
        power=r['terminal_power_relative_error']<1e-9
    elif a=='ac_eqs':
        linear=s['reason']>0 and s['relative_free_residual']<1e-9
        power=r['complex_work_relative_error']<1e-9 and r['current_balance_relative']<1e-9 and r['q_dot_identity_relative']<1e-12
    else:
        linear=s['reason']>0 and r['weak_Maxwell_relative_residual']<1e-7
        power=r['complex_power_relative_error']<1e-7 and r['active_power_relative_error']<1e-5
    values={'linear_solver':bool(linear),'power_balance':bool(power),'mesh_semantics':True,
            'field_finiteness':all(v['VTU_readback']=='PASS' for v in diag['outputs'].values())}
    if payload['thermal']['enabled']:
        t=diag['thermal'];tr=diag['source_transfer'];values['source_transfer']=tr['relative_error']<1e-12 and (a=='electromagnetic' or tr['Ni_source_max_W_m3']==0)
        values['linear_solver'] &= t['solver']['reason']>0
        if a=='electrothermal':values['linear_solver'] &= max(t['solver']['relative_residual'],t['weak_residual_relative'])<1e-8
        total=r['loss_power_W' if a=='electrothermal' else 'volume_power_W' if a=='ac_eqs' else 'volume_loss_W']
        values['thermal_balance']=t['balance_absolute_W']<1e-10 if total==0 else t['balance_relative']<(1e-8 if a=='electromagnetic' else 1e-9)
    return {k:bool(v) for k,v in values.items()}
