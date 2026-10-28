"""Deterministic contracts, no scientific imports and no experiment defaults."""
import math
from .common import ROOT, ModuleError, read_json


def shape(v, s, path='input'):
    types = {'object': dict, 'array': list, 'number': (int, float), 'integer': int,
             'string': str, 'boolean': bool, 'null': type(None)}
    kinds = s.get('type', list(types))
    if isinstance(kinds, str): kinds = [kinds]
    valid = any(isinstance(v, types[k]) and not (k in ('number','integer') and isinstance(v,bool)) for k in kinds)
    if not valid or type(v) in (int,float) and not math.isfinite(v):
        raise ModuleError('INVALID_INPUT', f'{path}: wrong type/nonfinite')
    if 'const' in s and v != s['const'] or 'enum' in s and v not in s['enum']:
        raise ModuleError('INVALID_INPUT', f'{path}: unsupported value')
    if isinstance(v,dict):
        props=s.get('properties',{})
        if set(s.get('required',[]))-v.keys() or s.get('additionalProperties') is False and v.keys()-props.keys():
            raise ModuleError('INVALID_INPUT', f'{path}: missing or unknown fields')
        for k,x in v.items():
            if k in props: shape(x,props[k],path+'.'+k)
    elif isinstance(v,list):
        if not s.get('minItems',0)<=len(v)<=s.get('maxItems',math.inf):
            raise ModuleError('INVALID_INPUT', f'{path}: array length')
        for i,x in enumerate(v): shape(x,s.get('items',{}),f'{path}[{i}]')
    elif type(v) in (int,float):
        if not s.get('minimum',-math.inf)<=v<=s.get('maximum',math.inf):
            raise ModuleError('INVALID_INPUT', f'{path}: bounds')
    elif isinstance(v,str) and len(v)<s.get('minLength',0):
        raise ModuleError('INVALID_INPUT',f'{path}: empty')


def validate_input(p, operation=None):
    op=operation or (p.get('operation') if isinstance(p,dict) else None)
    if op not in ('steady','evolve'): raise ModuleError('UNSUPPORTED_OPERATION','Use steady/evolve')
    shape(p,read_json(ROOT/'schemas'/f'{op}.input.schema.json'))
    d=p['dimension']; m=p['mesh']; ic=p['initial']; k=ic['kind']
    if ('nz' in m)!=(d==3): raise ModuleError('INVALID_INPUT','nz required only for 3D')
    if op=='steady' and 'evolution' in p: raise ModuleError('INVALID_INPUT','steady has no evolution controls')
    required={'uniform':{'value'},'wall':{'width','wall_center'},'nucleus':{'center','radii'}|({'zcenter','zradius'} if d==3 else set()),'random':{'seed','modes','amplitude','reference'}}[k]
    if set(ic)!=(required|{'kind'}): raise ModuleError('INVALID_INPUT',f'{k}: expected exactly {sorted(required)}')
    if k=='wall' and not -8<ic['wall_center']<8: raise ModuleError('INVALID_INPUT','wall center outside domain interior')
    if k=='nucleus':
        if not -8<ic['center'][0]<8 or not 0<ic['center'][1]<4 or d==3 and not -2<ic['zcenter']<2:
            raise ModuleError('INVALID_INPUT','Nucleus center must be strictly interior; cosine warp otherwise singular')
        # Guard floating-point singular denominators near boundaries as well.
        sines=[math.sin(math.pi*(ic['center'][0]+8)/16),math.sin(math.pi*ic['center'][1]/4)]
        if d==3:sines.append(math.sin(math.pi*(ic['zcenter']+2)/4))
        if min(map(abs,sines))<1e-12: raise ModuleError('INVALID_INPUT','Numerically singular nucleus center')
    if k=='random' and any(m[x]<2*(ic['modes']-1) for x in ('nx','ny','nz')[:d]):
        raise ModuleError('INVALID_INPUT','Mesh must resolve the finite cosine band with at least two cells per highest half-wave')
    if op=='evolve':
        c=p['evolution']
        if c['end']<1e-10 or c['dt']/2**c['max_halvings']<1e-10:
            raise ModuleError('INVALID_INPUT','Time resolution below supported absolute 1e-12 termination tolerance')
    return p


def initial_config(p):
    c=dict(p['initial'])
    if c['kind']=='wall': c['center']=c.pop('wall_center')
    if c['kind']=='random':c['dimension']=p['dimension']
    if c['kind']=='nucleus' and p['dimension']==3:c['three_dimensional']=True
    return c


def estimate_resources(p):
    m=p['mesh']; d=p['dimension']; nodes=(m['nx']+1)*(m['ny']+1)*(m.get('nz',0)+1)
    cells=(2 if d==2 else 6)*m['nx']*m['ny']*m.get('nz',1)
    c=p.get('evolution');steps=math.ceil(c['end']/c['dt'])*2**c['max_halvings']+1 if c else 1
    # Conservative planning weights; RT is a separate mixed direct system.
    return {'cells':cells,'work':cells*(steps*((c['max_halvings']+1) if c else 1)+(8 if p['output']['rt0'] else 0)),
            'history_bytes':nodes*2*8*(steps+1)}


def validate_result(r,p):
    shape(r,read_json(ROOT/'schemas/result.schema.json'),'result')
    for k in ('operation','dimension','model_profile','units'):
        if r[k]!=p[k]: raise ModuleError('INVALID_SCIENTIFIC_RESULT',f'{k} mismatch')
    m=p['mesh'];n=(m['nx']+1)*(m['ny']+1)*(m.get('nz',0)+1)
    if r['mesh']!={'cells':estimate_resources(p)['cells'],'dofs':2*n,'P_dofs':n,'phi_dofs':n}:
        raise ModuleError('INVALID_SCIENTIFIC_RESULT','Mesh/DOF mismatch')
    if not r['readback'].get('passed'):raise ModuleError('INVALID_SCIENTIFIC_RESULT','Native fields failed readback')
    if p['operation']=='evolve' and abs(r['time']['completed']-p['evolution']['end'])>1e-12:
        raise ModuleError('INVALID_SCIENTIFIC_RESULT','Incomplete trajectory')
    if p['operation']=='steady' and (r['time']['completed']!=0 or r['time']['accepted_steps']!=0):
        raise ModuleError('INVALID_SCIENTIFIC_RESULT','Invalid stationary time accounting')
    return r
