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
            raise ValueError('Unsupported scale')
        module = registry.load(module_id)
        if operation not in module.manifest['operations']:
            raise ValueError('Select one supported operation')
        op = module.manifest['operations'][operation]
        return {'schema': 'mlcc.scale-operation.v1', 'module_id': module_id,
                'version': module.manifest['version'], 'operation': operation, 'contract': op,
                'input_schema': module.schemas[op['input_schema']],
                'output_schema': module.schemas[op['output_schema']], 'backend_availability': 'not_checked'}
    return {'schema': 'mlcc.scale-catalog.v1', 'modules': [
        {'id': name, 'version': (module := registry.load(name)).manifest['version'],
         'operations': module.manifest['operations'],
         'backend_availability': 'not_checked',
         'scientific_acceptance': 'not_checked'} for name in sorted(MODULES)]}


def create_scale_task(*, module_id, operation, input_path, site_path, request_path):
    if module_id not in MODULES:
        raise ValueError('Supported scales: fem, phase_field, rve, spice')
    module = ModuleContracts(COMPUTE_ROOT).load(module_id)
    if operation not in module.manifest['operations']:
        raise ValueError('Unknown operation for the selected scale')
    op = module.manifest['operations'][operation]
    payload = contracts.read_json(Path(input_path))
    contracts.validate(payload, module.schemas[op['input_schema']])
    site, request = (contracts.read_json(Path(p)) for p in (site_path, request_path))
    if set(request) - {'schema', 'task_id', 'resource_request', 'study_ref'} or request.get('schema') != 'mlcc.scale-task-request.v1':
        raise ValueError('Invalid scale task request fields/schema')
    task_id = request['task_id']
    if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', task_id):
        raise ValueError('task_id must be a single readable directory name')
    resources = request['resource_request']
    if not isinstance(resources, dict) or not resources or resources.get('ntasks') != 1 or type(resources.get('ntasks')) is not int:
        raise ValueError('Explicit resources with ntasks=1 required by current scale kernels')
    # Existing kernels are serial. Budgets remain explicit host inputs.
    if any(isinstance(v, str) and ('\n' in v or '\r' in v) for v in resources.values()):
        raise ValueError('Resource values must not contain batch-script directives')
    allowed_resources = {'partition', 'account', 'ntasks', 'nodes', 'cpus_per_task', 'mem_mib', 'time'}
    if set(resources) - allowed_resources or not {'cpus_per_task', 'mem_mib', 'time'} <= resources.keys():
        raise ValueError('Explicit CPU, memory and time budgets required; unsupported resource keys')
    for key in ('cpus_per_task', 'mem_mib'):
        if type(resources[key]) is not int or resources[key] <= 0:
            raise ValueError('Positive integer CPU/memory budgets required')
    if ('nodes' in resources and type(resources['nodes']) is not int) or resources.get('nodes', 1) != 1:
        raise ValueError('Current scale kernels require one node')
    for key in ('partition', 'account', 'time'):
        if key in resources and (not isinstance(resources[key], str) or not re.fullmatch(r'[A-Za-z0-9_:.-]+', resources[key])):
            raise ValueError('Invalid explicit Slurm ' + key)
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
