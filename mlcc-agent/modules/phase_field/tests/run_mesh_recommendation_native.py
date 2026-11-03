"""Explicit real native Adapter regressions; no scheduler or existing task access."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from test_mesh_recommendation import CASES, MODULE, example
BUNDLE=MODULE.parents[1]


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def run_case(output,name,operation,mode=None):
    case=output/name;case.mkdir(parents=True,exist_ok=False);payload=case/'payload'
    for rel in ('src/mlcc/units.py','scientific_core','modules/phase_field'):
        source,target=BUNDLE/rel,payload/rel;target.parent.mkdir(parents=True,exist_ok=True)
        if source.is_dir():shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc','tests'))
        else:shutil.copy2(source,target)
    p=example(operation);p['output']['images']=False
    recommended=1
    if mode=='scalar-above-cell-and-axis':
        p['mesh']={'nx':49,'ny':64};p['output']['rt0']=False;recommended=6000
    elif mode=='scalar-above-z':
        p['dimension']=3;p['mesh']={'nx':8,'ny':8,'nz':13};p['output']['rt0']=False
    elif mode=='vector-above-dof':
        p['cells']=[92,92];p['initial_condition']={'kind':'uniform','values':[1.,0.]}
        p['field_protocol']={'kind':'constant','value':[0.,0.]};p['evolution']['end']=0
        recommended=6000
    elif mode in ('tangent-above-dof','tangent-above-axis'):
        p['cells']=[33,33] if mode=='tangent-above-dof' else [129,2]
        p['loading_path']=[[0.,0.]];p['verification']={'finite_difference':False,'analytical':True}
        recommended=6000
    deployment={'schema_version':'phase_field.deployment.native.v1','transport':'native_linux',
                'python':sys.executable,'linux_root':str(case),'timeout_seconds':240,'threads':1,
                'max_cells':recommended,'max_work':1,'max_history_bytes':1}
    write(case/'deployment.json',deployment)
    env=dict(os.environ,MLCC_FEA_DEPLOYMENT=str(case/'deployment.json'),
             MLCC_PHASE_FIELD_DEPLOYMENT=str(case/'deployment.json'),PYTHONDONTWRITEBYTECODE='1',
             OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    request={'schema_version':'mlcc.adapter-request.v1','interface_version':'1.0',
             'module_id':'phase_field','operation':operation,'action':'preflight',
             'input':p,'task_id':None,'artifact_dir':None}
    command=[sys.executable,'-B',str(payload/'modules/phase_field/adapter.py')]
    def invoke(label):
        write(case/(label+'-request.json'),request)
        r=subprocess.run(command,input=json.dumps(request),capture_output=True,text=True,env=env,timeout=280)
        (case/(label+'-stderr.log')).write_text(r.stderr,encoding='utf-8')
        response=json.loads(r.stdout);write(case/(label+'-response.json'),response);return response
    start=time.monotonic();pre=invoke('preflight');assert pre.get('ready'),pre
    out=case/'artifacts';out.mkdir();request.update(action='execute',task_id=name,artifact_dir=str(out))
    result=invoke('execute');assert result.get('execution_status')=='succeeded',result.get('errors')
    advisory=json.loads((out/'mesh_recommendation.json').read_text(encoding='utf-8'))
    assert advisory['enforced'] is False
    assert any('advisory only' in w for w in result['warnings']),result['warnings']
    assert not any(c['status']=='failed' for c in result['quality']['numerical']),result['quality']
    if mode=='scalar-above-cell-and-axis':assert advisory['actual']['cells']>6000
    if mode=='vector-above-dof':assert advisory['actual']['dofs']>25000
    if mode=='tangent-above-dof':assert advisory['actual']['dofs']>3300
    if mode=='tangent-above-axis':assert advisory['actual']['axis_cells'][0]>128
    summary={'name':name,'operation':operation,'execution':'succeeded','mesh_advisory':advisory,
             'quality':result['quality'],'warnings':result['warnings'],'seconds':time.monotonic()-start}
    write(case/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ('name','mesh_advisory','seconds')}),flush=True)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--case',action='append');args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    cases=[(op,op,None) for op in CASES]+[
        ('scalar-above-cell-and-axis','steady','scalar-above-cell-and-axis'),
        ('scalar-above-z','steady','scalar-above-z'),('vector-above-dof','vector_steady','vector-above-dof'),
        ('tangent-above-dof','dielectric_tangent','tangent-above-dof'),
        ('tangent-above-axis','dielectric_tangent','tangent-above-axis')]
    selected=set(args.case or [row[0] for row in cases]);assert selected<={row[0] for row in cases}
    report={'cases':[],'python':sys.executable}
    try:
        for name,op,mode in cases:
            if name in selected:report['cases'].append(run_case(output,name,op,mode))
    finally:write(output/'summary.json',report)


if __name__=='__main__':main()
