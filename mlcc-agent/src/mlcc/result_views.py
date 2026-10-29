"""Read-only shared result projection, preserving professional schemas and QC."""
from pathlib import Path
from . import contracts
from .tasks import load_task

ROOT=Path(__file__).resolve().parents[2]

def read_adapter_result(task_path):
    task=load_task(task_path)
    if task.data.get('engine')=='scale_compute':
        from .legacy_scale_results import read_scale_result
        return read_scale_result(task_path)
    if task.data.get('execution_protocol')!='mlcc.adapter.v1': raise ValueError('Not an adapter task')
    root=Path(task_path).resolve().parent
    response=contracts.read_json(root/'scale-response.json')
    if response.get('schema')!='mlcc.task-execution-response.v1': raise ValueError('Unsupported response schema')
    if response['platform_task_id']!=task.task_id or not task.scheduler_job_id or response['scheduler_job_id']!=task.scheduler_job_id:
        raise ValueError('Response belongs to another task/job')
    result=response['result']
    schema_name={'mlcc.task-result.v1':'task-result.schema.json',
                 'mlcc.result.v1':'result.schema.json'}.get(result.get('schema_version'))
    if schema_name is None: raise ValueError('Unsupported saved result contract')
    contracts.validate(result,contracts.read_json(contracts.confined(root/'payload/schemas',schema_name)))
    if (result['task_id']!=task.task_id or result['module']['id']!=task.data['module_id']
        or result['module']['version']!=task.data['module_version'] or result['operation']!=task.data['operation']
        or result['module']['interface_version']!=task.data['interface_version']
        or result['input']!={'schema':task.data['input_schema'],'payload':task.data['scientific_input']}):
        raise ValueError('Result identity/input mismatch')
    if result['execution']['status']=='succeeded' or result['results']:
        manifest=contracts.read_json(root/'payload/modules'/task.data['module_id']/'module.json')
        schema=manifest['operations'][task.data['operation']]['output_schema']
        contracts.validate(result['results'],contracts.read_json(contracts.confined(root/'payload/modules'/task.data['module_id'],schema)))
    for artifact in result['artifacts']:
        path=contracts.confined(root,artifact['path'])
        if path.stat().st_size!=artifact['size_bytes']: raise ValueError('Artifact changed')
    return {'schema':'mlcc.scale-delivery.v1','platform_task_id':task.task_id,
        'scheduler':{k:task.data.get(k) for k in ('scheduler_job_id','scheduler_state','exit_code')},
        'result':result,'scientific_status':result['quality']['scientific']['status']}

def task_summary(task):
    data=task.data
    view={k:data.get(k) for k in ('task_id','module_id','operation','engine','status','scheduler_job_id','scientific_status')}
    view['module_id']=data.get('module_id') or {'abacus':'dft','lammps':'md'}.get(data.get('engine'))
    if (data.get('execution_protocol')=='mlcc.adapter.v1' or data.get('engine')=='scale_compute') and data.get('collect_status')=='collected':
        try:
            delivery=read_adapter_result(task.path)
            view['scientific_status']=delivery['scientific_status']
            view['execution']=delivery['result']['execution']
            view['quality']=delivery['result']['quality']
        except (ValueError,OSError,KeyError) as exc:
            view['result_error']=str(exc)
    return view
