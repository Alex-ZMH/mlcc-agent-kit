"""Non-computational deployment evidence. Never launches a scientific engine."""
import argparse
import json
import os
from pathlib import Path
import subprocess

def probe(module, binary, provider_python=None, source_root=None):
    path=Path(binary)
    result={'schema':'mlcc.environment-probe.v1','module_id':module,
            'scheduler_job_id':os.environ.get('SLURM_JOB_ID'),
            'binary':str(path),'binary_exists':path.is_file(),
            'binary_executable':os.access(path,os.X_OK),
            'scientific_execution':'not_requested','scientific_acceptance':'not_checked',
            'native_engine_start':'not_checked','factory_import':{'status':'not_checked'}}
    if provider_python and source_root:
        provider='mlcc.abacus_tasks' if module=='dft' else 'mlcc.lammps_tasks'
        code='import sys,importlib;sys.path.insert(0,sys.argv[1]);importlib.import_module(sys.argv[2]);print("factory_import_ok")'
        process=subprocess.run([provider_python,'-I','-c',code,str(source_root),provider],capture_output=True,text=True,timeout=30)
        result['factory_import']={'status':'passed' if process.returncode==0 else 'failed',
                                  'returncode':process.returncode,'stdout':process.stdout,'stderr':process.stderr}
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module',choices=('dft','md'),required=True)
    parser.add_argument('--binary',required=True)
    parser.add_argument('--provider-python')
    parser.add_argument('--source-root')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=probe(args.module,args.binary,args.provider_python,args.source_root)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
    accepted=(result['binary_exists'] and result['binary_executable']
              and result['factory_import']['status'] in ('passed','not_checked'))
    raise SystemExit(0 if accepted else 1)
