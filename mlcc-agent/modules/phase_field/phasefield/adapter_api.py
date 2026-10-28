"""Public adapter normalization: independent host config, evidence and QC."""
from pathlib import Path
import re
from .common import ModuleError, digest, file_hash, read_json, write_json, artifact_path
from .validation import validate_input, validate_result
from .deployment import Deployment
from . import VERSION

LIMITS=['All scientific quantities dimensionless; scalar polarization (0,P,0), fixed profile/domain/coefficients.',
        'Newton convergence does not establish a stable minimum; finite evolution time does not establish equilibrium.',
        'RT0 is constrained postprocessing; raw CG1 flux is not locally strongly conservative.',
        'Deployment is host-controlled but not frozen by the public queued snapshot; keep it fixed until worker completes.',
        'Timeout/communication loss does not confirm Linux solver termination. Reconcile before any new submission.']


def check(i,s,m):return {'id':i,'status':s,'message':m}


def provenance(p=None,env=None,*,transport=None):
    return {'evidence_kind':'real_computation' if env else 'none',
            'method':{'name':'V0.3 scalar LGD P/phi CG1; Newton direct LU; TDGL backward Euler','version':VERSION},
            'backend':{'name':'Native Linux DOLFINx' if transport=='native_linux' else 'WSL DOLFINx','version':env['versions']['fenics-dolfinx'] if env else 'unverified'},
            'units':{k:'dimensionless' for k in ['P','phi','E','time','coordinates','epsilon','g','electric_enthalpy']},
            'conditions':p or {},'applicability':LIMITS[0],
            'sources':[{'kind':'validated_source','reference':'SOURCES.json','description':'V0.3 frozen-source fingerprint and adaptations; baseline PASS is not current task QC'}]}


def artifacts(directory):
    if directory is None or not Path(directory).is_dir():return []
    media={'.json':'application/json','.csv':'text/csv','.png':'image/png','.xdmf':'application/xml','.h5':'application/x-hdf5','.npz':'application/octet-stream','.log':'text/plain'}
    return [{'path':'artifacts/'+f.relative_to(directory).as_posix(),'media_type':media.get(f.suffix,'application/octet-stream'),'description':'Task-local native evidence: '+f.name}
            for f in sorted(Path(directory).rglob('*')) if f.is_file() and f.stat().st_size and not f.is_symlink() and '.cache' not in f.parts]


