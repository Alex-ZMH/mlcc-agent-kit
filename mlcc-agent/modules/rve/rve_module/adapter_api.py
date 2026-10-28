"""Public single-request adapter: admission, waiting, native evidence validation."""
import math
from pathlib import Path
import re
from .common import ROOT,ModuleError,validate_shape,read_json,write_json,digest,file_hash,artifact_path
from .contract import OPERATIONS,canonicalize,require,spd
from .deployment import Deployment

LIMITATIONS=['Synthetic static linear materials, no calibrated BaTiO3/device prediction.','Single run mesh convergence and statistical representativity not_checked.','Raw DG0 flux is diagnostic, not pointwise strong conservation.','3D complex GB/shell polycrystal not publicly exposed.','Host deployment is not frozen by public queued snapshot; keep bindings/config fixed until worker completes.']
def check(i,status,msg):return {'id':i,'status':status,'message':msg}
def provenance(c=None,env=None,*,transport=None):
    return {'evidence_kind':'real_computation' if env else 'none','method':{'name':'P1 periodic equivalence-class constrained linear elliptic RVE','version':'0.1.1'},'backend':{'name':'DOLFINx/PETSc/Gmsh','version':env['versions']['dolfinx'] if env else 'not_recorded'},'units':{'tensor':'F/m or W/(m K), operation-specific','field_coordinates':'m'},'conditions':{'canonical_input':c or {},'macro_basis':'eye(d): E [V/m] or negative grad(T) [K/m]','thermal_reference_K':300,'mpi_ranks':1,'windows_adapter':not (transport=='native_linux'),'WSL_science_only':not (transport=='native_linux')},'applicability':'Synthetic linear static RVE; material/device applicability not_checked','sources':[{'kind':'code_provenance','reference':'modules/rve/SOURCES.json','description':'Migrated dimension-specific kernels with source SHA256; no experiment imports'}]}
def diagnostics(out):
    if out is None:return []
    result=[]
    for p in Path(out).rglob('*'):
        rel=p.relative_to(out)
        if not p.is_file() or p.is_symlink() or not p.stat().st_size or 'cache' in rel.parts:continue
        result.append({'path':'artifacts/'+rel.as_posix(),'media_type':'application/json' if p.suffix=='.json' else 'application/octet-stream','description':'Preserved task evidence / partial failure diagnostics'})
    return result

def normalize(native,c,op,out,audit,*,transport=None):
    require(native.get('schema_version')=='rve.science-result.v1' and native.get('status')=='succeeded' and native.get('input_sha256')==digest(c),'Native response identity mismatch','INVALID_SCIENTIFIC_RESULT')
    r=native['results'];d,p=OPERATIONS[op];validate_shape(r,read_json(ROOT/f'schemas/{op}.output.schema.json'));spd(r['tensor'],d)
    require(r['boundary_condition']==c['boundary_condition'] and r['pore_model']==c['pore_model'],'Result conditions drift','INVALID_SCIENTIFIC_RESULT')
    hashes={}
    for a in native['artifacts']:
        path=artifact_path(out,a['path']);require(a['path'] not in hashes and file_hash(path)==a['sha256'],'Duplicate or changed native artifact','INVALID_SCIENTIFIC_RESULT');hashes[a['path']]=a['sha256']
    needed={r[k] for k in ('effective_material_artifact','readback_artifact','coordinate_artifact')}|set(r['load_fields'])|{'artifacts/geometry/mesh_identity.npz','artifacts/geometry/mesh_metrics.json','artifacts/geometry/periodic_CAD.json','artifacts/metrics.json','artifacts/diagnostics.json','artifacts/input.kernel-normalized.json'}
    require(needed<=hashes.keys(),'Missing required native evidence','INVALID_SCIENTIFIC_RESULT')
    require(read_json(Path(out)/'metrics.json')==r and read_json(Path(out)/'diagnostics.json')==native['diagnostics'],'Native metrics mismatch','INVALID_SCIENTIFIC_RESULT')
    e=read_json(Path(out)/'effective_material.json');validate_shape(e,read_json(ROOT/f'schemas/effective-material-{d}d-{p}.schema.json'))
    require(e['tensor']==r['tensor'] and e['rve_id']==r['rve_id'] and e['mesh_id']==r['mesh_id'] and e['materials']==c['materials'],'Effective material mismatch','INVALID_SCIENTIFIC_RESULT')
    require(set(e['region_mapping'])==set(c['materials'])==set(e['phase_fractions'])==set(e['material_sources']) and all(e['material_sources'].values()) and e['source_audit_artifact']=='artifacts/unit_normalization.json','Effective region/source coverage mismatch','INVALID_SCIENTIFIC_RESULT')
    rb=read_json(Path(out)/'readback.json');require(set(rb)==set('xyz'[:d]) and all(x['status']=='PASS' and x['checks'] and all(v is True for v in x['checks'].values()) for x in rb.values()),'Native readback failed','INVALID_SCIENTIFIC_RESULT')
    diag=native['diagnostics'];require(diag['verification']['checks'] and all(v is True for v in diag['verification']['checks'].values()) and len(diag['loads'])==d,'Native numerical checks failed','INVALID_SCIENTIFIC_RESULT')
    require(diag['mesh']['cells']==r['cells'] and all(type(row['solver']['reason']) is int and row['solver']['reason']>0 for row in diag['loads']),'Missing mesh/solver evidence','INVALID_SCIENTIFIC_RESULT')
    env=native['environment'];require(env['ready'] and env['versions']['dolfinx']=='0.11.0' and env['scalar_type']=='float64' and env['mpi_ranks']==1,'Native environment incompatible','INVALID_SCIENTIFIC_RESULT')
    qc={'numerical':[check(k,'not_applicable' if k=='PBC_pairing' and c['boundary_condition']!='periodic' else 'passed','Migrated numerical protocol; raw errors in diagnostics.json') for k in diag['verification']['checks']]+[check('mesh_geometry','passed','Positive nonempty mesh, region/CAD fraction audit retained'),check('linear_solver','passed','All independent basis loads converged'),check('native_readback','passed','Independent VTU/HDF5 gradients, constitutive law, flux/work, lifting and saved PBC pairs'),check('unit_normalization','passed','Shared core '+audit['core_version']+' catalog '+audit['catalog_version']),check('mesh_convergence','not_checked','Single run; historical selected grid studies not generalized')], 'scientific':[check(k,'not_checked',msg) for k,msg in [('material_calibration','Sources retained; synthetic values not measured calibration'),('statistical_representativity','No representative-volume statistical acceptance'),('device_applicability','No real material/product owner sign-off')]]}
    write_json(Path(out)/'quality.json',qc);write_json(Path(out)/'artifact_hashes.json',hashes)
    return {'schema_version':'mlcc.adapter-result.v1','execution_status':'succeeded','provenance':provenance(c,env,transport=transport),'results':r,'quality':qc,'errors':[],'warnings':[],'limitations':LIMITATIONS,'artifacts':diagnostics(out)}

