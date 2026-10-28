"""Trusted host configuration; never interpolate science input into a shell."""
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from .common import ROOT, ModuleError, require, read_json, write_json, digest, loads
from .contract import validate_si


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


class Deployment:
    def __init__(self, config):
        self.config = config

    @classmethod
    def load(cls):
        setting = os.environ.get('MLCC_SPICE_DEPLOYMENT')
        require(setting and Path(setting).is_absolute(), 'Set absolute MLCC_SPICE_DEPLOYMENT host configuration', 'DEPLOYMENT_NOT_CONFIGURED')
        try:
            c = read_json(setting)
            if not isinstance(c, dict): raise ValueError('Deployment must be an object')
            if c.get('schema_version') == 'spice.deployment.native.v1':
                required = {'schema_version','transport','python','ngspice','linux_root','solver_timeout_seconds','client_timeout_seconds','max_ac_samples','max_transient_samples','max_branches'}
                _validate_native(c, required, [('solver_timeout_seconds',1,120),('client_timeout_seconds',1,150),
                    ('max_ac_samples',1,21000),('max_transient_samples',1,100000),('max_branches',1,8)])
                require(c['solver_timeout_seconds'] + 20 <= c['client_timeout_seconds'], 'Allow solver termination/export within outer budget', 'INVALID_DEPLOYMENT')
                dep=cls(c);dep.map(ROOT/'science_entry.py');return dep
            keys = {'schema_version','wsl_executable','distribution','python','ngspice','windows_root','linux_root','solver_timeout_seconds','client_timeout_seconds','max_ac_samples','max_transient_samples','max_branches'}
            require(set(c) == keys and c['schema_version'] == 'spice.deployment.v1' and os.name == 'nt', 'Windows spice.deployment.v1 required', 'INVALID_DEPLOYMENT')
            require(Path(c['wsl_executable']).is_absolute() and Path(c['wsl_executable']).is_file() and Path(c['wsl_executable']).name.lower() == 'wsl.exe', 'Existing absolute wsl.exe required', 'INVALID_DEPLOYMENT')
            require(re.fullmatch(r'[A-Za-z0-9_.-]+', c['distribution']), 'Invalid distro', 'INVALID_DEPLOYMENT')
            for k in ('python', 'ngspice', 'linux_root'):
                require(PurePosixPath(c[k]).is_absolute() and '\x00' not in c[k], 'Absolute Linux path required: '+k, 'INVALID_DEPLOYMENT')
            require(Path(c['windows_root']).is_absolute() and Path(c['windows_root']).is_dir(), 'Absolute Bundle mapping required', 'INVALID_DEPLOYMENT')
            for key, hi in [('solver_timeout_seconds',120), ('client_timeout_seconds',150), ('max_ac_samples',21000), ('max_transient_samples',100000), ('max_branches',8)]:
                require(type(c[key]) is int and 1 <= c[key] <= hi, 'Invalid explicit budget '+key, 'INVALID_DEPLOYMENT')
            require(c['solver_timeout_seconds'] + 20 <= c['client_timeout_seconds'], 'Allow solver termination/export within outer budget', 'INVALID_DEPLOYMENT')
            dep = cls(c)
            dep.map(ROOT/'science_entry.py')
            return dep
        except ModuleError:
            raise
        except (OSError, TypeError, KeyError, ValueError) as e:
            raise ModuleError('INVALID_DEPLOYMENT', str(e)) from e

    def map(self, path):
        if self.config.get('transport') == 'native_linux':
            return _native_map(self.config, path)
        try:
            r = Path(path).resolve().relative_to(Path(self.config['windows_root']).resolve())
        except ValueError as e:
            raise ModuleError('PATH_MAPPING_ERROR', 'Outside trusted Bundle mapping') from e
        return str(PurePosixPath(self.config['linux_root']).joinpath(*r.parts))

    def command(self, *args, cwd=None):
        if self.config.get('transport') == 'native_linux':
            if cwd is not None: self.map(cwd)
            return [self.config['python'], '-I', '-B', '-u', self.map(ROOT / 'science_entry.py'), *args]
        c = self.config
        cmd = [c['wsl_executable'], '--distribution', c['distribution']]
        if cwd is not None:
            cmd += ['--cd', self.map(cwd)]
        return cmd + ['--exec', c['python'], '-I', '-B', '-u', self.map(ROOT/'science_entry.py'), *args]

    def budget(self, c, op):
        n = validate_si(c, op)
        kind = 'ac' if op.startswith('ac_') else 'transient'
        require(n <= self.config['max_'+kind+'_samples'], 'Requested sampling exceeds host budget; no coarsening/retry', 'RESOURCE_LIMIT')
        require(kind != 'ac' or len(c['models']) <= self.config['max_branches'], 'Branch budget exceeded', 'RESOURCE_LIMIT')
        return n

    def probe(self):
        try:
            p = subprocess.run(self.command('--probe', '--ngspice', self.config['ngspice']), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=6, shell=False)
            require(p.returncode == 0, 'Scientific probe failed: ' + p.stderr[-700:], 'BACKEND_UNAVAILABLE')
            x = loads(p.stdout)
            require(x.get('ready') is True and x.get('ngspice_executable') == self.config['ngspice'] and x.get('backend_version') == '41', 'Unsupported backend; no fallback', 'BACKEND_UNAVAILABLE')
            return x
        except ModuleError:
            raise
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            raise ModuleError('BACKEND_UNAVAILABLE', str(e)) from e

    def execute(self, c, op, out, task):
        if self.config.get('transport') == 'native_linux': self.map(out)
        self.budget(c, op)
        native = Path(out)/'native'
        try:
            native.mkdir(exist_ok=False)
        except FileExistsError as e:
            raise ModuleError('TASK_ALREADY_STARTED', 'Native directory exists; no restart') from e
        q, r = native/'request.json', native/'response.json'
        cmd = self.command('--request', self.map(q), '--response', self.map(r), cwd=native)
        write_json(q, {'schema_version':'spice.science-request.v1', 'input':c, 'operation':op,
                       'input_sha256':digest(c), 'artifact_dir':self.map(out), 'ngspice':self.config['ngspice'],
                       'solver_timeout_seconds':self.config['solver_timeout_seconds'],
                       'max_points':self.config['max_ac_samples' if op.startswith('ac_') else 'max_transient_samples']})
        write_json(native/'launch.json', {'task_id':task, 'argv':cmd, 'deployment':self.config, 'deployment_sha256':digest(self.config)})
        try:
            with (native/'stdout.log').open('xb') as stdout, (native/'stderr.log').open('xb') as stderr:
                p = subprocess.run(cmd, cwd=native, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, shell=False, timeout=self.config['client_timeout_seconds'])
        except subprocess.TimeoutExpired as e:
            raise ModuleError('SCIENTIFIC_STATE_UNKNOWN', 'Scientific transport timed out; Linux/ngspice termination UNKNOWN. Reconcile processes/logs; no automatic retry.') from e
        except OSError as e:
            raise ModuleError('SCIENTIFIC_LAUNCH_FAILED', str(e)) from e
        require(r.is_file() and r.stat().st_size < 2*1024*1024, 'Native response missing/oversized', 'SCIENTIFIC_EXECUTION_FAILED')
        x = read_json(r)
        require(p.returncode == 0 and x.get('status') == 'succeeded', str(x.get('message', 'Native failure; inspect logs')), 'SCIENTIFIC_EXECUTION_FAILED')
        return x
