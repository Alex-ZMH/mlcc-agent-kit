"""Fixed native scientific entry. WSL runs only this code, not the MLCC runtime."""
import argparse
import importlib.metadata
import os
from pathlib import Path
import sys
from runpy import run_path
_core = run_path(str(Path(__file__).resolve().parents[2] / 'scientific_core/bootstrap.py'))['load'](
    __file__, required_version='0.1.0')
import traceback

from device_fem import VERSION
from device_fem.common import ModuleError, digest, dumps, file_hash, read_json, write_json
from device_fem.validation import validate_input

PACKAGES = ('fenics-dolfinx','fenics-ufl','petsc4py','mpi4py','gmsh','numpy','pyvista','matplotlib')


def probe():
    try:
        versions = {n:importlib.metadata.version(n) for n in PACKAGES}
        return {'ready':True,'versions':versions,'python':sys.version,'executable':sys.executable,
                'scientific_entry_version':VERSION}
    except importlib.metadata.PackageNotFoundError as exc:
        return {'ready':False,'error':str(exc)}


def execute(request_path, response_path):
    output = None
    try:
        request = read_json(request_path)
        if request.get('schema_version') != 'fea.science-request.v1':
            raise ModuleError('INVALID_REQUEST','Wrong native request version')
        allowed = {'schema_version','input','input_sha256','artifact_dir','max_cells','threads','benchmark','operation'}
        if set(request)-allowed or not (allowed-{'benchmark','operation'}) <= request.keys():
            raise ModuleError('INVALID_REQUEST','Unexpected native request fields')
        operation=request.get('operation')
        if operation is not None:
            from device_fem.extended_contract import validate_input as validate_extended
            payload=validate_extended(request['input'],operation)
        else:
            payload = validate_input(request['input'])
        if digest(payload) != request['input_sha256']:
            raise ModuleError('INVALID_REQUEST','Input digest mismatch')
        output = Path(request['artifact_dir']).resolve()
        if not output.is_dir() or Path(request_path).resolve().parent != output/'native' or Path(response_path).resolve().parent != output/'native':
            raise ModuleError('INVALID_REQUEST','Native request/response must share the runtime-owned artifact directory')
        if type(request['max_cells']) is not int or not 1 <= request['max_cells'] <= (150000 if operation is not None else 50000) or type(request['threads']) is not int or request['threads'] != 1:
            raise ModuleError('RESOURCE_LIMIT','Native operational limits exceeded')
        if request.get('benchmark') not in (None,'parallel_plate'):
            raise ModuleError('INVALID_REQUEST','Unknown harness benchmark')
        os.environ['OMP_NUM_THREADS'] = '1'
        os.environ['OPENBLAS_NUM_THREADS'] = '1'
        os.environ['XDG_CACHE_HOME'] = str(output/'native/cache')
        os.environ['MPLCONFIGDIR'] = str(output/'native/cache/matplotlib')
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
        environment = probe()
        if not environment['ready'] or environment['versions']['fenics-dolfinx'] != '0.11.0':
            raise ModuleError('BACKEND_UNAVAILABLE','Reviewed DOLFINx 0.11.0 environment is required')
        if operation is not None:
            from device_fem.extended.runner import run
        else:
            from device_fem.fenicsx import run
        write_json(output/'input.normalized.json',payload)
        write_json(output/'method_environment.json',environment)
        if operation is not None:
            if request.get('benchmark') is not None: raise ModuleError('INVALID_REQUEST','Extended device operation does not accept harness benchmark')
            results,diagnostics,warnings=run(payload,output,request['max_cells'])
            from device_fem.extended_contract import validate_result
        else:
            results, diagnostics, warnings = run(payload,output,request['max_cells'],
                                                 benchmark=request.get('benchmark') == 'parallel_plate')
            from device_fem.validation import validate_result
        validate_result(results,payload)
        write_json(output/'metrics.json',results)
        write_json(output/'scientific_core.json', _core.provenance())
        artifacts = []
        media = {'.json':'application/json','.msh':'application/vnd.gmsh','.vtu':'application/xml','.png':'image/png','.xdmf':'application/xml','.h5':'application/x-hdf5','.npz':'application/octet-stream'}
        for path in sorted(output.rglob('*')):
            if not path.is_file() or 'native' in path.relative_to(output).parts:
                continue
            artifacts.append({'path':'artifacts/'+path.relative_to(output).as_posix(),
                              'media_type':media.get(path.suffix,'application/octet-stream'),
                              'description':'Native scientific evidence: '+path.name,
                              'sha256':file_hash(path)})
        result = {'schema_version':'fea.science-result.v1','status':'succeeded',
                  'input_sha256':digest(payload),'results':results,'diagnostics':diagnostics,
                  'environment':environment,'warnings':warnings,'artifacts':artifacts}
        write_json(response_path,result)
        return 0
    except Exception as exc:
        failure = {'schema_version':'fea.science-result.v1','status':'failed',
                   'code':getattr(exc,'code','SCIENTIFIC_EXCEPTION'),'message':str(exc),
                   'traceback':traceback.format_exc()}
        write_json(response_path,failure)
        print(failure['traceback'],file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe',action='store_true')
    parser.add_argument('--request',type=Path)
    parser.add_argument('--response',type=Path)
    args = parser.parse_args()
    if args.probe:
        if args.request or args.response:
            parser.error('probe accepts no request/response files')
        print(dumps(probe()))
        return 0
    if not args.request or not args.response:
        parser.error('--request and --response are required')
    return execute(args.request,args.response)


if __name__ == '__main__':
    raise SystemExit(main())