def handle(q):
    pre=isinstance(q,dict) and q.get('action')=='preflight';out=None;c=None
    try:
        require(isinstance(q,dict) and set(q)=={'schema_version','interface_version','action','module_id','operation','input','task_id','artifact_dir'} and q['schema_version']=='mlcc.adapter-request.v1' and q['interface_version']=='1.0' and q['module_id']=='rve' and q['action'] in ('preflight','execute'),'Invalid adapter envelope','INVALID_REQUEST')
        c,audit=canonicalize(q['input'],q['operation']);d,p=OPERATIONS[q['operation']]
        if pre:require(q['task_id'] is None and q['artifact_dir'] is None,'Preflight cannot create a task','INVALID_REQUEST')
        dep=Deployment.load();estimate=dep.budget(c,d)
        if pre:
            env=dep.probe();return {'schema_version':'mlcc.adapter-preflight.v1','ready':True,'errors':[],'warnings':LIMITATIONS[:2],'checks':[check('typed_input','passed','Strict quantities, geometry, coverage and SPD; shared UNIT only'),check('budget','passed',f'Planning estimate={estimate}; actual mesh guard before solve'),check('backend','passed',str(env))]}
        require(isinstance(q['task_id'],str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}',q['task_id']) is not None,'Runtime task ID required','INVALID_REQUEST')
        path=Path(q['artifact_dir']);require(path.is_absolute() and path.is_dir() and not path.is_symlink(),'Runtime-owned absolute artifact directory required','INVALID_REQUEST');out=path
        require(path.resolve()==(ROOT.parents[1].parent/'artifacts').resolve(),'Artifact directory must belong to this Bundle runtime task','INVALID_REQUEST')
        require(not (out/'native').exists(),'Native task already started','TASK_ALREADY_STARTED')
        write_json(out/'input.original.json',q['input']);write_json(out/'input.canonical-si.json',c);write_json(out/'unit_normalization.json',audit)
        write_json(out/'sources.json',read_json(ROOT/'SOURCES.json'));write_json(out/'numerical_protocol.json',read_json(ROOT/'protocols'/('validation_protocol.json' if d==2 else 'numerical_protocol.json')))
        native=dep.execute(c,q['operation'],out,q['task_id']);return normalize(native,c,q['operation'],out,audit,transport=dep.config.get('transport'))
    except Exception as e:
        error={'code':getattr(e,'code','ADAPTER_ERROR'),'message':str(e)}
        if pre:return {'schema_version':'mlcc.adapter-preflight.v1','ready':False,'errors':[error],'warnings':[],'checks':[]}
        code=error['code'];blocked=code.startswith(('INVALID_','UNITS_','UNSUPPORTED_','UNDER_RESOLVED_','DEPLOYMENT_')) or code in ('BACKEND_UNAVAILABLE','RESOURCE_LIMIT','TASK_ALREADY_STARTED')
        return {'schema_version':'mlcc.adapter-result.v1','execution_status':'blocked' if blocked else 'failed','provenance':provenance(),'results':{},'quality':{'numerical':[],'scientific':[]},'errors':[error],'warnings':[],'limitations':LIMITATIONS+(['WSL native process termination unknown; manual reconciliation required.'] if code=='SCIENTIFIC_STATE_UNKNOWN' else []),'artifacts':diagnostics(out)}
