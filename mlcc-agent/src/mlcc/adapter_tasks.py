"""Four independent scales: explicit creation, shared SiteRunner, saved results.

Only stdlib imports. Creation validates/stages inputs but never probes a backend,
opens SSH, submits Slurm, or imports a scientific library.
"""
from copy import deepcopy
from pathlib import Path, PurePosixPath
import re
import shutil

from .tasks import TaskRecord, load_task, save_task

COMPUTE_ROOT = Path(__file__).resolve().parents[2]
from . import contracts
from .module_contracts import ModuleContracts
from .capabilities import describe
MODULES = frozenset(m['id'] for m in describe()['modules'] if m.get('schema_version') == 'mlcc.module.v1')


class ScaleInputError(ValueError):
    """A caller-supplied scale selection or scientific/task input is invalid."""


def scale_task_request_schema():
    return contracts.read_json(COMPUTE_ROOT / 'schemas/scale-task-request.schema.json')


def _absolute_posix(value):
    if not isinstance(value, str) or not value.startswith('/') or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('Host executable/root paths must be absolute POSIX strings')
    path = PurePosixPath(value)
    if '..' in path.parts or path.as_posix() != value or value == '/':
        raise ValueError('Host paths must be canonical and non-root')
    return value


def describe_scales(module_id=None, operation=None):
    registry = ModuleContracts(COMPUTE_ROOT)
    if module_id is not None:
        if module_id not in MODULES:
            raise ScaleInputError('Unsupported scale: select fem, phase_field, rve, or spice')
        module = registry.load(module_id)
        if operation not in module.manifest['operations']:
            raise ScaleInputError('Select one supported operation: ' + ', '.join(module.manifest['operations']))
        op = module.manifest['operations'][operation]
        return {'schema': 'mlcc.scale-operation.v1', 'module_id': module_id,
                'version': module.manifest['version'], 'operation': operation, 'contract': op,
                'input_schema': module.schemas[op['input_schema']], 'task_request_schema': scale_task_request_schema(),
                'output_schema': module.schemas[op['output_schema']], 'backend_availability': 'not_checked'}
    return {'schema': 'mlcc.scale-catalog.v1', 'task_request_schema': scale_task_request_schema(), 'modules': [
        {'id': name, 'version': (module := registry.load(name)).manifest['version'],
         'operations': module.manifest['operations'],
         'backend_availability': 'not_checked',
         'scientific_acceptance': 'not_checked'} for name in sorted(MODULES)]}


def create_scale_task(*, module_id, operation, input_path, site_path, request_path):
    payload = contracts.read_json(Path(input_path))
    request = contracts.read_json(Path(request_path))
    module, op = _validate_scale_inputs(module_id, operation, payload, request)
    return _stage_scale_task(module, op, operation, payload, request, input_path, site_path)


def create_scale_task_from_data(*, module_id, operation, input_data, request, site_path, workspace):
    module, op = _validate_scale_inputs(module_id, operation, input_data, request)
    task_id = request['task_id']
    if (workspace / 'tasks' / task_id).exists():
        raise ScaleInputError(f'Task already exists: {task_id}; inspect the existing task instead of recreating it')
    input_path = workspace / 'inputs' / f'{task_id}.json'
    request_path = workspace / 'requests' / f'{task_id}.json'
    for path, value in ((input_path, input_data), (request_path, request)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contracts.dumps(value), encoding='utf-8')
    return _stage_scale_task(module, op, operation, input_data, request, input_path, site_path)


def _validate_scale_inputs(module_id, operation, payload, request):
    if module_id not in MODULES:
        raise ScaleInputError('Supported scales: fem, phase_field, rve, spice')
    module = ModuleContracts(COMPUTE_ROOT).load(module_id)
    if operation not in module.manifest['operations']:
        raise ScaleInputError('Select one supported operation: ' + ', '.join(module.manifest['operations']))
    op = module.manifest['operations'][operation]
    try:
        contracts.validate(request, scale_task_request_schema(), path='request')
        contracts.validate(payload, module.schemas[op['input_schema']], path='input')
    except contracts.FrameworkError as exc:
        if exc.code != 'CONTRACT_ERROR':
            raise
        raise ScaleInputError(f'{exc}; task request schema is mlcc.scale-task-request.v1') from exc
    return module, op


