"""Return each saved FD equilibrium to its original bias using a real solve."""
from pathlib import Path
import json,sys,numpy as np
from .kernel import TangentSystem,write
def load_state(folder):
    folder=Path(folder);z=np.load(folder/'fields.npz');return {'u':z['mixed_state'].copy(),'field':z['bias'].copy(),'mesh_id':str(z['mesh_id']),'path':json.loads((folder/'loading_path.json').read_text())}
def run(root):
    root=Path(root);rows=[]
    for f in sorted(root.rglob('fd_validation.json')):
        center=f.parent;spec=json.loads((center/'config.json').read_text());s=TangentSystem(**spec);reference=load_state(center);fd=json.loads(f.read_text());cases=[]
        for row in fd['rows']:
            for b in row['branch_checks']:
                perturbed=center.parent/b['folder'];s.restore(load_state(perturbed));s.solve(reference['field'],append=False);error=float(np.max(abs(s.u.x.array-reference['u'])));cases.append({'folder':b['folder'],'return_bias':reference['field'].tolist(),'maximum_state_return_error':error,'residual':s.residual(),'status':'PASS' if error<1e-7 else 'FAIL'})
        data={'status':'PASS' if all(r['status']=='PASS' for r in cases) else 'FAIL','cases':cases,'method':'start from each actual saved nonlinear + or - equilibrium, reset only voltage to center, solve full nonlinear static equations, compare stored center; no sensitivity or linear predictor'};write(center/'branch_reversibility.json',data);rows.append({'center':center.relative_to(root).as_posix(),'status':data['status'],'count':len(cases),'maximum_state_return_error':max(r['maximum_state_return_error'] for r in cases)})
    result={'status':'PASS' if rows and all(r['status']=='PASS' for r in rows) else 'FAIL','rows':rows};write(root/'branch_reversibility.json',result);print('Branch reversibility',result['status'],flush=True)
    if result['status']!='PASS':raise RuntimeError('FD left original reversible branch')
if __name__=='__main__':run(sys.argv[1])
