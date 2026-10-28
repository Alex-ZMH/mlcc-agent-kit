"""Vector public protocol and native evidence admission; standard library only."""
from pathlib import Path
import re
from .common import ROOT, ModuleError, digest, read_json, write_json, file_hash, artifact_path
from .vector_input import prepare, require
from .vector_views import result_view
from .validation import shape
from .deployment import Deployment
from . import VERSION

LIMITS=[
    'Synthetic quartic full-vector LGD, scalar isotropic gradient and fixed voltage on all outer faces; no material calibration.',
    'Dynamic triangular single-domain trajectories are not measured or quasistatic material hysteresis/coercive fields.',
    '90-degree polarization walls have no implemented elastic/electrostrictive coupling; no validated ferroelastic claim.',
    'The c=6b analytic-wall benchmark has a neutral 180-degree splitting mode; no unique stable-wall inference.',
    'Raw CG1/DG0 displacement flux is not H(div)-conservative. Legacy scalar RT0 remains separately available.',
    'Reference scales create an explicit physical view, not a measured BaTiO3 model; 2D energy is J/m.',
    'Native-process state must be reconciled after timeout; no automatic resubmission or WSL/server fallback.'
]

def provenance(p=None,env=None,context=None,transport=None):
    return {'evidence_kind':'real_computation' if env else 'none',
            'method':{'name':'Full-vector quartic LGD/TDGL and self-consistent electrostatics; mixed CG1/BE/Newton/MUMPS','version':VERSION},
            'backend':{'name':'Native Linux DOLFINx' if transport=='native_linux' else 'WSL DOLFINx',
                       'version':env['versions']['fenics-dolfinx'] if env else 'unverified'},
            'units':{'solver_dimensionless':'dimensionless',**({'results_si':'explicit SI view; 2D energy J/m, 3D J'} if context else {})},
            'conditions':{'solver_input':p,'unit_mapping_sha256':digest(context) if context else None,
                          'deployment_transport':transport or 'wsl','qc_domain':'dimensionless'},
            'applicability':'; '.join(LIMITS[:4]),
            'sources':[{'kind':'code_provenance','reference':'modules/phase_field/VECTOR_SOURCES.json',
                        'description':'Frozen vector PoC migration plus shared Scientific Core primitives; this task has its own native readback'},
                       {'kind':'synthetic_test','reference':p['source']['reference'] if p else 'not_executed',
                        'description':'Input source and optional explicit uncalibrated reference scales'}]}

