"""Trusted host configuration and one external scientific invocation; no task system."""
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

from .common import ROOT, ModuleError, digest, read_json, loads, write_json
from .validation import estimate_cells


def _validate_native(config, required, limits):
    """Host-only native binding; no backend probe, shell, install or fallback."""
    if set(config) != required or config.get('transport') != 'native_linux':
        raise ValueError('Unexpected native deployment fields/transport')
    if sys.platform != 'linux':
        raise ValueError('native_linux requires a Linux Adapter host')
    for key in ('python', 'linux_root') + (('ngspice',) if 'ngspice' in required else ()):
        value = config[key]
        if (not isinstance(value, str) or not value or '\\' in value
                or any(ord(ch) < 32 for ch in value)):
            raise ValueError('Native paths must be canonical absolute POSIX strings: ' + key)
        path = PurePosixPath(value)
        if not path.is_absolute() or value.startswith('//') or '..' in path.parts or path.as_posix() != value:
            raise ValueError('Native paths must be canonical absolute POSIX strings: ' + key)
    release = Path(config['linux_root'])
    if not release.is_dir() or release == Path(release.anchor):
        raise ValueError('Existing explicit native Bundle release directory required')
    for key in ('python',) + (('ngspice',) if 'ngspice' in required else ()):
        if not Path(config[key]).is_file() or not os.access(config[key], os.X_OK):
            raise ValueError('Existing executable native file required: ' + key)
    if not (ROOT / 'science_entry.py').is_file():
        raise ValueError('Native science_entry.py is missing')
    for key, low, high in limits:
        if type(config[key]) is not int or config[key] < low or (high is not None and config[key] > high):
            raise ValueError('Invalid explicit native resource budget: ' + key)


def _native_map(config, path):
    try:
        native = Path(path).resolve()
        native.relative_to(Path(config['linux_root']).resolve())
        return str(native)
    except (OSError, ValueError) as exc:
        raise ModuleError('PATH_MAPPING_ERROR', 'Path is outside the native Bundle release') from exc


