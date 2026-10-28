"""Deterministic formal protocol; preflight probes versions, never circuits."""
from pathlib import Path
import re
from .common import ROOT, require, read_json, write_json, validate, digest, file_hash, artifacts
from .contract import canonicalize
from .deployment import Deployment

LIMITS=['Synthetic/manual constant linear lumped RLC only; no product/material calibration.',
        'Finite pulse/recovery RMS is not periodic steady-state ripple.',
        'SI compatibility and structured quantities use the unique shared UNIT core; field semantics stay explicit.',
        'Keep source and host deployment fixed between queue and worker; public snapshot does not freeze their contents.']


def provenance(c=None, env=None, *, transport=None):
    return {'evidence_kind':'real_computation' if env else 'none', 'method':{'name':'Controlled series-RLC branches / native AC or Gear2 finite-pulse transient','version':'0.1.0'},
            'backend':{'name':'ngspice','version':env['backend_version'] if env else 'not_recorded'},
            'units':{'C':'F','R':'ohm','L':'H','frequency':'Hz','time':'s','voltage':'V','current':'A','power':'W','energy':'J','phase':'deg'},
            'conditions':{'canonical_input':c or {},'AC':'1 V normalized small-signal phasor; RMS convention for power only','current':'positive into DUT; signed capacitor delivery','transient':'baseline DC operating point, no UIC, finite PWL pulse, Gear2',**({'deployment_transport':'native_linux','adapter_host':'Linux','scientific_host':'native Linux'} if transport=='native_linux' else {})},
            'applicability':'Synthetic/manual constant linear RLC; material and device applicability not_checked',
            'sources':[{'kind':'code_provenance','reference':'modules/spice/SOURCES.json','description':'Read-only frozen prototype migration; task-native ngspice output, no experiment runtime imports'},
                       {'kind':'code_provenance','reference':'modules/spice/UNITS_SOURCES.json','description':'0.2.0 registration and shared-UNIT source fingerprints; physics kernels unchanged'}]}


def normalize(native,c,out,audit,*,transport=None):
    require(native.get('schema_version')=='spice.science-result.v1' and native.get('input_sha256')==digest(c), 'Native result identity mismatch', 'INVALID_SCIENTIFIC_RESULT')
    r=native['results'];validate(r,read_json(ROOT/'schemas/output.schema.json'))
    hashes=native['hashes']
    needed={'solver/circuit.cir','solver/output.raw','solver/ngspice.log','solver/execution.json','solver/parsed.csv','solver/metrics.json','environment.json','readback.json','curve.png','input.solver-si.json','summary.json','native_checks.json'}
    require(needed<=hashes.keys(), 'Required native evidence missing','INVALID_SCIENTIFIC_RESULT')
    for relative,h in hashes.items():
        require(isinstance(relative,str) and '\\' not in relative and ':' not in relative and not any(p in ('..','.') for p in relative.split('/')) and not relative.startswith('/'), 'Unsafe native artifact','INVALID_SCIENTIFIC_RESULT')
        p=out/relative
        require(p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(out.resolve()) and file_hash(p)==h,'Native evidence hash changed','INVALID_SCIENTIFIC_RESULT')
    require(read_json(out/'input.solver-si.json')==c and read_json(out/'summary.json')==r, 'Native input/summary drift','INVALID_SCIENTIFIC_RESULT')
    execution=read_json(out/'solver/execution.json');metrics=read_json(out/'solver/metrics.json');rb=read_json(out/'readback.json')
    require(execution['status']=='PASS' and execution['returncode']==0 and execution['points']==r['samples']==metrics['samples'] and rb['status']=='PASS' and rb['circuits']==1 and all(x['checks'] and all(v is True for v in x['checks'].values()) for x in rb['records'].values()),'Native completeness/readback failed','INVALID_SCIENTIFIC_RESULT')
    env=native['environment']; require(env['ready'] is True and env['backend_version']=='41' and read_json(out/'environment.json')==env,'Native environment mismatch','INVALID_SCIENTIFIC_RESULT')
    checks=native['checks'];require(checks==read_json(out/'native_checks.json'),'Native checks drift','INVALID_SCIENTIFIC_RESULT')
    quality={'numerical':checks+[{'id':'unit_admission','status':'not_checked' if audit['fixed_si_fields'] else 'passed','message':'Explicit SI domain admission and available shared-core audits retained; full UNIT pending catalog' if audit['fixed_si_fields'] else 'All fields through unique shared UNIT core'}],
             'scientific':[{'id':k,'status':'not_checked','message':message} for k,message in [('material_calibration','No measured/vendor calibration'),('device_applicability','No material/product owner applicability sign-off'),('periodic_steady_state','Only one finite pulse, no periodic steady-state qualification')]]}
    write_json(out/'quality.json',quality);write_json(out/'artifact_hashes.json',hashes)
    return {'schema_version':'mlcc.adapter-result.v1','execution_status':'succeeded','provenance':provenance(c,env,transport=transport),'results':r,'quality':quality,'errors':[],'warnings':[],'limitations':LIMITS,'artifacts':artifacts(out)}


