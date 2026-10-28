"""Standalone dimensionless response bundle; no RVE/runtime integration."""
from pathlib import Path
import json,sys,math
import numpy as np
def run(root):
    root=Path(root);readback=json.loads((root/'readback.json').read_text());responses=[]
    for f in sorted(root.rglob('tensor.json')):
        r=json.loads(f.read_text())
        if 'total_tangent_permittivity' not in r:continue
        case=f.parent;cfg=json.loads((case/'config.json').read_text());D=r['dimension'];z=np.load(case/'fields.npz');entry=dict(r);entry.update(schema_version='mlcc.tangent-dielectric-experiment.v1',source_folder=case.relative_to(root).as_posix(),source_fields='fields.npz / fields.vtu / fields.xdmf',initial_state=cfg['initial'] if cfg['initial'] is not None else ('prescribed wall profile' if cfg['kind'].startswith('wall') else [1.]+[0.]*(D-1)),parameters={'a':-.5,'b':.25,'c':1.5,'g':.5,'epsilon':1.,'mobility':1.,**cfg['parameters']},geometry_bounds={'min':z['coordinates'][:,:D].min(axis=0).tolist(),'max':z['coordinates'][:,:D].max(axis=0).tolist()},background_coefficient=cfg['parameters'].get('epsilon',1.),response_class='finite_fixed_end_multidomain_apparent_response' if cfg['kind'].startswith('wall') else 'uniform_branch_local_response')
        entry['field_readback']=readback['results'][case.relative_to(root).as_posix()];entry['fd_validation']=entry.get('fd_validation',{'status':'NOT_CHECKED','reason':'this point is not one of the independent FD benchmark states'})
        entry['mesh_convergence']={'status':'NOT_CHECKED','reason':'point-specific mesh series not executed; use stated benchmark series only'}
        if (root/'sensitivity.json').exists():
            m=json.loads((root/'sensitivity.json').read_text());matches=[v for v in m['rows'] if v['family']==f'd{D}_wall' and cfg['kind'] in ['wall_90xy','wall_90xz'] or v['family']==f'd{D}_uniform' and 'cross' in case.name]
            if matches:entry['mesh_convergence']={'status':m['status'],'scope':'same named normal-grid benchmark; transverse refinement separately reported','rows':matches,'summary_file':'sensitivity.json'}
        if (case/'branch_reversibility.json').exists():entry['fd_branch_return']=json.loads((case/'branch_reversibility.json').read_text())
        if entry['validation_status']=='computed_pending_independent_validation':entry['validation_status']='PARTIAL';entry['validation_note']='raw AD computation and independent residuals available; standalone point lacks full analytic/FD validation'
        assert np.array(entry['total_tangent_permittivity']).shape==(D,D)
        assert np.isfinite(np.array(entry['total_tangent_permittivity'])).all()
        assert entry['tensor_units'].startswith('dimensionless')
        responses.append(entry)
    result={'schema_version':'mlcc.tangent-dielectric-experiment.bundle.v1','integration_status':'standalone only; no RVE/Agent/runtime registration','units':'dimensionless absolute D/E; SI and relative permittivity unavailable without P0/E0','count':len(responses),'responses':responses};(root/'material_responses.json').write_text(json.dumps(result,indent=2,allow_nan=False));print('response bundle',len(responses),flush=True);return result
if __name__=='__main__':run(sys.argv[1])
