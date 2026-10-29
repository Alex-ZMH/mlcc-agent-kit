"""Trusted isolated WSL entry. Probe runs no circuit and creates no files."""
import argparse
import importlib.util
from pathlib import Path
import sys
import os

sys.dont_write_bytecode = True
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[key] = '1'
root = Path(__file__).resolve().parent/'spice_module'
spec = importlib.util.spec_from_file_location('spice_module', root/'__init__.py', submodule_search_locations=[str(root)])
package = importlib.util.module_from_spec(spec)
sys.modules['spice_module'] = package
spec.loader.exec_module(package)
from spice_module.common import read_json, write_json, dumps

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--probe', action='store_true')
    p.add_argument('--ngspice')
    p.add_argument('--request', type=Path)
    p.add_argument('--response', type=Path)
    a = p.parse_args()
    from spice_module.science import probe, execute
    if a.probe:
        print(dumps(probe(a.ngspice)))
    else:
        try:
            r = execute(read_json(a.request))
            write_json(a.response, r)
        except Exception as e:
            import traceback
            a.response.with_suffix('.failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
            write_json(a.response, {'status':'failed', 'code':getattr(e,'code','SCIENTIFIC_EXECUTION_FAILED'), 'message':str(e)})
            raise SystemExit(1)