def handle(q):
    from .adapter_api import artifacts
    pre=isinstance(q,dict) and q.get('action')=='preflight';out=None
    try:
        require(isinstance(q,dict) and set(q)=={'schema_version','interface_version','action','module_id','operation','input','task_id','artifact_dir'} and q['schema_version']=='mlcc.adapter-request.v1' and q['interface_version']=='1.0' and q['module_id']=='phase_field' and q['action'] in ('preflight','execute'),'Invalid vector adapter envelope','INVALID_REQUEST')
        p,context=prepare(q['input'],q['operation'])
        if pre:require(q['task_id'] is None and q['artifact_dir'] is None,'Preflight cannot own task files','INVALID_REQUEST')
        dep=Deployment.load();budget=dep.check_resources(p,context)
        if pre:
            env=dep.probe()
            return {'schema_version':'mlcc.adapter-preflight.v1','ready':True,'errors':[],'warnings':LIMITS[:2],
                    'checks':[{'id':i,'status':'passed','message':m} for i,m in [
                        ('vector_input','Explicit dimension-matched vectors, coefficients, BC and waveform'),
                        ('unit_mapping','Unique shared UNIT and explicit scales' if context else 'Explicit dimensionless input'),
                        ('budget',str(budget)),('backend',str(env))]]}
        require(isinstance(q['task_id'],str) and re.fullmatch(r'task-[a-f0-9]{32}',q['task_id']), 'Runtime task ID required','INVALID_REQUEST')
        out=Path(q['artifact_dir'])
        require(out.is_absolute() and out.is_dir() and not out.is_symlink() and out.resolve()==(ROOT.parents[1]/'outputs/tasks'/q['task_id']/'artifacts').resolve(),'Existing Bundle-owned task artifact directory required','INVALID_REQUEST')
        require(not (out/'native').exists(),'Native task already started','TASK_ALREADY_STARTED')
        write_json(out/'input.original.json',q['input'])
        if context:
            write_json(out/'input.canonical-si.json',context['canonical_si'])
            write_json(out/'unit_normalization.json',context['normalization_report'])
        native=dep.execute(p,out,q['task_id'],unit_context=context)
        require(native['task_id']==q['task_id'] and native['input_sha256']==digest(p) and native.get('unit_mapping_sha256')==(digest(context) if context else None),'Native task/unit identity mismatch','INVALID_SCIENTIFIC_RESULT')
        require(native['status']=='succeeded','Native vector task failed','SCIENTIFIC_EXECUTION_FAILED')
        hashes=native['hashes']
        required={'artifacts/'+x for x in ('fields.npz','fields.vtu','fields.xdmf','fields.h5','history.json','nonlinear.json','metrics.json','summary.json','readback.json','environment.json','native_checks.json','scientific_core.json','input.solver-dimensionless.json')}
        require(required<=hashes.keys(),'Incomplete native vector evidence','INVALID_SCIENTIFIC_RESULT')
        for ref,h in hashes.items():require(file_hash(artifact_path(out,ref))==h,'Native artifact hash mismatch','INVALID_SCIENTIFIC_RESULT')
        result=native['results'];shape(result,read_json(ROOT/'schemas/vector.result.schema.json'),'vector_result')
        require(set(result['artifact_refs'])<=hashes.keys() and read_json(out/'input.solver-dimensionless.json')==p and read_json(out/'summary.json')==result,'Native summary/input/refs differ','INVALID_SCIENTIFIC_RESULT')
        history=read_json(out/'history.json');logs=read_json(out/'nonlinear.json');metrics=read_json(out/'metrics.json')
        expected=result_view(p,metrics,history,logs,context,result['artifact_refs'])
        require(expected==result,'Vector result reconstruction mismatch','INVALID_SCIENTIFIC_RESULT')
        checks=read_json(out/'native_checks.json');rb=read_json(out/'readback.json')
        require(checks==native['checks'] and checks and all(v is True for v in checks.values()) and rb['checks'] and all(v is True for v in rb['checks'].values()),'Independent native checks missing/failed','INVALID_SCIENTIFIC_RESULT')
        if context:
            require({'artifacts/si/'+x for x in ('fields_si.npz','fields_si.vtu','history_si.json','mapping.json','readback.json','fields_units.json')}<=hashes.keys(),'Missing complete physical view','INVALID_SCIENTIFIC_RESULT')
            require(read_json(out/'si/mapping.json')==context and read_json(out/'si/readback.json')['passed'] is True,'Physical view or mapping mismatch','INVALID_SCIENTIFIC_RESULT')
        qc={'numerical':[{'id':'vector_'+k,'status':'passed','message':'Frozen PoC criteria; native independent field/residual/voltage-work evidence retained'} for k in checks],
            'scientific':[{'id':k,'status':'not_checked','message':m} for k,m in (
                ('material_validity','Synthetic parameters/reference scales; no measured calibration'),
                ('stationary_stability','Newton convergence or finite-time evolution does not prove stable equilibrium'),
                ('electroelasticity','No elasticity or electrostriction'),
                ('general_multidomain_cycle','Controlled dynamic trajectories do not validate arbitrary multidomain hysteresis'))]}
        qc['numerical'] += [{'id':'unit_mapping','status':'passed' if context else 'not_applicable','message':'Unique shared UNIT; canonical SI converted once to reduced solver input; QC stays reduced'},
                            {'id':'mesh_convergence','status':'not_checked','message':'No task-specific mesh refinement'},
                            {'id':'time_convergence','status':'not_checked' if p['operation']=='vector_evolve' else 'not_applicable','message':'No task-specific time refinement'}]
        write_json(out/'quality.json',qc)
        return {'schema_version':'mlcc.adapter-result.v1','execution_status':'succeeded',
                'provenance':provenance(p,read_json(out/'environment.json'),context,dep.config.get('transport')),
                'results':result,'quality':qc,'errors':[],'warnings':native.get('warnings',[]),'limitations':LIMITS,'artifacts':artifacts(out)}
    except Exception as exc:
        code=getattr(exc,'code','ADAPTER_ERROR');errors=[{'code':code,'message':str(exc)}]
        if pre:return {'schema_version':'mlcc.adapter-preflight.v1','ready':False,'errors':errors,'warnings':[],'checks':[]}
        blocked=code.startswith(('INVALID_','UNIT_','DEPLOYMENT_')) or code in ('RESOURCE_LIMIT','BACKEND_UNAVAILABLE','TASK_ALREADY_STARTED')
        return {'schema_version':'mlcc.adapter-result.v1','execution_status':'blocked' if blocked else 'failed',
                'provenance':provenance(),'results':{},'quality':{'numerical':[],'scientific':[]},
                'errors':errors,'warnings':[],'limitations':LIMITS,'artifacts':artifacts(out)}
