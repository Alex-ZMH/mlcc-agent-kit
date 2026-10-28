"""Stdlib-only explicit vector input and shared-UNIT admission; no scientific imports."""
from copy import deepcopy
import math
from .common import ROOT, ModuleError, digest, read_json
from .validation import shape
from .scaling import derive, finite
from .si_input import unit_core

OPERATIONS = ('vector_steady', 'vector_evolve', 'vector_steady_si', 'vector_evolve_si')
PROFILE = 'synthetic_tetragonal_quartic_v1'

def require(condition, message, code='INVALID_INPUT'):
    if not condition:
        raise ModuleError(code, message)

def scalar(value, *, positive=False):
    require(type(value) in (float, int) and math.isfinite(value) and (not positive or value > 0), 'Finite numeric vector model value required')
    return value

def vector(value, dimension):
    require(isinstance(value, list) and len(value) == dimension, 'Vector length must equal spatial/polarization dimension')
    return [scalar(x) for x in value]

def validate_reduced(payload):
    p = deepcopy(payload)
    require(p['operation'] in ('vector_steady', 'vector_evolve'), 'Reduced vector operation required')
    require(p['units'] == 'dimensionless' and p['model_profile'] == PROFILE and p['boundary_condition'] == 'all_surface_voltage', 'Explicit reviewed vector profile/boundary required')
    d = p['dimension']
    require(type(d) is int and d in (2, 3), 'Dimension must be exactly 2 or 3')
    cells = p['cells']
    require(isinstance(cells, list) and len(cells) == d and all(type(x) is int and x > 0 for x in cells), 'Explicit positive dimension-matched mesh counts required')
    a = p['parameters']
    require(set(a) == {'a','b','c','g','epsilon','mobility'}, 'Complete reduced model parameters required')
    for x in a.values(): scalar(x)
    require(a['a'] < 0 and a['b'] > 0 and a['c'] > 2*a['b'] and min(a['g'],a['epsilon'],a['mobility']) > 0, 'Reviewed axis-minimum model requires a<0,b>0,c>2b,g/epsilon/mobility>0')
    initial = p['initial_condition']; kind = initial['kind']
    require(kind in ('uniform','perturb','wall_180','wall_90xy','wall_90xz'), 'Unsupported vector initial state')
    if kind == 'uniform':
        require(set(initial) == {'kind','values'}, 'Uniform initial state requires only values')
        vector(initial['values'], d)
    elif kind == 'perturb':
        require(set(initial) == {'kind'}, 'Perturbation is the fixed frozen experiment profile')
    else:
        require(set(initial) == {'kind','width_factor'}, 'Wall initial state requires explicit width_factor')
        scalar(initial['width_factor'], positive=True)
        require(kind != 'wall_90xz' or d == 3, '90xz requires three components')
        delta = math.sqrt(a['g']/abs(a['a']))
        require(math.isfinite(delta) and delta > 0 and 16/cells[0] <= delta/2+1e-12, 'Unresolved wall: use the frozen four-cells-per-2delta planning guard')
    wave = p['field_protocol']; typ = wave['kind']
    if typ == 'constant':
        require(set(wave) == {'kind','value'}, 'Constant field keys invalid')
        vector(wave['value'], d)
    elif typ == 'triangle':
        require(set(wave) == {'kind','direction','amplitude','period'}, 'Triangle field keys invalid')
        v = vector(wave['direction'], d)
        require(0 < math.hypot(*v) < math.inf, 'Finite nonzero triangular-field direction required')
        scalar(wave['amplitude'], positive=True); scalar(wave['period'], positive=True)
    elif typ == 'stairs':
        require(set(wave) == {'kind','times','values'}, 'Stair field keys invalid')
        ts = wave['times']; vs = wave['values']
        require(isinstance(ts,list) and 1 <= len(ts) <= 100 and len(vs) == len(ts), 'Matching nonempty bounded stair arrays required')
        for t in ts: scalar(t)
        require(ts[0] == 0 and all(b > a for a,b in zip(ts,ts[1:])), 'Stair times must start at zero and strictly increase')
        for v in vs: vector(v,d)
    else: require(False, 'Unsupported electric waveform')
    e = p['evolution']
    require(set(e) == {'end','dt','max_steps','max_halvings'}, 'Explicit integration/resource controls required')
    scalar(e['end']); scalar(e['dt'],positive=True)
    require(e['end'] >= 0 and e['dt'] <= .2, 'Frozen integrator requires end>=0 and 0<dt<=0.2')
    require(type(e['max_steps']) is int and 1 <= e['max_steps'] <= 2000, 'Explicit accepted-step guard must be 1..2000')
    require(type(e['max_halvings']) is int and 0 <= e['max_halvings'] <= 6, 'PoC retry/rollback limit must be 0..6')
    if p['operation'] == 'vector_evolve': require(e['end'] > 0, 'Evolution must advance time')
    else: require(typ == 'constant', 'Steady solve requires a constant voltage boundary; use evolve for waveforms')
    if typ == 'stairs': require(ts[-1] < e['end'], 'Each stair must occur before the explicit end time')
    require(math.ceil(e['end']/e['dt']) <= e['max_steps'], 'Requested integration exceeds accepted-step budget', 'RESOURCE_LIMIT')
    budget = estimate_resources(p)
    require(budget['dofs'] <= 25000, 'Frozen vector direct-LU DOF cap 25000', 'RESOURCE_LIMIT')
    return p

