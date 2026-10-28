"""Isolated Linux orchestration of migrated kernels and independent native readback."""
import importlib
import os
from pathlib import Path
import sys
from .common import ROOT,read_json,write_json,file_hash,digest,validate_shape
from .contract import OPERATIONS,geometry,kernel_input,require,spd

def deployment_host(out):
    # Transport provenance only. The Adapter writes this trusted launch record
    # before execution; legacy standalone/WSL calls keep their original label.
    launch=Path(out)/'native/launch.json'
    binding=read_json(launch).get('deployment',{}) if launch.is_file() else {}
    return 'native Linux' if binding.get('transport')=='native_linux' else 'WSL'

def environment():
    import dolfinx,gmsh,numpy,ufl,h5py,pyvista
    from petsc4py import PETSc
    from mpi4py import MPI
    return {'ready':dolfinx.__version__=='0.11.0' and numpy.dtype(PETSc.ScalarType).name=='float64' and MPI.COMM_WORLD.size==1,'versions':{'dolfinx':dolfinx.__version__,'gmsh':gmsh.__version__,'numpy':numpy.__version__,'PETSc':'.'.join(map(str,PETSc.Sys.getVersion())),'ufl':ufl.__version__,'h5py':h5py.__version__,'pyvista':pyvista.__version__},'python':sys.version,'executable':sys.executable,'scalar_type':numpy.dtype(PETSc.ScalarType).name,'mpi_ranks':MPI.COMM_WORLD.size,'pid':os.getpid(),'threads':{k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')}}

def compute(q):
    require(set(q)=={'schema_version','input','input_sha256','operation','artifact_dir','max_cells','threads'} and q['schema_version']=='rve.science-request.v1','Invalid native envelope')
    c=q['input'];d,p=OPERATIONS[q['operation']];require(digest(c)==q['input_sha256'],'Native input hash mismatch')
    require(type(q['max_cells']) is int and 1<=q['max_cells']<=(90000 if d==2 else 180000) and type(q['threads']) is int and q['threads']==1,'Explicit bounded single-thread budget required')
    # Canonical numeric input is never fed back to the raw-unit converter.
    tags=geometry(c['geometry'],c['normalized_h'],d);require(set(c['materials'])==tags,'Native material coverage mismatch')
    for m in c['materials'].values():
        if 'tensor' in m:spd(m['tensor'],d)
        else:require(m['scalar']>0,'Native coefficient positive')
    out=Path(q['artifact_dir']);env=environment();write_json(out/'environment.json',env);require(env['ready'],'Unsupported backend')
    write_json(out/'native/process.json',{'pid':os.getpid(),'host':deployment_host(out),'state':'running','input_sha256':q['input_sha256']})
    prefix=f'rve_module.kernel{d}d'
    build=importlib.import_module(prefix+'.microstructure').build;create=importlib.import_module(prefix+'.rve_mesh').create
    physics=importlib.import_module(prefix+'.physics');homogenize=importlib.import_module(prefix+'.homogenization').homogenize
    checker=importlib.import_module(prefix+'.verify').check
    cfg,materials=kernel_input(c,d,p)
    write_json(out/'input.kernel-normalized.json',{'geometry':cfg,'normalized_h':c['normalized_h'],'materials':materials})
    coordinate={'schema_version':'rve.coordinates.v1','gmsh':'normalized dimensionless unit box','VTU_XDMF_HDF5_NPZ':'physical coordinates in m','physical_lengths_m':c['geometry']['physical_lengths'],'formula':'x_m[i] = x_normalized[i] * physical_lengths_m[i]','geometry_parameters':'normalized fractions/radii/widths unscaled','dimension':d,'macro_basis':'eye(d), G is E=1 V/m or negative grad(T)=1 K/m','potential_lifting':'u=-G.x+w','thermal_reference_K':300,'area_or_volume_normalization':'full cell including cavity','two_dimensional_depth':'not introduced; material tensor units unchanged'}
    write_json(out/'coordinates.json',coordinate)
    micro=build(cfg);rve=create(micro,c['normalized_h'],out/'geometry',max_cells=q['max_cells'])
    adapter=(physics.ElectrostaticAdapter if p=='electrostatics' else physics.ThermalAdapter)(materials)
    prop=homogenize(rve,adapter,out/'solution',bc=c['boundary_condition'],void_mode=c['pore_model'])
    loads=['xyz'[i] for i in range(d)];readback={name:checker(out/'solution'/name,prop) for name in loads}
    # Native readback reconstructs gradients, C*field, flux/work integrals and PBC;
    # never accepts a PASS string in effective_tensor.json as its own evidence.
    require(all(row['status']=='PASS' and all(v is True for v in row['checks'].values()) for row in readback.values()),'Independent field readback failed','NATIVE_READBACK_FAILED')
    write_json(out/'readback.json',readback)
    prop['artifact_paths']={'microstructure':'artifacts/geometry/microstructure.json','mesh':'artifacts/geometry/mesh_normalized.msh','loads':['artifacts/solution/'+n+'/fields.vtu' for n in loads]}
    # Rewrite only module-owned kernel output, never Runtime record.json.
    from .kernel3d.fem_common import write
    write(out/'solution/effective_tensor.json',prop)
    effective={'schema_version':'rve.effective-material.v1','dimension':d,'physics':p,'rve_id':micro['rve_id'],'mesh_id':rve.diagnostics['mesh_id'],'tensor':prop['homogenized_property']['values'],'tensor_unit':adapter.output_unit,'phase_fractions':prop['phase_fractions'],'region_mapping':micro['regions'],'materials':c['materials'],'boundary_condition':c['boundary_condition'],'pore_model':c['pore_model'],'loads':[{'direction':name,'G':row['load_G'],'drive_unit':row['drive_units'],'mean_field':row['mean_driving_field'],'mean_flux':row['mean_flux'],'micro_work_density':row['micro_work_density'],'macro_work_density':row['macro_work_density'],'field_artifact':f'artifacts/solution/{name}/fields.vtu','metrics_artifact':f'artifacts/solution/{name}/metrics.json'} for name,row in zip(loads,prop['loads'])],'coordinates_artifact':'artifacts/coordinates.json','verification_status':prop['verification']['status'],'applicability':'Synthetic linear static '+str(d)+'D; crystal orientations metadata only; no calibration, representativity or device validity','limitations':['single task mesh convergence not_checked','raw DG0 flux jumps diagnostic; no pointwise H(div) claim','thermal cavity excludes pore cells and uses full-cell average','3D GB/shell polycrystal refused'],'material_calibration':'not_checked','statistical_representativity':'not_checked'}
    audit=read_json(out/'unit_normalization.json')
    effective['material_sources']={tag:[rec['original']['source'] for key,rec in audit['records'].items() if key.startswith('/materials/'+row+'/')] for row,tag in audit['material_rows'].items()}
    effective['source_audit_artifact']='artifacts/unit_normalization.json'
    validate_shape(effective,read_json(ROOT/f'schemas/effective-material-{d}d-{p}.schema.json'));write_json(out/'effective_material.json',effective)
    result={'schema_version':'rve.result.v1','dimension':d,'physics':p,'rve_id':micro['rve_id'],'mesh_id':rve.diagnostics['mesh_id'],'tensor':prop['homogenized_property']['values'],'tensor_unit':adapter.output_unit,'boundary_condition':c['boundary_condition'],'pore_model':c['pore_model'],'cells':rve.diagnostics['cells'],'load_count':d,'effective_material_artifact':'artifacts/effective_material.json','readback_artifact':'artifacts/readback.json','coordinate_artifact':'artifacts/coordinates.json','load_fields':prop['artifact_paths']['loads'],'numerical_status':'PASS','scientific_applicability':'not_checked'}
    validate_shape(result,read_json(ROOT/f'schemas/{q["operation"]}.output.schema.json'));write_json(out/'metrics.json',result)
    diag={'mesh':rve.diagnostics,'verification':prop['verification'],'loads':[{key:row[key] for key in ('solver','average_field_relative_error','Hill_Mandel_relative_error','weak_projected_residual','PBC_fluctuation_relative_error','PBC_boundary_reaction_antiperiodicity')} for row in prop['loads']]};write_json(out/'diagnostics.json',diag)
    from scientific_core import provenance
    write_json(out/'scientific_core.json',provenance())
    artifacts=[]
    for path in sorted(out.rglob('*')):
        rel=path.relative_to(out)
        if not path.is_file() or 'native' in rel.parts:continue
        artifacts.append({'path':'artifacts/'+rel.as_posix(),'sha256':file_hash(path),'media_type':'application/json' if path.suffix=='.json' else 'application/octet-stream','description':'RVE native evidence: '+rel.as_posix()})
    write_json(out/'native/completion.json',{'pid':os.getpid(),'state':'computed_and_readback_complete','input_sha256':q['input_sha256']})
    return {'schema_version':'rve.science-result.v1','status':'succeeded','input_sha256':q['input_sha256'],'results':result,'diagnostics':diag,'environment':env,'artifacts':artifacts}
