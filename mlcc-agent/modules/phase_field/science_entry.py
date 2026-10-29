"""Fixed WSL scientific entry; no public task state management."""
import argparse
import os
from pathlib import Path
import sys
from runpy import run_path
_core = run_path(str(Path(__file__).resolve().parents[2] / 'scientific_core/bootstrap.py'))['load'](
    __file__, required_version='0.1.0')
sys.dont_write_bytecode=True
from phasefield.common import read_json,write_json,dumps

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--probe',action='store_true');ap.add_argument('--request');ap.add_argument('--response');a=ap.parse_args()
    # Probe imports only; never creates cache/task or invokes a solve.
    if a.probe:
        from phasefield.science import environment
        print(dumps(environment()));return
    q=read_json(a.request)
    if q['schema_version']!='phase_field.science-request.v1':raise ValueError('Invalid native request')
    out=Path(q['artifact_dir'])
    for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:os.environ[k]=str(q['threads'])
    cache=out/'native'/'.cache';cache.mkdir(exist_ok=False)
    os.environ['XDG_CACHE_HOME']=str(cache)
    try:
        if q.get('operation')=='dielectric_tangent':
            from phasefield.tangent_science import compute
            result=compute(q,_core)
        elif isinstance(q.get('operation'),str) and q['operation'].startswith('vector_'):
            from phasefield.vector_science import compute
            result=compute(q,_core)
        else:
            from phasefield.science import compute
            result=compute(q)
    except Exception as e:
        import traceback
        traceback.print_exc()
        write_json(a.response,{'status':'failed','code':'NATIVE_SCIENCE_ERROR','message':str(e)});raise SystemExit(1)
    write_json(a.response,result)

if __name__=='__main__':main()
