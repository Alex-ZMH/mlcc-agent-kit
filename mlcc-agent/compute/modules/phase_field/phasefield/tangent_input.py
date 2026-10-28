"""Strict static tangent inputs and unique shared-UNIT admission; stdlib only."""
from copy import deepcopy
import math
from .common import ROOT,digest,read_json
from .validation import shape
from .vector_input import require,scalar,vector
from .scaling import derive,finite
from .si_input import unit_core

OPERATIONS=('dielectric_tangent','dielectric_tangent_si')
def estimate_resources(p):
    d=p['dimension'];nodes=math.prod(n+1 for n in p['cells']);cells=math.prod(p['cells'])*(2 if d==2 else 6)
    states=len(p['loading_path'])+(12*d if p['verification']['finite_difference'] else 0)+4
    return {'cells':cells,'dofs':nodes*(d+1),'work':cells*(d+1)*states,
            'history_bytes':nodes*(d+1)*8*states*4+cells*d*8*states*3,
            'dense_stability_matrix_bytes':nodes**2*(d+1)**2*8}
def validate_reduced(payload):
    p=deepcopy(payload);require(p['operation']=='dielectric_tangent' and p['units']=='dimensionless','Reduced static tangent required')
    require(p['model_profile']=='synthetic_tetragonal_quartic_v1' and p['boundary_condition']=='all_surface_voltage','Reviewed profile and fixed-voltage boundary required')
    d=p['dimension'];require(type(d) is int and d in (2,3),'Two/three dimensions only')
    require(len(p['cells'])==d and all(type(n) is int and n>0 for n in p['cells']),'Positive dimension-matched mesh counts required')
    par=p['parameters'];require(set(par)=={'a','b','c','g','epsilon'},'Five explicit static model parameters required; no mobility or dt')
    for v in par.values():scalar(v)
    require(par['a']<0 and par['b']>0 and par['c']>2*par['b'] and par['g']>0 and par['epsilon']>0,'Invalid quartic/gradient/background coefficients')
    initial=p['initial_condition'];kind=initial['kind']
    require(kind in ('uniform','wall_180','wall_90xy','wall_90xz'),'Unsupported static initial state')
    if kind=='uniform':
        require(set(initial)=={'kind','values'} and 'wall_half_length' not in p,'Uniform state requires explicit vector; no wall specimen length')
        vector(initial['values'],d)
    else:
        require(set(initial)=={'kind'} and 'wall_half_length' in p,'Wall template requires explicit finite specimen half length')
        require(kind!='wall_90xz' or d==3,'90xz needs three components')
        scalar(p['wall_half_length']);require(1<=p['wall_half_length']<=8,'Reviewed wall half length in [1,8]')
        # Preserve the underlying frozen vector constructor's planning guard.
        require(16/p['cells'][0]<=math.sqrt(par['g']/abs(par['a']))/2+1e-12,'Unresolved source wall template')
        require(not p['verification']['analytical'],'Uniform Hessian reference is not a wall validation')
    path=p['loading_path'];require(isinstance(path,list) and 1<=len(path)<=100,'Explicit bounded bias loading path required')
    for value in path:vector(value,d)
    scalar(p['equilibrium_atol'],positive=True);require(p['equilibrium_atol']<=1e-8,'Frozen strict equilibrium atol <=1e-8 required')
    require(set(p['verification'])=={'finite_difference','analytical'} and all(type(v) is bool for v in p['verification'].values()),'Explicit independent-check selection required')
    budget=estimate_resources(p)
    require(budget['dofs']<=3300,'Dense stability eigensolve operational cap: 3300 total DOFs, no automatic coarsening','RESOURCE_LIMIT')
    return p