def normalize(native,p,directory,task_id,*,transport=None):
    if native.get('input_sha256')!=digest(p) or native.get('task_id')!=task_id:
        raise ModuleError('INVALID_SCIENTIFIC_RESULT','Task/input identity mismatch')
    if native.get('status')!='succeeded':raise ModuleError('SCIENTIFIC_EXECUTION_FAILED',str(native.get('message')))
    r=validate_result(native['results'],p)
    refs=set()
    for ref,h in native['hashes'].items():
        if file_hash(artifact_path(directory,ref))!=h:raise ModuleError('INVALID_SCIENTIFIC_RESULT','Artifact hash mismatch')
        refs.add(ref)
    required={'artifacts/fields.npz','artifacts/fields.xdmf','artifacts/fields.h5','artifacts/history.json','artifacts/nonlinear.json','artifacts/initial.json','artifacts/environment.json'}
    if p['output']['rt0']:required.add('artifacts/flux_reconstruction.npz')
    if not required<=refs or not set(r['artifact_refs'])<=refs:raise ModuleError('INVALID_SCIENTIFIC_RESULT','Missing native artifact manifest entries')
    history=read_json(Path(directory)/'history.json');logs=read_json(Path(directory)/'nonlinear.json')
    if not history or not logs:raise ModuleError('INVALID_SCIENTIFIC_RESULT','Missing history/nonlinear evidence')
    accepted=[x for x in logs if x.get('accepted',x['converged'])];rejected=[x for x in logs if not x.get('accepted',x['converged'])]
    if len(logs)!=r['time']['nonlinear_solves'] or len(rejected)!=r['time']['rejected_steps']:
        raise ModuleError('INVALID_SCIENTIFIC_RESULT','Nonlinear accounting mismatch')
    if not all(x['converged'] and x['reason']>0 and x['residual']<1e-8 for x in accepted):
        raise ModuleError('INVALID_SCIENTIFIC_RESULT','Accepted nonlinear convergence missing')
    if abs(history[-1]['potential']-r['electric_enthalpy'])>1e-12 or history[-1]['t']!=r['time']['completed']:
        raise ModuleError('INVALID_SCIENTIFIC_RESULT','History summary mismatch')
    if p['operation']=='evolve' and (len(history)!=len(accepted)+1 or r['time']['accepted_steps']!=len(accepted) or any(b['t']<=a['t'] for a,b in zip(history,history[1:]))):
        raise ModuleError('INVALID_SCIENTIFIC_RESULT','Accepted trajectory mismatch')
    g=r['gauss'];energy=max([b['potential']-a['potential'] for a,b in zip(history,history[1:])],default=0.)
    # Numerical tolerances inherited only for this identical dimensionless model and source-free path.
    qc={'numerical':[
        check('nonlinear_accepted','passed','All accepted solves have positive SNES reason and residual <1e-8; rejected attempts retained separately.'),
        check('finite_fields','passed','Native P/phi/E arrays and histories finite; JSON forbids nonfinite values.'),
        check('completed_time','passed' if p['operation']=='evolve' else 'not_applicable','Evolution end reached' if p['operation']=='evolve' else 'Stationary solve has no transient end requirement.'),
        check('rollback',('passed' if all(x.get('rollback_exact') for x in rejected) else 'failed') if rejected else 'not_applicable','Rejected attempts retain rollback diagnostics; no failed trial submitted to history.'),
        check('native_readback','passed','XDMF/HDF5/NPZ topology, P/phi histories and E read back and compared.'),
        check('gauss_weak','passed' if g['free_weak_residual_l2']<1e-8 else 'failed','Original weak Gauss residual; V0.3 worker 1e-8 numerical criterion.'),
        check('voltage_bc','passed' if g['voltage_boundary_error']<1e-12 else 'failed','V0.3 fixed voltage boundary criterion 1e-12.'),
        check('energy_nonincrease',('passed' if energy<1e-8 else 'failed') if p['operation']=='evolve' else 'not_applicable','Source-free accepted BE history only; V0.3 absolute increment 1e-8; stationary Newton is not a descent path.'),
        check('rt0',('passed' if max(g['rt0_divergence_rms'],g['rt0_interior_normal_jump_rms'],g['rt0_side_normal_rms'],abs(g['rt0_flux_source_imbalance']))<1e-8 else 'failed') if p['output']['rt0'] else 'not_checked','V0.3 physical reconstruction 1e-8 checks only; correction and raw weak/flux evidence retained.'),
        check('mesh_convergence','not_checked','No task-specific refinement study.'),check('time_convergence','not_checked' if p['operation']=='evolve' else 'not_applicable','No task-specific time refinement.')],
        'scientific':[check('material_validity','not_checked','No material calibration or SI mapping.'),check('independent_reference','not_checked','No physical experiment reference.'),check('stationary_stability','not_checked','No Hessian/stability test; evolution end is not proof of equilibrium.')]}
    write_json(Path(directory)/'quality.json',qc)
    return {'schema_version':'mlcc.adapter-result.v1','execution_status':'succeeded','provenance':provenance(p,r['environment'],transport=transport),'results':r,'quality':qc,'errors':[],
            'warnings':native.get('warnings',[]),'limitations':LIMITS,'artifacts':artifacts(directory)}