def estimate_resources(p):
    d=p['dimension']; cells=math.prod(p['cells'])*(2 if d==2 else 6)
    nodes=math.prod(x+1 for x in p['cells']); steps=p['evolution']['max_steps']+2
    return {'cells':cells,'dofs':nodes*(d+1),'work':cells*(d+1)*steps,
            'history_bytes':nodes*(d+1)*8*steps*2+cells*(d+1)*8*4}

def semantics(p):
    fields={f'/reference_scales/{k}':{'kind':kind} for k,kind in (
        ('length','length'),('polarization','polarization'),('time','time'),('energy_density','energy_density'))}
    fields.update({'/g':{'kind':'gradient_coefficient'},'/epsilon':{'kind':'absolute_permittivity'}})
    fields.update({f'/reduced_parameters/{k}':{'kind':'dimensionless_parameter'} for k in ('a','b','c','mobility')})
    initial=p['initial_condition']
    if initial['kind']=='uniform':
        fields.update({f'/initial_condition/values/{i}':{'kind':'polarization'} for i in range(len(initial['values']))})
    elif initial['kind'].startswith('wall'): fields['/initial_condition/width']={'kind':'length'}
    for k in ('end','dt'): fields['/evolution/'+k]={'kind':'time'}
    wave=p['field_protocol']
    if wave['kind']=='constant':
        fields.update({f'/field_protocol/value/{i}':{'kind':'electric_field'} for i in range(len(wave['value']))})
    elif wave['kind']=='triangle':
        fields['/field_protocol/amplitude']={'kind':'electric_field'}; fields['/field_protocol/period']={'kind':'time'}
    elif wave['kind']=='stairs':
        fields.update({f'/field_protocol/times/{i}':{'kind':'time'} for i in range(len(wave['times']))})
        fields.update({f'/field_protocol/values/{i}/{j}':{'kind':'electric_field'} for i,v in enumerate(wave['values']) for j in range(len(v))})
    return fields