def semantics(p):
    result={f'/reference_scales/{k}':{'kind':kind} for k,kind in [('length','length'),('polarization','polarization'),('time','time'),('energy_density','energy_density')]}
    result.update({'/g':{'kind':'gradient_coefficient'},'/epsilon':{'kind':'absolute_permittivity'}})
    result.update({f'/reduced_parameters/{k}':{'kind':'dimensionless_parameter'} for k in ['a','b','c']})
    if p['initial_condition']['kind']=='uniform':result.update({f'/initial_condition/values/{i}':{'kind':'polarization'} for i in range(p['dimension'])})
    if 'wall_half_length' in p:result['/wall_half_length']={'kind':'length'}
    result.update({f'/loading_path/{j}/{i}':{'kind':'electric_field'} for j,row in enumerate(p['loading_path']) for i in range(len(row))})
    return result
def reduce_si(canonical):
    p=deepcopy(canonical);base=derive(p.pop('reference_scales'),p['dimension']);f=base['factors']
    par=p.pop('reduced_parameters');par.update(g=finite(p.pop('g')/f['g'],True),epsilon=finite(p.pop('epsilon')/f['epsilon'],True))
    p.update(parameters=par,operation='dielectric_tangent',units='dimensionless')
    if p['initial_condition']['kind']=='uniform':p['initial_condition']['values']=[finite(v/f['polarization']) for v in p['initial_condition']['values']]
    if 'wall_half_length' in p:p['wall_half_length']=finite(p['wall_half_length']/f['length'],True)
    p['loading_path']=[[finite(v/f['electric_field']) for v in row] for row in p['loading_path']]
    derived={'factors':f,'energy_unit':base['energy_unit'],'tensor_factor_F_per_m':f['polarization']/f['electric_field'],
             'tensor_relation':'epsilon_abs_SI=(P0/E0)*epsilon_nd=P0^2/f0*epsilon_nd; not relative permittivity',
             'physical_vector_coefficients':{'a':finite(par['a']*f['energy_density']/f['polarization']**2),
                'b':finite(par['b']*f['energy_density']/f['polarization']**4),'c':finite(par['c']*f['energy_density']/f['polarization']**4)},
             'time_scale_role':'retained for compatibility; no time step/mobility/BE term in static response','material_calibration':'not_checked'}
    return validate_reduced(p),derived
def prepare(payload,operation):
    require(operation in OPERATIONS,'Unsupported tangent operation','UNSUPPORTED_OPERATION')
    shape(payload,read_json(ROOT/'schemas'/f'{operation}.input.schema.json'))
    require(payload['operation']==operation,'Operation and input mismatch')
    if not operation.endswith('_si'):return validate_reduced(payload),None
    rules=semantics(payload);normal=unit_core({'schema_version':'mlcc.units-request.v1','action':'normalize_fields','payload':payload,'fields':rules})
    require(set(normal)=={'payload','records','core_version'} and normal['core_version']=='1.0.0','Unexpected UNIT response','UNIT_CORE_INCOMPATIBLE')
    require(set(normal['records'])==set(rules),'UNIT audit field coverage mismatch','UNIT_CORE_INCOMPATIBLE')
    expected=deepcopy(payload)
    for pointer,rule in rules.items():
        parts=pointer.lstrip('/').split('/');node=expected
        for part in parts[:-1]:node=node[int(part)] if isinstance(node,list) else node[part]
        key=int(parts[-1]) if isinstance(node,list) else parts[-1];record=normal['records'][pointer]
        require(record.get('kind')==rule['kind'] and record.get('schema_version')=='mlcc.quantity.v1' and record.get('original',{}).get('representation')==node[key] and record.get('conversion',{}).get('core_version')=='1.0.0','UNIT audit semantic/original mismatch','UNIT_CORE_INCOMPATIBLE')
        node[key]=finite(record['normalized']['value'])
    require(expected==normal['payload'],'UNIT modified undeclared data','UNIT_CORE_INCOMPATIBLE')
    p,derived=reduce_si(normal['payload'])
    return p,{'schema_version':'phase_field.tangent-unit-mapping.v1','original_input':deepcopy(payload),'original_input_sha256':digest(payload),
              'canonical_si':normal['payload'],'normalization_report':normal,'derived':derived,'solver_input_sha256':digest(p),
              'qc_domain':'dimensionless','material_calibration':'not_checked'}
