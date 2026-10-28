"""Trusted Windows host binding; no user shell, installation or backend fallback."""
from pathlib import Path,PurePosixPath
import math
import os
import re
import subprocess
import sys
from .common import ROOT,ModuleError,read_json,write_json,digest,loads
from .contract import require

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
    def __init__(self,config):self.config=config;self.fingerprint=digest(config)
    @classmethod
    def load(cls):
        setting=os.environ.get('MLCC_RVE_DEPLOYMENT')
        require(setting and Path(setting).is_absolute(),'Set absolute MLCC_RVE_DEPLOYMENT host configuration','DEPLOYMENT_NOT_CONFIGURED')
        try:
            c=read_json(setting)
            if not isinstance(c, dict): raise ValueError('Deployment must be an object')
            if c.get('schema_version') == 'rve.deployment.native.v1':
                required = {'schema_version','transport','python','linux_root','timeout_seconds','threads','max_cells_2d','max_cells_3d'}
                _validate_native(c, required, [('timeout_seconds',1,240),('threads',1,1),('max_cells_2d',1,90000),('max_cells_3d',1,180000)])
                dep=cls(c);dep.map(ROOT/'science_entry.py');return dep
            require(set(c)=={'schema_version','wsl_executable','distribution','python','windows_root','linux_root','timeout_seconds','threads','max_cells_2d','max_cells_3d'},'Unexpected deployment keys','INVALID_DEPLOYMENT')
            require(c['schema_version']=='rve.deployment.v1' and os.name=='nt','Windows rve.deployment.v1 required','INVALID_DEPLOYMENT')
            require(Path(c['wsl_executable']).is_absolute() and Path(c['wsl_executable']).is_file() and Path(c['wsl_executable']).name.lower()=='wsl.exe','Absolute existing wsl.exe required','INVALID_DEPLOYMENT')
            require(re.fullmatch(r'[A-Za-z0-9_.-]+',c['distribution']) is not None,'Invalid distro','INVALID_DEPLOYMENT')
            require(PurePosixPath(c['python']).is_absolute() and PurePosixPath(c['linux_root']).is_absolute() and Path(c['windows_root']).is_absolute() and Path(c['windows_root']).is_dir(),'Absolute path mappings required','INVALID_DEPLOYMENT')
            for key,hi in [('threads',1),('timeout_seconds',240),('max_cells_2d',90000),('max_cells_3d',180000)]:require(type(c[key]) is int and 1<=c[key]<=hi,'Invalid explicit budget '+key,'INVALID_DEPLOYMENT')
            dep=cls(c);dep.map(ROOT/'science_entry.py');return dep
        except ModuleError:raise
        except (OSError,TypeError,ValueError,KeyError) as e:raise ModuleError('INVALID_DEPLOYMENT',str(e)) from e
    def map(self,path):
        if self.config.get('transport') == 'native_linux':
            return _native_map(self.config, path)
        try:r=Path(path).resolve().relative_to(Path(self.config['windows_root']).resolve())
        except ValueError as e:raise ModuleError('PATH_MAPPING_ERROR','Outside trusted mapping') from e
        return str(PurePosixPath(self.config['linux_root']).joinpath(*r.parts))
    def command(self,*args,cwd=None):
        if self.config.get('transport') == 'native_linux':
            if cwd is not None: self.map(cwd)
            return [self.config['python'], '-I', '-B', '-u', self.map(ROOT / 'science_entry.py'), *args]
        c=self.config;cmd=[c['wsl_executable'],'--distribution',c['distribution']]
        if cwd is not None:cmd+=['--cd',self.map(cwd)]
        return cmd+['--exec',c['python'],'-I','-B','-u',self.map(ROOT/'science_entry.py'),*args]
    def budget(self,c,d):
        # Planning guard only. Actual Gmsh count is checked before DOLFINx import/solve.
        # Unit-box h scaling: 4/h^2 triangles or 12/h^3 tets; not a scientific threshold.
        estimate=math.ceil((4 if d==2 else 12)/c['normalized_h']**d)
        require(estimate<=self.config[f'max_cells_{d}d'],f'Planning cells={estimate} exceeds explicit host budget; no remesh/retry','RESOURCE_LIMIT')
        return estimate
    def probe(self):
        try:
            r=subprocess.run(self.command('--probe'),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=7,shell=False)
            require(r.returncode==0,'Scientific probe failed: '+r.stderr[-1000:],'BACKEND_UNAVAILABLE')
            x=loads(r.stdout);require(x.get('ready') is True and x['versions']['dolfinx']=='0.11.0' and x['scalar_type']=='float64' and x['mpi_ranks']==1,'Unsupported scientific environment','BACKEND_UNAVAILABLE')
            return x
        except ModuleError:raise
        except (OSError,ValueError,KeyError,subprocess.TimeoutExpired) as e:raise ModuleError('BACKEND_UNAVAILABLE',str(e)) from e
    def execute(self,c,op,out,task):
        if self.config.get('transport') == 'native_linux': self.map(out)
        d=int(op[-2]);self.budget(c,d);out=Path(out).resolve();require(out.is_dir(),'Existing runtime artifact directory required','INVALID_REQUEST')
        native=out/'native'
        try:native.mkdir(exist_ok=False)
        except FileExistsError as e:raise ModuleError('TASK_ALREADY_STARTED','native exists; no restart or lock deletion') from e
        q=native/'request.json';r=native/'response.json'
        cmd=self.command('--request',self.map(q),'--response',self.map(r),cwd=native)
        write_json(native/'launch.json',{'task_id':task,'argv':cmd,'deployment':self.config,'deployment_sha256':self.fingerprint})
        write_json(q,{'schema_version':'rve.science-request.v1','input':c,'input_sha256':digest(c),'operation':op,'artifact_dir':self.map(out),'max_cells':self.config[f'max_cells_{d}d'],'threads':1})
        try:
            with (native/'stdout.log').open('xb') as stdout,(native/'stderr.log').open('xb') as stderr:
                p=subprocess.run(cmd,cwd=native,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,shell=False,timeout=self.config['timeout_seconds'])
        except subprocess.TimeoutExpired as e:raise ModuleError('SCIENTIFIC_STATE_UNKNOWN','Scientific transport timed out; Linux process termination UNKNOWN. Reconcile native PID/process and logs before another submission; no retry.') from e
        except OSError as e:raise ModuleError('SCIENTIFIC_LAUNCH_FAILED',str(e)) from e
        require(r.is_file() and r.stat().st_size<2*1024*1024,'Native response missing/oversized','INVALID_SCIENTIFIC_RESULT')
        x=read_json(r)
        require(p.returncode==0 and x.get('status')=='succeeded','Native execution failed: '+dumps_failure(x),'SCIENTIFIC_EXECUTION_FAILED')
        return x

def dumps_failure(x):return str({k:x.get(k) for k in ('code','message')})
