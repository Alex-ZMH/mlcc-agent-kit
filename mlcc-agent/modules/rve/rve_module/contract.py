"""Strict Windows stdlib science admission, including direct adapter calls."""
from copy import deepcopy
import math
import subprocess
import sys
from .common import ROOT,ModuleError,read_json,loads,dumps,validate_shape

OPERATIONS={f'homogenize_{p}_{d}d':(d,p) for d in (2,3) for p in ('electrostatics','thermal')}
CORE=ROOT.parents[1]/'src/mlcc/units.py'

def rpc(action,**kwargs):
    if not CORE.is_file():raise ModuleError('UNITS_CORE_UNAVAILABLE','Unique shared core missing; no fallback')
    try:
        run=subprocess.run([sys.executable,'-I',str(CORE)],input=dumps({'schema_version':'mlcc.units-request.v1','action':action,**kwargs}),capture_output=True,text=True,encoding='utf-8',timeout=3,shell=False)
        if len(run.stdout.encode('utf-8'))>2*1024*1024:raise ValueError('Oversized units response')
        r=loads(run.stdout)
        if r.get('schema_version')!='mlcc.units-response.v1' or r.get('core_version')!='1.0.0':raise ValueError('Incompatible units protocol/core')
        if run.returncode or r.get('ok') is not True:raise ModuleError('INVALID_UNITS',dumps(r.get('errors',[])))
        return r['result']
    except ModuleError:raise
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired) as e:raise ModuleError('UNITS_CORE_FAILED',str(e)) from e

def require(condition,message,code='INVALID_INPUT'):
    if not condition:raise ModuleError(code,message)

def spd(value,d):
    """Source tensor_material symmetry tolerance; Cholesky permits negative off-diagonals."""
    a=value
    require(isinstance(a,list) and len(a)==d and all(isinstance(row,list) and len(row)==d for row in a),'Dimension-matched tensor required','INVALID_MATERIAL')
    require(all(type(x) in (int,float) and math.isfinite(x) for row in a for x in row),'Finite matrix required','INVALID_MATERIAL')
    scale=max(abs(x) for row in a for x in row)
    require(scale>0,'Positive definite matrix required','INVALID_MATERIAL')
    scaled=[[x/scale for x in row] for row in a]
    norm=math.sqrt(sum(x*x for row in scaled for x in row))
    require(max(abs(scaled[i][j]-scaled[j][i]) for i in range(d) for j in range(d))<=1e-12*max(norm,1e-30/scale),'Symmetric matrix required','INVALID_MATERIAL')
    l=[[0.]*d for _ in range(d)]
    for i in range(d):
        for j in range(i+1):
            v=scaled[i][j]-sum(l[i][k]*l[j][k] for k in range(j))
            if i==j:
                require(v>0 and math.isfinite(v),'Positive definite matrix required','INVALID_MATERIAL');l[i][j]=math.sqrt(v)
            else:l[i][j]=v/l[j][j]
    return a

