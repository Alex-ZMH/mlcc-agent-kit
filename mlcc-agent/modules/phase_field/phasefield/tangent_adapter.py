"""Deterministic tangent preflight and native-evidence admission; stdlib only."""
from pathlib import Path
import re
from .common import ROOT,read_json,write_json,digest,file_hash,artifact_path
from .tangent_input import prepare
from .tangent_views import result_view
from .vector_input import require
from .validation import shape
from .deployment import Deployment
from . import VERSION
LIMITS=[
 'Static branch-local derivative d< D >/dEbar; full 2x2 or 3x3 tensor, not dynamic P-E slope or relative permittivity.',
 'Synthetic vector quartic LGD; no material calibration, finite-frequency complex dielectric or elasticity.',
 'Uniform branch response and finite fixed-end wall apparent response are distinct; wall size/end constraints affect the latter.',
 'Unstable, near-singular or unequilibrated states do not export a valid relaxed tangent; no BE regularization or internal pinning.',
 'SI tensor is absolute F/m via explicit P0/E0; no implicit vacuum permittivity or automatic RVE transfer.',
 'QC remains dimensionless; point-specific mesh convergence and real material applicability are not_checked.',
 'Timeout does not prove external process termination; no automatic resubmission or backend fallback.'
]
def provenance(p=None,env=None,context=None,transport=None):
    return {'evidence_kind':'real_computation' if env else 'none',
        'method':{'name':'Static full-coupled UFL AD Jacobian, multi-RHS LU sensitivity and independent saved-simplex readback','version':VERSION},
        'backend':{'name':'Native Linux DOLFINx' if transport=='native_linux' else 'WSL DOLFINx','version':env['versions']['fenics-dolfinx'] if env else 'unverified'},
        'units':{'solver_tensor':'dimensionless absolute D/E','physical_tensor':'F/m' if context else 'not produced'},
        'conditions':{'solver_input':p,'unit_mapping_sha256':digest(context) if context else None,'qc_domain':'dimensionless','deployment_transport':transport or 'wsl'},
        'applicability':'; '.join(LIMITS[:4]),
        'sources':[{'kind':'code_provenance','reference':'modules/phase_field/TANGENT_SOURCES.json','description':'Reviewed tangent experiment migration and existing vector/Core consumption'},
                   {'kind':'synthetic_test','reference':p['source']['reference'] if p else 'not_executed','description':'Explicit synthetic or manual parameters, not material calibration'}]}
