"""Deterministic preflight, local queue, execution and evidence collection."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import uuid

from .contracts import FrameworkError, confined, validate
from .registry import Registry
from .store import Store, now, transition
from .transport import invoke


def error(code, message):
    return {'code': code, 'message': str(message)}


def quality_summary(checks, required):
    checks = deepcopy(checks)
    ids = [check['id'] for check in checks]
    if len(ids) != len(set(ids)):
        raise FrameworkError('CONTRACT_ERROR', 'Duplicate quality check ids')
    for name in required:
        if name not in ids:
            checks.append({'id': name, 'status': 'not_checked', 'message': 'Required check not reported by module'})
    statuses = {check['status'] for check in checks}
    status = next((s for s in ('failed', 'warning', 'not_checked') if s in statuses), None)
    if status is None:
        status = 'passed' if 'passed' in statuses else 'not_checked'
    return {'status': status, 'checks': checks}


def empty_provenance():
    return {'evidence_kind': 'none', 'method': {'name': 'not_executed', 'version': 'not_recorded'},
            'backend': {'name': 'not_executed', 'version': 'not_recorded'}, 'units': {}, 'conditions': {},
            'applicability': 'No computed result is available.', 'sources': []}


class Runtime:
    def __init__(self, project, bindings=None):
        self.registry = Registry(Path(project), bindings)
        self.store = Store(project)

    def _operation(self, module_id, operation):
        module = self.registry.load(module_id)
        if module.manifest['implementation'] != 'implemented':
            raise FrameworkError('NOT_INTEGRATED', f'{module_id} has no connected calculation')
        if operation not in module.manifest['operations']:
            raise FrameworkError('UNKNOWN_OPERATION', f'Unsupported operation: {operation}')
        return module, module.manifest['operations'][operation]

    def _preflight(self, module, operation, payload):
        report = {'schema_version': 'mlcc.preflight.v1', 'module_id': module.id, 'operation': operation,
                  'ready': False, 'dependency_checks': [], 'checks': [], 'errors': [], 'warnings': []}
        try:
            op = module.manifest['operations'][operation]
            validate(payload, module.schemas[op['input_schema']])
            report['dependency_checks'] = self.registry.dependencies(module)
            if not all(item['available'] for item in report['dependency_checks']):
                raise FrameworkError('DEPENDENCY_UNAVAILABLE', 'Required interpreter/package/executable is unavailable')
            request = self._request(module, operation, payload, 'preflight')
            response, code = invoke(module, request, min(10, op['timeout_seconds']))
            validate(response, self.registry.common_schema('adapter-preflight'))
            report['checks'] = response['checks']
            report['warnings'] = response['warnings']
            report['errors'] = response['errors']
            if code != 0:
                report['errors'].append(error('PREFLIGHT_EXIT_ERROR', f'Adapter preflight exited {code}'))
            if not response['ready'] and not report['errors']:
                report['errors'].append(error('MODULE_NOT_READY', 'Module preflight refused execution'))
            if any(c['status'] == 'failed' for c in response['checks']):
                report['errors'].append(error('PREFLIGHT_CHECK_FAILED', 'A module preflight check failed'))
            report['ready'] = response['ready'] and not report['errors']
        except Exception as exc:
            report['errors'].append(error(getattr(exc, 'code', 'PREFLIGHT_ERROR'), exc))
        return report

    def preflight(self, module_id, operation, payload):
        module, _ = self._operation(module_id, operation)
        return self._preflight(module, operation, payload)

    def _request(self, module, operation, payload, action, task_id=None):
        request = {'schema_version': 'mlcc.adapter-request.v1', 'interface_version': '1.0',
                   'action': action, 'module_id': module.id, 'operation': operation,
                   'input': payload, 'task_id': task_id,
                   'artifact_dir': str(self.store.task_dir(task_id) / 'artifacts') if task_id else None}
        validate(request, self.registry.common_schema('adapter-request'))
        return request

    def run(self, module_id, operation, payload, *, defer=False):
        # Malformed documents and unknown routes have no valid task identity.
        validate(payload, {'type': 'object'})
        module, op = self._operation(module_id, operation)
        report = self._preflight(module, operation, payload)
        stamp = now()
        result = {'schema_version': 'mlcc.result.v1', 'task_id': 'task-' + uuid.uuid4().hex,
                  'module': {key: module.manifest[key] for key in ('id', 'version', 'interface_version', 'kind')},
                  'operation': operation,
                  'execution': {'status': 'queued', 'created_at': stamp, 'updated_at': stamp,
                                'backend_exit_code': None, 'events': [{'status': 'queued', 'at': stamp}]},
                  'input': {'schema': op['input_schema'], 'payload': deepcopy(payload)},
                  'provenance': empty_provenance(), 'results': None,
                  'quality': {name: quality_summary([], op['required_checks'][name]) for name in ('numerical', 'scientific')},
                  'errors': deepcopy(report['errors']), 'warnings': deepcopy(report['warnings']),
                  'limitations': [], 'artifacts': []}
        if not report['ready']:
            transition(result, 'blocked')
        validate(result, self.registry.common_schema('result'))
        record = {'result': result, 'preflight': report, 'snapshot': {
            'manifest': module.manifest, 'schemas': module.schemas, 'python': module.python}}
        self.store.create(record)
        if report['ready'] and op['execution'] == 'sync' and not defer:
            return self.work(result['task_id'])
        return result

    def _artifacts(self, task_id, descriptors, evidence_kind):
        rows = []
        paths = set()
        directory = self.store.task_dir(task_id)
        for descriptor in descriptors:
            relative = descriptor['path']
            if not relative.startswith('artifacts/') or relative in paths:
                raise FrameworkError('ARTIFACT_ERROR', 'Artifact must be unique and below artifacts/')
            path = confined(directory, relative)
            paths.add(relative)
            rows.append({**descriptor, 'size_bytes': path.stat().st_size, 'evidence_kind': evidence_kind})
        return rows

    def _logs(self, task_id):
        rows = []
        for name, media in (('adapter.stdout.json', 'application/json'), ('adapter.stderr.log', 'text/plain')):
            directory = self.store.task_dir(task_id)
            path = confined(directory, f'logs/{name}', must_exist=False)
            if path.is_file():
                rows.append({'path': f'logs/{name}', 'media_type': media, 'description': 'Raw adapter protocol or diagnostics; not validated scientific evidence',
                             'size_bytes': path.stat().st_size, 'evidence_kind': 'none'})
        return rows

    def work(self, task_id):
        record = self.store.read(task_id)
        if record['result']['execution']['status'] != 'queued':
            # Terminal/running tasks can never be executed again by this API.
            return self.result(task_id)
        lock = self.store.claim(task_id)
        try:
            record = self.store.read(task_id)
            result = record['result']
            if result['execution']['status'] != 'queued':
                return self.result(task_id)
            started = False
            try:
                module, op = self._operation(result['module']['id'], result['operation'])
                snapshot = {'manifest': module.manifest, 'schemas': module.schemas, 'python': module.python}
                if snapshot != record['snapshot']:
                    raise FrameworkError('CONTRACT_CHANGED', 'Manifest, schemas or interpreter changed since submission; saved task will not execute')
                report = self._preflight(module, result['operation'], result['input']['payload'])
                record['execution_preflight'] = report
                if not report['ready']:
                    result['errors'].extend(report['errors'])
                    transition(result, 'blocked')
                else:
                    directory = self.store.task_dir(task_id)
                    confined(directory, 'artifacts', must_exist=False).mkdir(exist_ok=False)
                    transition(result, 'running')
                    self.store.save(record)
                    started = True
                    request = self._request(module, result['operation'], result['input']['payload'], 'execute', task_id)
                    response, code = invoke(module, request, op['timeout_seconds'], directory / 'logs')
                    result['execution']['backend_exit_code'] = code
                    validate(response, self.registry.common_schema('adapter-result'))
                    kind = response['provenance']['evidence_kind']
                    no_result_failure = kind == 'none' and response['execution_status'] in {'failed', 'blocked'} and not response['results']
                    if kind not in op['evidence_kinds'] and not no_result_failure:
                        raise FrameworkError('EVIDENCE_KIND_MISMATCH', f'Undeclared evidence kind: {kind}')
                    # A failure may have no scientific quantities; never invent required success fields.
                    # Nonempty diagnostic/partial output must still satisfy its professional schema.
                    if response['execution_status'] == 'succeeded' or response['results']:
                        validate(response['results'], module.schemas[op['output_schema']])
                    quality = {name: quality_summary(response['quality'][name], op['required_checks'][name])
                               for name in ('numerical', 'scientific')}
                    artifacts = self._artifacts(task_id, response['artifacts'], kind)
                    state = response['execution_status']
                    errors = response['errors']
                    if code != 0:
                        state = 'failed'
                        errors.append(error('ADAPTER_EXIT_ERROR', f'Adapter exited {code}'))
                    if state == 'succeeded' and errors:
                        state = 'failed'
                    if state in {'failed', 'blocked'} and not errors:
                        raise FrameworkError('CONTRACT_ERROR', 'Failed/blocked response requires error reasons')
                    result.update(provenance=response['provenance'], results=response['results'], quality=quality,
                                  errors=errors, warnings=result['warnings'] + response['warnings'],
                                  limitations=response['limitations'], artifacts=artifacts)
                    transition(result, state)
            except Exception as exc:
                result['errors'].append(error(getattr(exc, 'code', 'RUNTIME_ERROR'), exc))
                transition(result, 'interrupted' if started and getattr(exc, 'code', None) == 'ADAPTER_TIMEOUT'
                           else ('failed' if started else 'blocked'))
            result['artifacts'].extend(self._logs(task_id))
            validate(result, self.registry.common_schema('result'))
            self.store.save(record)
            return deepcopy(result)
        finally:
            lock.unlink(missing_ok=True)

    def result(self, task_id):
        # No module discovery, dependency probing, imports, execution or writes.
        result = self.store.read(task_id)['result']
        validate(result, self.registry.common_schema('result'))
        if result['task_id'] != task_id:
            raise FrameworkError('INVALID_RECORD', 'Saved task identity mismatch')
        return result

    def status(self, task_id):
        result = self.result(task_id)
        return {'schema_version': 'mlcc.status.v1', 'task_id': task_id, 'module': result['module'],
                'operation': result['operation'], 'execution': result['execution'],
                'quality': {key: value['status'] for key, value in result['quality'].items()},
                'evidence_kind': result['provenance']['evidence_kind'], 'errors': result['errors'],
                'warnings': result['warnings'], 'limitations': result['limitations']}

    def artifact(self, task_id, reference):
        result = self.result(task_id)
        descriptor = next((a for a in result['artifacts'] if a['path'] == reference), None)
        if descriptor is None:
            raise FrameworkError('UNKNOWN_ARTIFACT', 'Artifact not registered in task result')
        path = confined(self.store.task_dir(task_id), reference)
        if path.stat().st_size != descriptor['size_bytes']:
            raise FrameworkError('ARTIFACT_CHANGED', 'Artifact size changed after collection')
        return {'task_id': task_id, 'artifact': descriptor, 'absolute_path': str(path)}