def reduce_si(canonical):
    p=deepcopy(canonical); original_op=p['operation']; d=p['dimension']
    base=derive(p.pop('reference_scales'),d); f=base['factors']
    a=p.pop('reduced_parameters'); a['g']=finite(p.pop('g')/f['g'],True); a['epsilon']=finite(p.pop('epsilon')/f['epsilon'],True)
    p['parameters']=a; p['operation']=original_op.removesuffix('_si'); p['units']='dimensionless'
    initial=p['initial_condition']
    if initial['kind']=='uniform': initial['values']=[finite(x/f['polarization']) for x in initial['values']]
    elif initial['kind'].startswith('wall'):
        delta=math.sqrt(a['g']/abs(a['a'])); initial['width_factor']=finite(initial.pop('width')/(f['length']*delta),True)
    for k in ('end','dt'): p['evolution'][k]=finite(p['evolution'][k]/f['time'])
    wave=p['field_protocol']
    if wave['kind']=='constant': wave['value']=[finite(x/f['electric_field']) for x in wave['value']]
    elif wave['kind']=='triangle':
        wave['amplitude']=finite(wave['amplitude']/f['electric_field'],True);wave['period']=finite(wave['period']/f['time'],True)
    else:
        wave['times']=[finite(x/f['time']) for x in wave['times']]
        wave['values']=[[finite(x/f['electric_field']) for x in v] for v in wave['values']]
    derived={'factors':f,'factor_units_si':base['factor_units_si'],'energy_unit':base['energy_unit'],
             'coefficient_definition':'fL=a*sum(Pi^2)+b*sum(Pi^4)+c*sum(Pi^2*Pj^2); no 1/2 or 1/4 factors',
             'physical_coefficients':{'a':finite(a['a']*f['energy_density']/f['polarization']**2),
                  'b':finite(a['b']*f['energy_density']/f['polarization']**4),
                  'c':finite(a['c']*f['energy_density']/f['polarization']**4),
                  'g':canonical['g'],'epsilon_absolute':canonical['epsilon'],
                  'mobility':finite(a['mobility']*base['profile_coefficients_si']['mobility'])},
             'material_calibration':'not_checked'}
    return validate_reduced(p), derived

def prepare(payload, operation):
    require(operation in OPERATIONS, 'Unsupported vector operation', 'UNSUPPORTED_OPERATION')
    shape(payload,read_json(ROOT/'schemas'/f'{operation}.input.schema.json'))
    require(payload['operation']==operation, 'Operation/input mismatch')
    if not operation.endswith('_si'): return validate_reduced(payload),None
    rules=semantics(payload)
    normalized=unit_core({'schema_version':'mlcc.units-request.v1','action':'normalize_fields','payload':payload,'fields':rules})
    require(set(normalized)=={'payload','records','core_version'} and normalized['core_version']=='1.0.0', 'Invalid shared unit response', 'UNIT_CORE_INCOMPATIBLE')
    expected=deepcopy(payload);records=normalized['records']
    require(set(records)==set(rules), 'Unit audit field coverage mismatch', 'UNIT_CORE_INCOMPATIBLE')
    for pointer, rule in rules.items():
        parts=pointer.lstrip('/').split('/'); node=expected
        for part in parts[:-1]: node=node[int(part)] if isinstance(node,list) else node[part]
        key=int(parts[-1]) if isinstance(node,list) else parts[-1]; record=records[pointer]
        require(record.get('schema_version')=='mlcc.quantity.v1' and record.get('kind')==rule['kind'] and record.get('original',{}).get('representation')==node[key] and record.get('conversion',{}).get('core_version')=='1.0.0', 'Shared UNIT audit semantic/original mismatch', 'UNIT_CORE_INCOMPATIBLE')
        node[key]=finite(record['normalized']['value'])
    require(expected==normalized['payload'], 'Normalizer altered undeclared data', 'UNIT_CORE_INCOMPATIBLE')
    p,derived=reduce_si(normalized['payload'])
    context={'schema_version':'phase_field.vector-unit-mapping.v1','original_input':deepcopy(payload),
             'canonical_si':normalized['payload'],'normalization_report':normalized,'derived':derived,
             'original_input_sha256':digest(payload),'solver_input_sha256':digest(p),
             'qc_domain':'dimensionless','material_calibration':'not_checked'}
    return p,context