def handle(q):
    from .adapter_api import artifacts
    pre=isinstance(q,dict) and q.get('action')=='preflight';out=None;p=None;env=None;context=None;transport=None
    try:
        require(isinstance(q,dict) and set(q)=={'schema_version','interface_version','action','module_id','operation','input','task_id','artifact_dir'} and q['schema_version']=='mlcc.adapter-request.v1' and q['interface_version']=='1.0' and q['module_id']=='phase_field' and q['action'] in ('preflight','execute'),'Invalid tangent adapter envelope','INVALID_REQUEST')
        p,context=prepare(q['input'],q['operation']);dep=Deployment.load();budget=dep.check_resources(p,context);transport=dep.config.get('transport')
        if pre:
            require(q['task_id'] is None and q['artifact_dir'] is None,'Preflight must not own task files','INVALID_REQUEST');env=dep.probe()
            return {'schema_version':'mlcc.adapter-preflight.v1','ready':True,'errors':[],'warnings':LIMITS[:3],
                'checks':[{'id':k,'status':'passed','message':v} for k,v in [('tangent_input','Explicit static bias path and selected independent checks'),('unit_mapping','Shared UNIT and four scales' if context else 'Explicit dimensionless input'),('budget',str(budget)),('backend',str(env))]]}
        require(isinstance(q['task_id'],str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}',q['task_id']),'Runtime task identity required','INVALID_REQUEST')
        out=Path(q['artifact_dir']);require(out.is_absolute() and out.is_dir() and not out.is_symlink() and out.resolve()==(ROOT.parents[1].parent/'artifacts').resolve(),'Existing Bundle-owned task artifacts required','INVALID_REQUEST')
        require(not (out/'native').exists(),'Scientific task already started','TASK_ALREADY_STARTED');write_json(out/'input.original.json',q['input'])
        if context:
            write_json(out/'input.canonical-si.json',context['canonical_si']);write_json(out/'unit_normalization.json',context['normalization_report'])
        native=dep.execute(p,out,q['task_id'],unit_context=context);env=read_json(out/'environment.json')
        require(native['task_id']==q['task_id'] and native['input_sha256']==digest(p),'Native task/input mismatch','INVALID_SCIENTIFIC_RESULT')
        if native['status']=='rejected':
            rejected=read_json(out/'material_responses.json');require(rejected['count']==0 and rejected['responses']==[],'Rejected state exported a response','INVALID_SCIENTIFIC_RESULT')
            return {'schema_version':'mlcc.adapter-result.v1','execution_status':'failed','provenance':provenance(p,env,context,transport),'results':{},
                'quality':{'numerical':[{'id':'tangent_admissible','status':'failed','message':native['reason']}],
                           'scientific':[{'id':'material_validity','status':'not_checked','message':'No valid local response or material validation'}]},
                'errors':[{'code':'TANGENT_NOT_VALID','message':native['reason']}],'warnings':[],'limitations':LIMITS,'artifacts':artifacts(out)}
        require(native['status']=='succeeded' and native.get('unit_mapping_sha256')==(digest(context) if context else None),'Native result/mapping not accepted','INVALID_SCIENTIFIC_RESULT')
        hashes=native['hashes'];required={'artifacts/'+p for p in ['summary.json','input.solver-dimensionless.json','response.dimensionless.json','material_responses.json','readback.json','native_checks.json','scientific_core.json','environment.json','equilibrium/fields.npz','equilibrium/fields.vtu','equilibrium/fields.xdmf','equilibrium/fields.h5','equilibrium/tensor.json','equilibrium/frozen_sensitivities.npz']}
        require(required<=hashes.keys(),'Incomplete tangent native evidence','INVALID_SCIENTIFIC_RESULT')
        for ref,h in hashes.items():require(file_hash(artifact_path(out,ref))==h,'Native artifact hash mismatch','INVALID_SCIENTIFIC_RESULT')
        result=native['results'];shape(result,read_json(ROOT/'schemas/tangent.result.schema.json'))
        require(set(result['artifact_refs'])<=hashes.keys() and read_json(out/'summary.json')==result and read_json(out/'input.solver-dimensionless.json')==p,'Input/summary/ref mismatch','INVALID_SCIENTIFIC_RESULT')
        response=read_json(out/'response.dimensionless.json');require(read_json(out/'material_responses.json')['responses']==[response],'Response bundle mismatch','INVALID_SCIENTIFIC_RESULT')
        require(result_view(p,response,context,result['artifact_refs'])==result,'Tensor/unit summary reconstruction mismatch','INVALID_SCIENTIFIC_RESULT')
        checks=read_json(out/'native_checks.json');rb=read_json(out/'readback.json')
        require(checks==native['checks'] and checks and all(v is True for v in checks.values()) and rb['status']=='PASS' and rb['results'],'Missing/failed native checks','INVALID_SCIENTIFIC_RESULT')
        require(all(row['status']=='PASS' and row['checks'] and all(v is True for v in row['checks'].values()) for row in rb['results'].values()),'Independent tangent readback failed','INVALID_SCIENTIFIC_RESULT')
        if context:
            require({'artifacts/si/'+x for x in ['fields_si.npz','fields_si.vtu','mapping.json','readback.json','fields_units.json']}<=hashes.keys(),'Incomplete physical view','INVALID_SCIENTIFIC_RESULT')
            require(read_json(out/'si/mapping.json')==context and read_json(out/'si/readback.json')['passed'] is True,'SI map/roundtrip failed','INVALID_SCIENTIFIC_RESULT')
        qc={'numerical':[{'id':'tangent_'+k,'status':'passed','message':'Reviewed AD/static protocol and new native evidence'} for k in checks],
            'scientific':[{'id':'material_validity','status':'not_checked','message':'Synthetic parameters/scales; no material calibration'},
                          {'id':'general_multidomain_constitutive','status':'not_checked','message':'Finite fixed-end specimen response is not a universal material law'},
                          {'id':'finite_frequency_or_elasticity','status':'not_checked','message':'No complex-frequency or electroelastic model'}]}
        qc['numerical'] += [{'id':'tangent_admissible','status':'passed','message':'Static center and positive reduced-energy Hessian under stated constraints'},
            {'id':'fd_validation','status':'passed' if p['verification']['finite_difference'] else 'not_checked','message':'New independent +/- solves and returns to saved center' if p['verification']['finite_difference'] else 'Not requested for this task; historical FD not relabelled'},
            {'id':'analytic_reference','status':'passed' if p['verification']['analytical'] else 'not_checked','message':'Independent uniform Hessian benchmark only when requested'},
            {'id':'unit_mapping','status':'passed' if context else 'not_applicable','message':'Absolute F/m mapping; no implicit relative epsilon'},
            {'id':'mesh_convergence','status':'not_checked','message':'No point-specific mesh series'}]
        write_json(out/'quality.json',qc)
        return {'schema_version':'mlcc.adapter-result.v1','execution_status':'succeeded','provenance':provenance(p,env,context,transport),
                'results':result,'quality':qc,'errors':[],'warnings':[],'limitations':LIMITS,'artifacts':artifacts(out)}
    except Exception as exc:
        code=getattr(exc,'code','ADAPTER_ERROR');errors=[{'code':code,'message':str(exc)}]
        if pre:return {'schema_version':'mlcc.adapter-preflight.v1','ready':False,'errors':errors,'warnings':[],'checks':[]}
        blocked=code.startswith(('INVALID_','UNIT_','DEPLOYMENT_')) or code in ('RESOURCE_LIMIT','BACKEND_UNAVAILABLE','TASK_ALREADY_STARTED')
        return {'schema_version':'mlcc.adapter-result.v1','execution_status':'blocked' if blocked else 'failed','provenance':provenance(p,env,context,transport),
                'results':{},'quality':{'numerical':[],'scientific':[]},'errors':errors,'warnings':[],'limitations':LIMITS,'artifacts':artifacts(out)}