def handle(q):
    pre=isinstance(q,dict) and q.get('action')=='preflight';out=None
    try:
        require(isinstance(q,dict) and set(q)=={'schema_version','interface_version','action','module_id','operation','input','task_id','artifact_dir'} and q['schema_version']=='mlcc.adapter-request.v1' and q['interface_version']=='1.0' and q['module_id']=='spice' and q['action'] in ('preflight','execute'), 'Invalid adapter envelope','INVALID_REQUEST')
        if pre:require(q['task_id'] is None and q['artifact_dir'] is None,'Preflight is task-free','INVALID_REQUEST')
        c,audit=canonicalize(q['input'],q['operation'])
        dep=Deployment.load();estimate=dep.budget(c,q['operation'])
        if pre:
            env=dep.probe()
            return {'schema_version':'mlcc.adapter-preflight.v1','ready':True,'errors':[],'warnings':LIMITS,
                    'checks':[{'id':'input','status':'passed','message':'Strict source/schema/domain, deterministic SI/UNIT admission'},
                              {'id':'budget','status':'passed','message':'Estimated samples='+str(estimate)+'; actual raw count/step enforced'},
                              {'id':'backend','status':'passed','message':str(env)}]}
        require(isinstance(q['task_id'],str) and re.fullmatch('task-[0-9a-f]{32}',q['task_id']), 'Runtime task ID required','INVALID_REQUEST')
        path=Path(q['artifact_dir']);expected=ROOT.parents[1]/'outputs/tasks'/q['task_id']/'artifacts'
        require(path.is_absolute() and path.is_dir() and not path.is_symlink() and path.resolve()==expected.resolve(), 'Bundle Runtime-owned artifact directory required','INVALID_REQUEST')
        out=path
        require(not (out/'native').exists(),'Native task exists; no restart','TASK_ALREADY_STARTED')
        write_json(out/'input.original.json',q['input']);write_json(out/'input.canonical-si.json',c);write_json(out/'unit_normalization.json',audit)
        write_json(out/'sources.json',read_json(ROOT/'SOURCES.json'))
        write_json(out/'unit_release.json',read_json(ROOT/'UNITS_SOURCES.json'))
        write_json(out/'numerical_protocol.json',read_json(ROOT/'cases/validation.json'))
        native=dep.execute(c,q['operation'],out,q['task_id'])
        return normalize(native,c,out,audit,transport=dep.config.get('transport'))
    except Exception as e:
        error={'code':getattr(e,'code','ADAPTER_ERROR'),'message':str(e)}
        if pre:return {'schema_version':'mlcc.adapter-preflight.v1','ready':False,'errors':[error],'warnings':[],'checks':[]}
        blocked=error['code'].startswith(('INVALID_','UNITS_','DEPLOYMENT_','UNSUPPORTED_')) or error['code'] in ('BACKEND_UNAVAILABLE','RESOURCE_LIMIT','TASK_ALREADY_STARTED')
        return {'schema_version':'mlcc.adapter-result.v1','execution_status':'blocked' if blocked else 'failed','provenance':provenance(), 'results':{},'quality':{'numerical':[],'scientific':[]},'errors':[error],'warnings':[],
                'limitations':LIMITS+(['Native WSL/ngspice termination UNKNOWN; reconcile before another task.'] if error['code']=='SCIENTIFIC_STATE_UNKNOWN' else []),'artifacts':artifacts(out)}
