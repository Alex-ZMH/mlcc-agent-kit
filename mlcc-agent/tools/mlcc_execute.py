"""Execute one adapter in an existing allocation. No queue, Store or worker."""
import argparse
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == 'tools' else Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'src'))
from mlcc import contracts
from mlcc.module_contracts import ModuleContracts
from mlcc.adapter_transport import invoke

ENVIRONMENT={'fem':'MLCC_FEA_DEPLOYMENT','phase_field':'MLCC_PHASE_FIELD_DEPLOYMENT',
             'rve':'MLCC_RVE_DEPLOYMENT','spice':'MLCC_SPICE_DEPLOYMENT'}

def quality(checks, required):
    checks=list(checks)
    ids=[c['id'] for c in checks]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate quality checks')
    checks += [{'id':name,'status':'not_checked','message':'Required check not reported'} for name in required if name not in ids]
    states={c['status'] for c in checks}
    status=next((s for s in ('failed','warning','not_checked','passed') if s in states),'not_checked')
    return {'status':status,'checks':checks}

def execute(request_path,response_path):
    request_path,response_path=Path(request_path).resolve(),Path(response_path).resolve()
    q=contracts.read_json(request_path)
    if q['schema']!='mlcc.scale-execution-request.v1' or q['module_id'] not in ENVIRONMENT: raise ValueError('Unsupported request')
    job=os.environ.get('SLURM_JOB_ID')
    if not job: raise ValueError('An explicit Slurm allocation is required')
    if response_path.exists():
        saved=contracts.read_json(response_path)
        r=saved['result']
        if (saved['platform_task_id']!=q['platform_task_id'] or saved['scheduler_job_id']!=job
            or r['operation']!=q['operation'] or r['module']['id']!=q['module_id']
            or r['module']['version']!=q['module_version'] or r['input']['payload']!=q['input']):
            raise ValueError('Saved response differs; reconcile before any execution')
        return saved
    with (request_path.parent/'scale-execution.claim').open('x') as stream: stream.write(job+'\n')
    # The staged release is the task directory: payload code and sibling artifacts.
    # Native mapping remains confined to this one explicitly allocated task.
    deployment=dict(q['deployment'],linux_root=str(request_path.parent))
    if deployment.get('transport')!='native_linux': raise ValueError('Explicit native Linux deployment required')
    deployment_path=ROOT/'host-deployment.json'
    deployment_path.write_text(contracts.dumps(deployment))
    os.environ[ENVIRONMENT[q['module_id']]]=str(deployment_path)
    catalog=ModuleContracts(ROOT)
    module=catalog.load(q['module_id']); module.python=q['adapter_python']
    if module.manifest['version']!=q['module_version']: raise ValueError('Staged module version differs')
    op=module.manifest['operations'][q['operation']]
    contracts.validate(q['input'],module.schemas[op['input_schema']])
    stamp=datetime.now(timezone.utc).isoformat()
    result={'schema_version':'mlcc.task-result.v1','task_id':q['platform_task_id'],
        'module':{k:module.manifest[k] for k in ('id','version','interface_version','kind')},'operation':q['operation'],
        'execution':{'status':'blocked','created_at':stamp,'updated_at':stamp,'backend_exit_code':None,'events':[]},
        'input':{'schema':op['input_schema'],'payload':q['input']},
        'provenance':{'evidence_kind':'none','method':{'name':'not_executed','version':'not_recorded'},
            'backend':{'name':'not_executed','version':'not_recorded'},'units':{},'conditions':{},'applicability':'No computed result available','sources':[]},
        'results':None,'quality':{name:quality([],op['required_checks'][name]) for name in ('numerical','scientific')},
        'errors':[],'warnings':[],'limitations':[],'artifacts':[]}
    request={'schema_version':'mlcc.adapter-request.v1','interface_version':'1.0','action':'preflight',
        'module_id':q['module_id'],'operation':q['operation'],'input':q['input'],'task_id':None,'artifact_dir':None}
    started=False
    artifacts=request_path.parent/'artifacts'
    artifacts.mkdir(exist_ok=False)
    (request_path.parent/'logs').mkdir(exist_ok=False)
    try:
        report,code=invoke(module,request,min(10,op['timeout_seconds']),request_path.parent/'logs/preflight')
        contracts.validate(report,catalog.common_schema('adapter-preflight'))
        if code or not report['ready'] or report['errors'] or any(c['status']=='failed' for c in report['checks']):
            result['errors']=report['errors'] or [{'code':'PREFLIGHT_REFUSED','message':'Adapter preflight refused execution'}]
            result['warnings']=report['warnings']
        else:
            request.update(action='execute',task_id=q['platform_task_id'],artifact_dir=str(artifacts))
            started=True
            response,code=invoke(module,request,op['timeout_seconds'],request_path.parent/'logs')
            contracts.validate(response,catalog.common_schema('adapter-result'))
            kind=response['provenance']['evidence_kind']
            if kind not in op['evidence_kinds'] and not (kind=='none' and response['execution_status'] in ('failed','blocked') and not response['results']):
                raise ValueError('Undeclared evidence kind')
            if response['execution_status']=='succeeded' or response['results']: contracts.validate(response['results'],module.schemas[op['output_schema']])
            paths=set()
            for descriptor in response['artifacts']:
                relative=descriptor['path']
                if not relative.startswith('artifacts/') or relative in paths: raise ValueError('Invalid/duplicate artifact')
                paths.add(relative)
                path=contracts.confined(request_path.parent,relative)
                result['artifacts'].append(dict(descriptor,size_bytes=path.stat().st_size,evidence_kind=kind))
            result.update(provenance=response['provenance'],results=response['results'],errors=response['errors'],
                          warnings=response['warnings'],limitations=response['limitations'])
            result['quality']={name:quality(response['quality'][name],op['required_checks'][name]) for name in ('numerical','scientific')}
            state=response['execution_status']
            if code:
                state='failed'; result['errors'].append({'code':'ADAPTER_EXIT_ERROR','message':str(code)})
            if state=='succeeded' and result['errors']: state='failed'
            if state in ('failed','blocked') and not result['errors']: raise ValueError('Failure requires a reason')
            result['execution'].update(status=state,backend_exit_code=code)
    except Exception as exc:
        result['execution']['status']='interrupted' if getattr(exc,'code',None)=='ADAPTER_TIMEOUT' else ('failed' if started else 'blocked')
        result['errors'].append({'code':getattr(exc,'code','ADAPTER_ERROR'),'message':str(exc)})
    result['execution']['updated_at']=datetime.now(timezone.utc).isoformat()
    contracts.validate(result,catalog.common_schema('task-result'))
    saved={'schema':'mlcc.task-execution-response.v1','platform_task_id':q['platform_task_id'],'scheduler_job_id':job,'result':result}
    temporary=response_path.with_suffix('.tmp');temporary.write_text(contracts.dumps(saved));temporary.replace(response_path)
    return saved

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True);parser.add_argument('--response',required=True)
    args=parser.parse_args()
    saved=execute(args.request,args.response)
    print(contracts.dumps({'task_id':saved['platform_task_id'],'execution':saved['result']['execution']}))
    raise SystemExit(0 if saved['result']['execution']['status']=='succeeded' else 1)
