"""One host-authorized scale execution inside an existing Slurm allocation."""
import argparse
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parent
contracts, Registry, Runtime = runpy.run_path(str(ROOT / 'bootstrap.py'))['load']()
ENVIRONMENT = {'fem': 'MLCC_FEA_DEPLOYMENT', 'phase_field': 'MLCC_PHASE_FIELD_DEPLOYMENT',
               'rve': 'MLCC_RVE_DEPLOYMENT', 'spice': 'MLCC_SPICE_DEPLOYMENT'}


def execute(request_path, response_path):
    request_path, response_path = Path(request_path).resolve(), Path(response_path).resolve()
    request = contracts.read_json(request_path)
    if request['schema'] != 'mlcc.scale-execution-request.v1' or request['module_id'] not in ENVIRONMENT:
        raise ValueError('Unsupported scale request')
    job = os.environ.get('SLURM_JOB_ID')
    if not job:
        raise ValueError('Scale execution requires an explicit Slurm allocation')
    if response_path.exists():
        saved = contracts.read_json(response_path)
        if saved['platform_task_id'] != request['platform_task_id'] or saved['scheduler_job_id'] != job:
            raise ValueError('Saved response identity differs; reconciliation required')
        result = saved['result']
        if (result['module']['id'] != request['module_id'] or result['module']['version'] != request['module_version']
                or result['operation'] != request['operation'] or result['input']['payload'] != request['input']):
            raise ValueError('Saved response differs from the explicit scientific request')
        return saved  # Reading a completed invocation never creates another task.
    claim = request_path.parent / 'scale-execution.claim'
    with claim.open('x', encoding='utf-8') as stream:
        stream.write(job + '\n')
    deployment = dict(request['deployment'], linux_root=str(ROOT))
    if deployment.get('transport') != 'native_linux':
        raise ValueError('Only explicitly selected native_linux deployment is supported')
    deployment_path = ROOT / 'host-deployment.json'
    deployment_path.write_text(contracts.dumps(deployment), encoding='utf-8')
    os.environ[ENVIRONMENT[request['module_id']]] = str(deployment_path)
    bindings = ROOT / 'host-bindings.json'
    bindings.write_text(contracts.dumps({'schema_version': 'mlcc.bindings.v1', 'modules': {
        request['module_id']: {'python': request['adapter_python']}}}), encoding='utf-8')
    runtime = Runtime(ROOT, bindings)
    module = runtime.registry.load(request['module_id'])
    if module.manifest['version'] != request['module_version']:
        raise ValueError('Staged module version differs from the created task')
    result = runtime.run(request['module_id'], request['operation'], request['input'], defer=True)
    relation = {'platform_task_id': request['platform_task_id'], 'runtime_task_id': result['task_id'],
                'scheduler_job_id': job}
    (request_path.parent / 'scale-task-link.json').write_text(contracts.dumps(relation), encoding='utf-8')
    result = runtime.work(result['task_id'])
    response = {'schema': 'mlcc.scale-execution-response.v1', **relation,
                'runtime_relative_dir': 'payload/outputs/tasks/' + result['task_id'], 'result': result}
    temporary = response_path.with_suffix('.tmp')
    temporary.write_text(contracts.dumps(response), encoding='utf-8')
    temporary.replace(response_path)
    return response


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--response', type=Path, required=True)
    args = parser.parse_args(argv)
    response = execute(args.request, args.response)
    print(contracts.dumps({'platform_task_id': response['platform_task_id'],
                           'runtime_task_id': response['runtime_task_id'],
                           'execution': response['result']['execution']}))
    return 0 if response['result']['execution']['status'] == 'succeeded' else 1


if __name__ == '__main__':
    raise SystemExit(main())
