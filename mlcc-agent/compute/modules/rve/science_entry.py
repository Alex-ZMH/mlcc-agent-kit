"""Fixed WSL science entry; only module package is bootstrapped under -I."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys
from runpy import run_path
_core = run_path(str(Path(__file__).resolve().parents[2] / 'scientific_core/bootstrap.py'))['load'](
    __file__, required_version='0.1.0')
sys.dont_write_bytecode=True
root=Path(__file__).resolve().parent/'rve_module'
spec=importlib.util.spec_from_file_location('rve_module',root/'__init__.py',submodule_search_locations=[str(root)])
package=importlib.util.module_from_spec(spec);sys.modules['rve_module']=package;spec.loader.exec_module(package)
from rve_module.common import dumps,read_json,write_json

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--probe',action='store_true');ap.add_argument('--request',type=Path);ap.add_argument('--response',type=Path);a=ap.parse_args()
    for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[key]='1'
    if a.probe:
        if a.request or a.response:ap.error('Probe takes no files')
        from rve_module.science import environment
        print(dumps(environment()));return
    if not a.request or not a.response:ap.error('request and response required')
    try:
        q=read_json(a.request);out=Path(q['artifact_dir']).resolve()
        if a.request.resolve().parent!=out/'native' or a.response.resolve().parent!=out/'native' or not out.is_dir():raise ValueError('Native paths must share runtime artifacts/native')
        cache=out/'native/cache';cache.mkdir(exist_ok=False)
        os.environ['XDG_CACHE_HOME']=str(cache);os.environ['MPLCONFIGDIR']=str(cache/'matplotlib');os.environ['TMPDIR']=str(cache)
        from rve_module.science import compute
        result=compute(q);write_json(a.response,result)
    except Exception as e:
        import traceback
        traceback.print_exc();write_json(a.response,{'status':'failed','code':getattr(e,'code','SCIENCE_ERROR'),'message':str(e),'traceback':traceback.format_exc()});raise SystemExit(1)
if __name__=='__main__':main()
