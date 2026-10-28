"""Read-only compatibility for bridge releases; never executes tasks."""
from pathlib import Path
from .tasks import load_task
COMPUTE_ROOT=Path(__file__).resolve().parents[2]
MODULES=frozenset({"fem","phase_field","rve","spice"})
def read_scale_result(task_path):
    """Read and validate collected evidence, including failed scientific tasks."""
    from . import contracts
    task = load_task(task_path)
    if task.data.get('engine') != 'scale_compute' or task.data.get('module_id') not in MODULES:
        raise ValueError('Expected a scale_compute task')
    root = Path(task_path).resolve().parent
    response = contracts.read_json(root / 'scale-response.json')
    if response['schema'] != 'mlcc.scale-execution-response.v1' or response['platform_task_id'] != task.task_id:
        raise ValueError('Collected response belongs to another platform task')
    if task.scheduler_job_id is None or response['scheduler_job_id'] != task.scheduler_job_id:
        raise ValueError('Collected response belongs to another Slurm job')
    result = response['result']
    contracts.validate(result, contracts.read_json(COMPUTE_ROOT / 'schemas/result.schema.json'))
    if result['execution']['status'] == 'succeeded':
        schema = contracts.read_json(root / 'payload/modules' / task.data['module_id'] / 'module.json')
        output_schema = schema['operations'][task.data['operation']]['output_schema']
        contracts.validate(result['results'], contracts.read_json(contracts.confined(
            root / 'payload/modules' / task.data['module_id'], output_schema)))
    if (result['task_id'] != response['runtime_task_id'] or result['module']['id'] != task.data['module_id']
            or result['module']['version'] != task.data['module_version'] or result['operation'] != task.data['operation']
            or result['module']['interface_version'] != task.data['interface_version']
            or result['input']['schema'] != task.data['input_schema']
            or result['input']['payload'] != task.data['scientific_input']):
        raise ValueError('Runtime result identity/input differs from the created scale task')
    relative = 'payload/outputs/tasks/' + result['task_id']
    if response['runtime_relative_dir'] != relative:
        raise ValueError('Unexpected collected runtime path')
    runtime_dir = contracts.confined(root, relative, must_exist=False)
    record = contracts.read_json(contracts.confined(runtime_dir, 'record.json'))
    if record['result'] != result:
        raise ValueError('Collected response differs from the original runtime record')
    for artifact in result['artifacts']:
        path = contracts.confined(runtime_dir, artifact['path'])
        if path.stat().st_size != artifact['size_bytes']:
            raise ValueError('Collected artifact size differs from the saved descriptor')
    return {'schema': 'mlcc.scale-delivery.v1', 'platform_task_id': task.task_id,
            'scheduler': {key: task.data.get(key) for key in ('scheduler_job_id', 'scheduler_state', 'exit_code')},
            'runtime_task_id': result['task_id'], 'runtime_directory': str(runtime_dir),
            'result': result, 'scientific_status': result['quality']['scientific']['status'],
            'limitations': ['Independent scale only; no cross-scale parameter transfer',
                            'Scheduler completion and execution success do not grant scientific qualification']}