def geometry(g,h,d):
    k=g['kind'];base={'kind','physical_lengths','pore_fraction'}
    extra={'homogeneous':set(),'layers':{'normalized_fraction','axis'},'rotated_layers':{'normalized_fraction'},'circle':{'normalized_radius'},'ellipse':{'normalized_radius','normalized_aspect'},'sphere':{'normalized_radius','normalized_center'},'ellipsoid':{'normalized_axes','normalized_center'},'core_shell':{'normalized_radius','normalized_shell'}|({'normalized_center'} if d==3 else set()),'polycrystal':{'grain_count','seed','normalized_gb_width','normalized_shell','jitter'}}
    require(k in extra and set(g)==base|extra[k],'Geometry requires exactly its documented fields, no ignored parameters','INVALID_GEOMETRY')
    lengths=g['physical_lengths'];require(all(x>0 for x in lengths),'Positive physical lengths required','INVALID_GEOMETRY')
    measure=math.prod(lengths);require(math.isfinite(measure) and measure>0,'Physical cell area/volume must remain finite positive in float64','INVALID_GEOMETRY')
    if d==2:require(lengths[0]==lengths[1],'2D source builder requires a square cell','INVALID_GEOMETRY')
    if 'normalized_fraction' in g:require(0<g['normalized_fraction']<1,'Fraction strictly inside (0,1)','INVALID_GEOMETRY')
    if 'normalized_radius' in g:
        r=g['normalized_radius'];s=g.get('normalized_shell',0)
        require(0<r<(.4 if d==2 else .44) and r+s<(.45 if d==2 else .44),'Bounded resolved inclusion radius/shell required','INVALID_GEOMETRY')
    if 'normalized_axes' in g:require(min(g['normalized_axes'])>0,'Positive normalized axes required','INVALID_GEOMETRY')
    if k=='core_shell':require(g['normalized_shell']>0,'Positive shell required','INVALID_GEOMETRY')
    if k=='polycrystal':
        n=g['grain_count'];require(n in ([4,9,16,25,36] if d==2 else [8,12,16,20,27]),'Unsupported grain count','INVALID_GEOMETRY')
        if d==2:require(.01<=g['normalized_gb_width']<=.08,'2D GB source bounds .01..08','INVALID_GEOMETRY')
        else:require(g['normalized_gb_width']==0 and g['normalized_shell']==0,'3D GB/shell polycrystal is limited history only; not exposed in this release','UNSUPPORTED_GEOMETRY')
    thin=min([g[x] for x in ('normalized_shell','normalized_gb_width') if g.get(x,0)>0],default=1.)
    if k in ('polycrystal','core_shell'):require(h<=thin/(1.5 if d==2 else 1.2),'Under-resolved GB/shell: source target-elements-per-width guard','UNDER_RESOLVED_GEOMETRY')
    tags={'10'}
    if k in ('layers','rotated_layers','circle','ellipse','sphere','ellipsoid'):tags.add('20')
    if k=='core_shell':tags|={'20','30'}
    if k=='polycrystal':
        tags={str(100+i) for i in range(g['grain_count'])}
        if g['normalized_shell']>0:tags|={str(200+i) for i in range(g['grain_count'])}
        if g['normalized_gb_width']>0:tags.add('3000')
    if g['pore_fraction']>0:tags.add('9000')
    return tags