def _stage_scale_task(module, op, operation, payload, request, input_path, site_path):
    module_id = module.id
    task_id, resources = request['task_id'], request['resource_request']
    site = contracts.read_json(Path(site_path))
    engine = module.manifest['engine']
    if 'scales' in site and engine in site:
        raise ValueError('Select one explicit backend configuration; legacy scales and engine binding conflict')
    # Retain old explicit site files; new bindings use the same engine-level
    # organization as the existing site.abacus and site.lammps sections.
    config = site['scales'] if 'scales' in site else site[engine]
    python = _absolute_posix(config['runtime_python'])
    binding = config['modules'][module_id]
    adapter_python = _absolute_posix(binding['adapter_python'])
    deployment = deepcopy(binding.get('operation_deployments', {}).get(operation, binding['deployment']))
    if deployment.get('transport') != 'native_linux' or 'linux_root' in deployment:
        raise ValueError('Host deployment must select native_linux; task-local linux_root is assigned by the bridge')
    _absolute_posix(deployment['python'])
    if module_id == 'spice':
        _absolute_posix(deployment['ngspice'])
    remote_root = _absolute_posix(site['workspace']['remote_root'])
    local = Path(site['workspace']['local']).resolve() / 'tasks' / task_id
    remote = str(PurePosixPath(remote_root) / 'tasks' / task_id)
    # Construct the same site/runner contract used by DFT and MD, without I/O.
    from .site_runner import SiteConfig
    SiteConfig.from_mapping(site)
    local.mkdir(parents=True, exist_ok=False)
    payload_root = local / 'payload'
    payload_root.mkdir()
    for directory in ('src', 'schemas', 'scientific_core'):
        shutil.copytree(COMPUTE_ROOT / directory, payload_root / directory,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(COMPUTE_ROOT / 'modules' / module_id, payload_root / 'modules' / module_id,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(COMPUTE_ROOT / 'tools/mlcc_execute.py', payload_root / 'execute.py')
    execution = {'schema': 'mlcc.scale-execution-request.v1', 'platform_task_id': task_id,
                 'module_id': module_id, 'module_version': module.manifest['version'],
                 'operation': operation, 'input': payload, 'adapter_python': adapter_python,
                 'deployment': deployment}
    (local / 'scale-request.json').write_text(contracts.dumps(execution), encoding='utf-8')
    data = {'task_id': task_id, 'engine': module.manifest['engine'],
            'execution_protocol': 'mlcc.adapter.v1', 'stage': 'independent_scale',
            'module_id': module_id, 'module_version': module.manifest['version'],
            'interface_version': module.manifest['interface_version'], 'operation': operation,
            'input_schema': op['input_schema'], 'scientific_input': payload,
            'study_ref': request.get('study_ref'), 'resource_request': resources,
            'required_results': [], 'runner': 'slurm', 'scheduler_job_id': None,
            'command': [python, '-I', 'payload/execute.py', '--request', 'scale-request.json',
                        '--response', 'scale-response.json'],
            'local_workdir': str(local), 'remote_workdir': remote,
            'transfer_paths': ['payload', 'scale-request.json'],
            'collect_paths': ['stdout.log', 'stderr.log', 'scale-response.json', 'artifacts', 'logs'],
            'status': 'defined', 'scientific_status': 'not_calculated',
            'result_file': str(local / 'scale-response.json')}
    task = TaskRecord(data, local / 'task.json')
    task.record_event('create', result='scale_inputs_staged_not_submitted',
                      input_file=str(Path(input_path).resolve()), site_file=str(Path(site_path).resolve()))
    save_task(task)
    return task.data


def read_scale_result(task_path):
    from .result_views import read_adapter_result
    return read_adapter_result(task_path)
