"""Physics-independent two-load workflow and tensor/energy verification."""
from pathlib import Path
import numpy as np
from .fem_common import write

def homogenize(rve,adapter,root,bc='periodic',void_mode='explicit',dense=False):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    D=rve.mesh.geometry.dim;names=['x','y','z'][:D];loads=[adapter.solve_load_case(rve,g,bc,root/name,void_mode,dense) for name,g in zip(names,np.eye(D))]
    flux=np.array([r['mean_flux'] for r in loads]).T;avg=np.array([r['mean_driving_field'] for r in loads]).T
    # Full material domain average equals imposed G. With a true hole, use
    # full-cell macro G, not the smaller solid-only gradient average.
    C=flux if void_mode=='insulating_cavity' else flux@np.linalg.inv(avg)
    asym=float(np.linalg.norm(C-C.T)/np.linalg.norm(C));eig=np.linalg.eigvalsh((C+C.T)/2)
    checks={'finite_tensor':bool(np.isfinite(C).all()),'symmetry':asym<1e-8,'positive_definite':bool(min(eig)>0),
        'mean_driving_field':max(r['average_field_relative_error'] for r in loads)<1e-8,
        'Hill_Mandel':max(r['Hill_Mandel_relative_error'] for r in loads)<1e-8,
        'weak_PDE':max(r['weak_projected_residual'] for r in loads)<1e-8,
        'PBC_pairing':all(r['PBC_fluctuation_relative_error']<1e-10 and r['PBC_boundary_reaction_antiperiodicity']<1e-8 for r in loads) if bc=='periodic' else True}
    materials=adapter.prepare_materials(rve)[1]
    data={'schema_version':'rve.effective-property.v1','dimension':D,'rve_id':rve.micro['rve_id'],'geometry_version':'periodic_3d_convex_offset_v02','mesh_id':rve.diagnostics['mesh_id'],
      'physics':adapter.name,'boundary_condition':bc,'void_mode':void_mode,'homogenized_property':{'name':adapter.property_name,'representation':f'tensor_{D}x{D}','units':adapter.output_unit,'values':C.tolist()},
      'relative_permittivity_tensor':(C/adapter.factor).tolist() if adapter.name=='electrostatics' else None,
      'phase_fractions':rve.diagnostics['fraction_by_region'],'region_mapping':rve.micro['regions'],'materials':materials,'loads':loads,
      'verification':{'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'symmetry_relative':asym,'eigenvalues':eig.tolist()},
      'applicability':'Synthetic linear 3D volume, no calibrated BaTiO3 recipe or uncomputed z component; no device integration.',
      'artifact_paths':{'microstructure':str(rve.root/'microstructure.json'),'mesh':str(rve.root/'mesh_normalized.msh'),'loads':[name+'/fields.vtu' for name in names]}}
    write(root/'effective_tensor.json',data);print(root.name,adapter.name,bc,data['verification']['status'],(C/adapter.factor).tolist(),flush=True)
    if data['verification']['status']!='PASS':raise RuntimeError('homogenization verification failed')
    return data