def canonicalize(raw,operation):
    require(operation in OPERATIONS,'Unsupported RVE operation','UNSUPPORTED_OPERATION')
    d,p=OPERATIONS[operation];validate_shape(raw,read_json(ROOT/f'schemas/{operation}.input.schema.json'))
    fields={f'/geometry/physical_lengths/{i}':{'kind':'length'} for i in range(d)}
    kind='relative_permittivity' if p=='electrostatics' else 'thermal_conductivity'
    assigned=[]
    for index,m in enumerate(raw['materials']):
        tag=m['region_tag'];assigned.append(tag)
        require(tag.isascii() and tag.isdigit() and str(int(tag))==tag,'Canonical numeric region tags required','INVALID_MATERIAL')
        expect={'region_tag','representation','applicability', 'scalar' if m['representation']=='isotropic' else 'tensor'}
        require(set(m)==expect and m['applicability'].strip(),'Exactly scalar or tensor and nonblank applicability required','INVALID_MATERIAL')
        if 'scalar' in m:fields[f'/materials/{index}/scalar']={'kind':kind}
        else:
            for i in range(d):
                for j in range(d):fields[f'/materials/{index}/tensor/{i}/{j}']={'kind':kind}
    require(len(set(assigned))==len(assigned),'Duplicate region assignments are forbidden','INVALID_MATERIAL')
    for pointer in fields:
        q=raw
        for key in pointer.strip('/').split('/'):q=q[int(key)] if isinstance(q,list) else q[key]
        require(q['source']['kind'].strip() not in ('','unspecified') and bool(q['source']['reference'].strip()),'Nonblank quantity source required: '+pointer,'INVALID_UNITS')
    if raw['geometry']['kind']=='polycrystal':
        fields['/geometry/grain_count']={'kind':'count'};fields['/geometry/seed']={'kind':'seed'}
    catalog=rpc('catalog');expected={'length':('length','m'),kind:('dimensionless','1') if p=='electrostatics' else ('thermal_conductivity','W/(m K)'),'count':('dimensionless','1'),'seed':('dimensionless','1')}
    for k,(dimension,unit) in expected.items():
        require(catalog['kinds'].get(k)=={'dimension':dimension,'canonical_unit':unit},'Shared kind semantics mismatch: '+k,'UNITS_CORE_FAILED')
        require(catalog['units'].get(unit,{}).get('dimension')==dimension,'Canonical unit missing from shared catalog: '+k,'UNITS_CORE_FAILED')
    require(isinstance(catalog.get('catalog_version'),str) and bool(catalog['catalog_version']),'Catalog version required','UNITS_CORE_FAILED')
    norm=rpc('normalize_fields',payload=raw,fields=fields);canonical=norm['payload'];expected_payload=deepcopy(raw)
    require(norm.get('core_version')=='1.0.0' and set(norm['records'])==set(fields),'Incomplete unit audit','UNITS_CORE_FAILED')
    for pointer,spec in fields.items():
        rec=norm['records'][pointer];a=raw;b=expected_payload
        keys=pointer.strip('/').split('/')
        for key in keys[:-1]:a=a[int(key)] if isinstance(a,list) else a[key];b=b[int(key)] if isinstance(b,list) else b[key]
        key=int(keys[-1]) if isinstance(b,list) else keys[-1]
        require(rec['schema_version']=='mlcc.quantity.v1' and rec['kind']==spec['kind'] and rec['dimension']==expected[spec['kind']][0] and rec['normalized']['unit']==expected[spec['kind']][1] and rec['original']['representation']==a[key] and rec['conversion']['core_version']=='1.0.0','Inconsistent unit record '+pointer,'UNITS_CORE_FAILED')
        require(catalog['units'].get(rec['conversion']['unit_key'],{}).get('dimension')==expected[spec['kind']][0],'Actual input unit missing/incompatible in shared catalog: '+pointer,'UNITS_CORE_FAILED')
        if isinstance(a[key],dict):require(rec['original']['source']==a[key]['source'],'Quantity source mismatch','UNITS_CORE_FAILED')
        v=rec['normalized']['value'];require(type(v) in (int,float) and math.isfinite(v),'Nonfinite normalized value','UNITS_CORE_FAILED');b[key]=v
    require(canonical==expected_payload,'Normalizer modified undeclared fields','UNITS_CORE_FAILED')
    canonical=deepcopy(canonical)
    canonical['materials']={m['region_tag']:{k:v for k,v in m.items() if k!='region_tag'} for m in canonical['materials']}
    tags=geometry(canonical['geometry'],canonical['normalized_h'],d)
    require(set(canonical['materials'])==tags,'All and only actual region tags require explicit materials: '+str(sorted(tags)),'INVALID_MATERIAL')
    require(p=='thermal' or canonical['pore_model']=='explicit','Electrostatic pores must remain explicit positive phase','UNSUPPORTED_PORE_MODEL')
    if canonical['pore_model']=='insulating_cavity':require(canonical['geometry']['pore_fraction']>0,'Cavity requires positive pore fraction','UNSUPPORTED_PORE_MODEL')
    for m in canonical['materials'].values():
        if 'scalar' in m:require(m['scalar']>0,'Positive scalar coefficient required','INVALID_MATERIAL')
        else:spd(m['tensor'],d)
    audit={'schema_version':'rve.unit-normalization.v1','core_version':norm['core_version'],'catalog_version':catalog['catalog_version'],'records':norm['records'],'field_map':fields,'material_rows':{str(i):tag for i,tag in enumerate(assigned)},'rule':'raw typed -> shared normalize_fields -> unique region-row mapping in canonical SI -> RVE geometry mapping; WSL never rescales raw units'}
    return canonical,audit

def kernel_input(c,d,p):
    g=c['geometry'];cfg={'kind':g['kind'],'pore_fraction':g['pore_fraction']}
    if d==2:cfg['length_m']=g['physical_lengths'][0]
    else:cfg['lengths_m']=g['physical_lengths']
    mapping={'normalized_fraction':'fraction','axis':'axis','normalized_radius':'radius','normalized_shell':'shell','normalized_aspect':'aspect','normalized_center':'center','normalized_axes':'axes','grain_count':'grains','seed':'seed','normalized_gb_width':'gb_width','jitter':'jitter'}
    for key,target in mapping.items():
        if key in g:cfg[target]=g[key]
    mats={tag:{'value':m.get('scalar',m.get('tensor')),'units':'1' if p=='electrostatics' else 'W/(m K)','source':dumps({'quantity_sources':m,'note':'canonical values; source references retained in unit audit'}),'applicability':m['applicability']} for tag,m in c['materials'].items()}
    return cfg,mats