@dataclass(frozen=True)
class Deployment:
    config: dict

    @classmethod
    def load(cls, *, extended=False):
        setting = os.environ.get('MLCC_FEA_DEPLOYMENT')
        if not setting or not Path(setting).is_absolute():
            raise ModuleError('DEPLOYMENT_NOT_CONFIGURED', 'Host must set MLCC_FEA_DEPLOYMENT to an absolute deployment JSON path')
        try:
            c = read_json(setting)
            if not isinstance(c, dict): raise ValueError('Deployment must be an object')
            if c.get('schema_version') in ('fea.deployment.native.v1', 'fem.deployment.native.v1'):
                expanded = c['schema_version'] == 'fem.deployment.native.v1'
                required = {'schema_version','transport','python','linux_root','timeout_seconds','threads','max_cells'}
                if expanded:
                    required.add('profile')
                    if not extended or c.get('profile') != 'device_extended_v1':
                        raise ValueError('Extended native deployment is only valid for new device operations')
                _validate_native(c, required, [('timeout_seconds',1,240 if expanded else 120),
                                               ('threads',1,1),('max_cells',1,150000 if expanded else 50000)])
                result = cls(c); result.map(ROOT / 'science_entry.py'); return result
            required = {'schema_version', 'wsl_executable', 'distribution', 'python',
                        'windows_root', 'linux_root', 'timeout_seconds', 'threads', 'max_cells'}
            expanded = c.get('schema_version')=='fem.deployment.v2'
            if expanded:
                required.add('profile')
                if not extended or c.get('profile')!='device_extended_v1':
                    raise ValueError('Extended deployment is only valid for the new device operations')
            if set(c) != required or c['schema_version'] not in ('fea.deployment.v1','fem.deployment.v2'):
                raise ValueError('Unexpected deployment fields/version')
            if os.name != 'nt':
                raise ValueError('The module Adapter is Windows-only; invoke science_entry directly for native development')
            exe = Path(c['wsl_executable'])
            if not exe.is_absolute() or not exe.is_file() or exe.name.lower() != 'wsl.exe':
                raise ValueError('Existing absolute wsl.exe is required')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', c['distribution']):
                raise ValueError('Invalid distribution identity')
            for key in ('python', 'linux_root'):
                p = PurePosixPath(c[key])
                if not p.is_absolute() or '..' in p.parts or '\\' in c[key]:
                    raise ValueError('Linux paths must be absolute canonical POSIX paths')
            if not Path(c['windows_root']).is_absolute() or not Path(c['windows_root']).is_dir():
                raise ValueError('Existing absolute Windows mapping root required')
            for key, low, high in (('timeout_seconds', 1, 240 if expanded else 120), ('threads', 1, 1), ('max_cells', 1, 150000 if expanded else 50000)):
                if type(c[key]) is not int or not low <= c[key] <= high:
                    raise ValueError(f'{key} is outside this release operational limits [{low},{high}]')
            result = cls(c)
            result.map(ROOT / 'science_entry.py')
            return result
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ModuleError('INVALID_DEPLOYMENT', str(exc)) from exc

    @property
    def fingerprint(self):
        return digest(self.config)

    def map(self, path):
        if self.config.get('transport') == 'native_linux':
            return _native_map(self.config, path)
        root = Path(self.config['windows_root']).resolve()
        try:
            rel = Path(path).resolve().relative_to(root)
        except ValueError as exc:
            raise ModuleError('PATH_MAPPING_ERROR', 'Path is outside the trusted deployment mapping') from exc
        return str(PurePosixPath(self.config['linux_root']).joinpath(*rel.parts))

    def command(self, *args, cwd=None):
        if self.config.get('transport') == 'native_linux':
            if cwd is not None: self.map(cwd)
            return [self.config['python'], '-B', '-u', self.map(ROOT / 'science_entry.py'), *args]
        prefix = [self.config['wsl_executable'], '--distribution', self.config['distribution']]
        if cwd is not None:
            prefix += ['--cd', self.map(cwd)]
        return prefix + ['--exec', self.config['python'], '-B', '-u', self.map(ROOT / 'science_entry.py'), *args]

    def check_resources(self, payload):
        estimate = estimate_cells(payload)
        if payload.get('analysis')=='electromagnetic':
            from .validation import body_height
            import math
            p=payload['geometry']; port=payload['port']; H=body_height(payload)
            ratio=(p['body_length_m']+2*port['bus_width_m'])*(H+port['feed_air_m']+port['bottom_air_m'])/(p['body_length_m']*H)
            estimate=math.ceil(estimate*ratio)
        if estimate > self.config['max_cells']:
            raise ModuleError('RESOURCE_LIMIT', f'Conservative mesh estimate {estimate} exceeds host budget {self.config["max_cells"]}; refine request/obtain a new resource review')
        return estimate

    def probe(self):
        try:
            p = subprocess.run(self.command('--probe'), capture_output=True, timeout=7,
                               encoding='utf-8', errors='replace', shell=False)
            if p.returncode:
                raise ValueError(f'Scientific probe exit {p.returncode}: {p.stderr[-1500:]}')
            data = loads(p.stdout)
            if not data.get('ready'):
                raise ValueError(data.get('error', 'Probe not ready'))
            if data['versions']['fenics-dolfinx'] != '0.11.0':
                raise ValueError('Only the reviewed DOLFINx 0.11.0 API is supported by this release')
            return data
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            raise ModuleError('BACKEND_UNAVAILABLE', str(exc)) from exc

    def execute(self, payload, artifact_dir, task_id, *, operation=None):
        if self.config.get('transport') == 'native_linux': self.map(artifact_dir)
        self.check_resources(payload)
        directory = Path(artifact_dir).resolve()
        if not directory.is_dir():
            raise ModuleError('INVALID_REQUEST', 'Runtime-owned artifact directory must already exist')
        work = directory / 'native'
        try:
            work.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise ModuleError('TASK_ALREADY_STARTED', 'Native directory exists; automatic re-execution is forbidden') from exc
        request = work / 'request.json'
        response = work / 'response.json'
        command = self.command('--request', self.map(request), '--response', self.map(response), cwd=work)
        write_json(work / 'launch.json', {'task_id': task_id, 'deployment': self.config,
                                        'deployment_sha256': self.fingerprint, 'argv': command,
                                        'adapter_platform': os.name})
        native_request = {'schema_version': 'fea.science-request.v1', 'input': payload,
                            'input_sha256': digest(payload), 'artifact_dir': self.map(directory),
                            'max_cells': self.config['max_cells'], 'threads': self.config['threads']}
        if operation is not None: native_request['operation']=operation
        write_json(request,native_request)
        try:
            with (work/'stdout.log').open('xb') as out, (work/'stderr.log').open('xb') as err:
                p = subprocess.run(command, cwd=work, stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=err, shell=False,
                                   timeout=self.config['timeout_seconds'])
        except subprocess.TimeoutExpired as exc:
            raise ModuleError('SCIENTIFIC_STATE_UNKNOWN', 'Scientific transport timed out; Linux solver termination is NOT confirmed. Preserve this task and reconcile native process/logs before any new submission.') from exc
        except OSError as exc:
            raise ModuleError('SCIENTIFIC_LAUNCH_FAILED', str(exc)) from exc
        if p.returncode:
            detail = ''
            try:
                if response.is_file() and response.stat().st_size <= 2*1024*1024:
                    failure = read_json(response)
                    if failure.get('status') == 'failed':
                        detail = f" Native {failure.get('code')}: {failure.get('message')}"
            except (OSError,ValueError,TypeError,AttributeError):
                pass
            raise ModuleError('SCIENTIFIC_EXECUTION_FAILED', f'Scientific process exited {p.returncode}; no numerical result accepted.'+detail)
        if not response.is_file() or response.stat().st_size > 2*1024*1024:
            raise ModuleError('INVALID_SCIENTIFIC_RESULT', 'Missing or oversized native response')
        try:
            result = read_json(response)
            return result
        except (OSError, ValueError) as exc:
            raise ModuleError('INVALID_SCIENTIFIC_RESULT', f'Invalid native JSON: {exc}') from exc
