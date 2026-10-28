"""Filesystem discovery and subprocess dependency probes, without adapter imports."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import sys

from .contracts import FrameworkError, confined, read_json, validate, check_schema


@dataclass
class Module:
    root: Path
    manifest: dict
    schemas: dict
    python: str

    @property
    def id(self):
        return self.manifest['id']


class ModuleContracts:
    def __init__(self, project: Path, bindings: Path | None = None):
        self.project = Path(project).resolve()
        self.bindings = read_json(bindings) if bindings else {'schema_version': 'mlcc.bindings.v1', 'modules': {}}
        validate(self.bindings, self.common_schema('bindings'))
        for key, binding in self.bindings['modules'].items():
            if not re.fullmatch(r'[a-z][a-z0-9_]*', key):
                raise FrameworkError('INVALID_BINDING', f'Invalid module id: {key}')
            if 'python' in binding and not Path(binding['python']).is_absolute():
                raise FrameworkError('INVALID_BINDING', 'Interpreter bindings must be absolute paths')

    def common_schema(self, name):
        return read_json(confined(self.project, f'schemas/{name}.schema.json'))

    def load(self, module_id):
        if not isinstance(module_id, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', module_id):
            raise FrameworkError('UNKNOWN_MODULE', 'Invalid module id')
        path = confined(self.project, f'modules/{module_id}/module.json')
        manifest = read_json(path)
        validate(manifest, self.common_schema('module'))
        if manifest['id'] != module_id:
            raise FrameworkError('INVALID_MODULE', 'Directory and module id differ')
        implemented = manifest['implementation'] == 'implemented'
        if implemented and (manifest['adapter'] is None or not manifest['operations']):
            raise FrameworkError('INVALID_MODULE', 'Implemented modules need adapter and operations')
        if not implemented and (manifest['adapter'] is not None or manifest['operations']):
            raise FrameworkError('INVALID_MODULE', 'Unintegrated modules cannot advertise operations')
        if implemented:
            confined(path.parent, manifest['adapter']['entry'])
        schemas = {}
        for name, op in manifest['operations'].items():
            if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
                raise FrameworkError('INVALID_MODULE', f'Invalid operation: {name}')
            if not op['evidence_kinds'] or 'none' in op['evidence_kinds']:
                raise FrameworkError('INVALID_MODULE', 'Executable operations need explicit result evidence kinds')
            if manifest['kind'] != 'scientific' and any(k not in {'interface_selfcheck', 'demo'} for k in op['evidence_kinds']):
                raise FrameworkError('INVALID_MODULE', 'Non-scientific modules cannot advertise scientific evidence')
            for key in ('input_schema', 'output_schema'):
                schema = read_json(confined(path.parent, op[key]))
                check_schema(schema)
                if schema.get('type') != 'object':
                    raise FrameworkError('INVALID_SCHEMA', 'Operation root schemas must have type object')
                schemas[op[key]] = schema
            for names in op['required_checks'].values():
                if len(names) != len(set(names)):
                    raise FrameworkError('INVALID_MODULE', 'Required check ids must be unique')
        interpreter = self.bindings['modules'].get(module_id, {}).get('python', sys.executable)
        return Module(path.parent, manifest, schemas, interpreter)

    def dependencies(self, module):
        requirements = module.manifest['dependencies']
        checks = [{'kind': 'interpreter', 'name': module.python, 'available': Path(module.python).is_file()}]
        packages = [dep['name'] for dep in requirements if dep['kind'] == 'python_package']
        for name in packages:
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
                raise FrameworkError('INVALID_MODULE', 'python_package must be a top-level import name')
        if checks[0]['available'] and (packages or module.python != sys.executable):
            code = ('import importlib.util,json,sys; '
                    'print(json.dumps({n:importlib.util.find_spec(n) is not None for n in sys.argv[1:]}))')
            try:
                probe = subprocess.run([module.python, '-I', '-c', code, *packages],
                                       capture_output=True, text=True, encoding='utf-8', timeout=5)
                from .contracts import loads
                found = loads(probe.stdout) if probe.returncode == 0 else {}
                validate(found, {'type': 'object', 'additionalProperties': {'type': 'boolean'}})
                if probe.returncode:
                    checks[0]['available'] = False
                    checks[0]['reason'] = 'Interpreter probe failed'
            except (OSError, subprocess.TimeoutExpired, FrameworkError) as exc:
                found = {}
                checks[0]['available'] = False
                checks[0]['reason'] = str(exc)
            checks.extend({'kind': 'python_package', 'name': name, 'available': found.get(name, False)} for name in packages)
        elif packages:
            checks.extend({'kind': 'python_package', 'name': name, 'available': False} for name in packages)
        for dep in requirements:
            if dep['kind'] == 'executable':
                checks.append({**dep, 'available': shutil.which(dep['name']) is not None})
        return checks

    def describe(self, module):
        manifest = module.manifest
        dependencies = self.dependencies(module) if manifest['implementation'] == 'implemented' else []
        available = manifest['implementation'] == 'implemented' and all(c['available'] for c in dependencies)
        return {'id': module.id, 'title': manifest['title'], 'version': manifest['version'],
                'interface_version': manifest['interface_version'], 'kind': manifest['kind'],
                'implementation': manifest['implementation'],
                'availability': 'available' if available else ('dependency_unavailable' if manifest['implementation'] == 'implemented' else 'not_integrated'),
                'operations': manifest['operations'], 'dependencies': manifest['dependencies'],
                'dependency_checks': dependencies,
                'counts_as_scale_coverage': False,
                'coverage_note': 'Requires module real-run evidence and owner scientific acceptance; discovery does not certify coverage.'}

    def discover(self):
        modules_root = self.project / 'modules'
        if not modules_root.exists():
            return []
        rows = []
        for directory in sorted(modules_root.iterdir()):
            if not directory.is_dir():
                continue
            try:
                # An incomplete folder must remain visible as a load error.
                rows.append(self.describe(self.load(directory.name)))
            except Exception as exc:
                rows.append({'id': directory.name, 'availability': 'load_error', 'operations': {},
                             'counts_as_scale_coverage': False,
                             'errors': [{'code': getattr(exc, 'code', 'MODULE_LOAD_ERROR'), 'message': str(exc)}]})
        return rows