def handle(q):
    if isinstance(q,dict) and q.get('operation') in ('dielectric_tangent','dielectric_tangent_si'):
        from .tangent_adapter import handle as tangent_handle
        return tangent_handle(q)
    if isinstance(q,dict) and isinstance(q.get('operation'),str) and q['operation'].startswith('vector_'):
        from .vector_adapter import handle as vector_handle
        return vector_handle(q)
    pre=isinstance(q,dict) and q.get('action')=='preflight';directory=None
    try:
        if not isinstance(q,dict) or set(q)!={'schema_version','interface_version','action','module_id','operation','input','task_id','artifact_dir'} or q['schema_version']!='mlcc.adapter-request.v1' or q['interface_version']!='1.0' or q['module_id']!='phase_field' or q['action'] not in ('preflight','execute'):
            raise ModuleError('INVALID_REQUEST','Invalid public request')
        context=None
        if q['operation'] in ('steady_si','evolve_si'):
            from .si_input import prepare_si
            p,context=prepare_si(q['input'],q['operation'])
        else:p=validate_input(q['input'],q['operation'])
        if pre and (q['task_id'] is not None or q['artifact_dir'] is not None):raise ModuleError('INVALID_REQUEST','Preflight is task-free')
        d=Deployment.load();cells=d.check_resources(p,context)
        if pre:
            env=d.probe()
            return {'schema_version':'mlcc.adapter-preflight.v1','ready':True,'errors':[],
                    'warnings':['SI input and physical result view use explicit scales; kernel and numerical QC remain dimensionless. No material calibration is inferred.'] if context else LIMITS[:1],
                    'checks':[check('input','passed','Explicit profile and initial data validated'),check('unit_mapping','passed' if context else 'not_applicable','Public units core 1.0.0 -> canonical SI -> explicit scales -> legacy dimensionless input' if context else 'Legacy dimensionless input remains dimensionless'),check('budget','passed',f'cells={cells}; history/work/RT estimates within host limits'),check('environment','passed',str(env))]}
        if not isinstance(q['task_id'],str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,95}',q['task_id']):raise ModuleError('INVALID_REQUEST','Invalid task id')
        directory=Path(q['artifact_dir'])
        if not directory.is_absolute() or directory.is_symlink():raise ModuleError('INVALID_REQUEST','Absolute runtime artifact directory required')
        native=d.execute(p,directory,q['task_id'],unit_context=context)
        result=normalize(native,p,directory,q['task_id'],transport=d.config.get('transport'))
        if context:
            from .si_input import si_result
            from .validation import shape
            if native.get('original_input_sha256')!=digest(q['input']) or native.get('unit_mapping_sha256')!=digest(context):
                raise ModuleError('INVALID_SCIENTIFIC_RESULT','Original SI task input or mapping identity mismatch')
            saved=read_json(directory/'si/summary.json');mapped=si_result(result['results'],context)
            if saved!=mapped['results_si'] or not read_json(directory/'si/readback.json').get('passed'):
                raise ModuleError('INVALID_SCIENTIFIC_RESULT','SI result mapping/readback mismatch')
            required={'artifacts/si/fields_si.npz','artifacts/si/summary.json','artifacts/si/mapping.json','artifacts/si/history_si.json','artifacts/si/fields_units.json','artifacts/si/readback.json'}
            if not required<=set(native['hashes']):raise ModuleError('INVALID_SCIENTIFIC_RESULT','Missing SI mapped evidence')
            shape(mapped,read_json(Path(__file__).resolve().parents[1]/'schemas/si.result.schema.json'),'result_si')
            result['results']=mapped
            result['quality']['numerical'].append(check('unit_mapping','passed','Explicit original -> public canonical SI -> reduced input; physical array readback; all solver QC remains dimensionless.'))
            for c in result['quality']['scientific']:
                if c['id']=='material_validity':c['message']='Explicit SI reference scales are provided, but not independently calibrated or validated for a material.'
            result['provenance']['conditions']={'original_input':q['input'],'canonical_si':context['canonical_si'],'solver_dimensionless_input':p,'unit_mapping_sha256':digest(context),'qc_domain':'dimensionless'}
            result['provenance']['units']={f'results.results_si.fields.{k}':saved['units'][k] for k in ('P','phi','E_magnitude','P_gradient_rms')}
            result['provenance']['units'].update({'results.results_si.fixed_domain_m':'m','results.results_si.completed_time':'s','results.results_si.centerline_unique_wall_x':'m','results.results_si.electric_enthalpy':saved['units']['electric_enthalpy']})
            result['provenance']['units']['results.solver_dimensionless']='dimensionless'
            result['provenance']['applicability']='Explicit SI view of constrained scalar LGD family; reference scales are not independently material-calibrated.'
            result['limitations']=list(result['limitations'])
            result['limitations'][0]='SI view requires explicit uncalibrated reference scales; constrained scalar LGD family. Original solver evidence/QC is dimensionless; 2D energy is J/m.'
            for name,value in [('original_input',context['original_input']),('normalized_input',context['canonical_si']),
                               ('normalization_report',context['normalization_report']),('solver_input',p),('reference_scales',context['derived'])]:
                write_json(directory/'si'/f'{name}.json',value)
            # quality.json from normalize is the dimensionless source; SI checks are a separate artifact.
            write_json(directory/'si/quality.json',result['quality']);result['artifacts']=artifacts(directory)
            result['results']['artifact_refs']=sorted({x['path'] for x in result['artifacts'] if x['path'].startswith('artifacts/si/')}|set(result['results']['artifact_refs']))
        if d.config.get('transport')=='native_linux': result['provenance']['conditions']=dict(result['provenance']['conditions'],deployment_transport='native_linux')
        return result
    except Exception as e:
        code=getattr(e,'code','ADAPTER_ERROR');errors=[{'code':code,'message':str(e)}]
        if pre:return {'schema_version':'mlcc.adapter-preflight.v1','ready':False,'errors':errors,'warnings':[],'checks':[]}
        return {'schema_version':'mlcc.adapter-result.v1','execution_status':'blocked' if code in ('INVALID_INPUT','INVALID_REQUEST','RESOURCE_LIMIT','DEPLOYMENT_NOT_CONFIGURED','INVALID_DEPLOYMENT','BACKEND_UNAVAILABLE','TASK_ALREADY_STARTED','UNSUPPORTED_OPERATION','INVALID_UNITS','INVALID_SCALES','UNIT_CORE_UNAVAILABLE','UNIT_CORE_INCOMPATIBLE') else 'failed',
                'provenance':provenance(),'results':{},'quality':{'numerical':[],'scientific':[]},'errors':errors,'warnings':[],'limitations':LIMITS,'artifacts':artifacts(directory)}
