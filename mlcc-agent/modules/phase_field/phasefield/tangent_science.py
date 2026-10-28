"""Scientific-process orchestration of reviewed static AD extraction; no BE dynamics."""
from pathlib import Path
import numpy as np
from .common import ROOT,digest,read_json,write_json,file_hash
from .tangent_input import validate_reduced,reduce_si
from .tangent_views import result_view
from .vector_input import require
from .science import environment
from .tangent.kernel import TangentSystem,InvalidTangent,write
from .tangent.validation import validate_case
from .tangent.readback import run as readback
from .tangent.branch_reversibility import run as branch_return
from .tangent.export import run as export

def physical_files(out,context,d):
    import pyvista as pv
    folder=out/'si';folder.mkdir(exist_ok=False);f=context['derived']['factors'];scale=context['derived']['tensor_factor_F_per_m']
    with np.load(out/'equilibrium/fields.npz',allow_pickle=False) as z:a={k:z[k].copy() for k in z.files}
    for key,factor in [('coordinates',f['length']),('P',f['polarization']),('phi',f['potential']),('psi',f['potential']),('bias',f['electric_field'])]:a[key]*=factor
    for i,ids in enumerate(a['maps']):a['mixed_state'][ids]*=f['polarization'] if i<d else f['potential']
    a['mass_volume']*=f['length']**d
    if 'sensitivities' in a:
        for i,ids in enumerate(a['maps']):a['sensitivities'][:,ids]*=scale if i<d else f['length']
    require(all(np.isfinite(v).all() for v in a.values() if np.issubdtype(v.dtype,np.number)),'Nonfinite SI fields','INVALID_SCALES')
    np.savez_compressed(folder/'fields_si.npz',**a)
    grid=pv.read(out/'equilibrium/fields.vtu');grid.points*=f['length']
    for key in grid.point_data:
        factor=scale if key.startswith('dP') else f['length'] if key.startswith('dphi_') else f['potential'] if key in ('phi','psi') else f['polarization']
        grid.point_data[key]*=factor
    for key in grid.cell_data:grid.cell_data[key]*=1 if key.startswith('dE_') else f['electric_field'] if key=='E' else f['polarization']
    grid.save(folder/'fields_si.vtu');again=pv.read(folder/'fields_si.vtu')
    with np.load(folder/'fields_si.npz',allow_pickle=False) as z:
        checks={k:bool(np.array_equal(z[k],v)) for k,v in a.items()}
        checks.update(VTU_coordinates=bool(np.array_equal(again.points,z['coordinates'])),VTU_P=bool(np.array_equal(again.point_data['P'][:,:d],z['P'])),VTU_phi=bool(np.array_equal(again.point_data['phi'],z['phi'])))
    write_json(folder/'readback.json',{'passed':all(checks.values()),'checks':checks});require(all(checks.values()),'SI field roundtrip failed','INVALID_SCIENTIFIC_RESULT')
    write_json(folder/'mapping.json',context)
    write_json(folder/'fields_units.json',{'coordinates':'m','P':'C/m^2','phi':'V','psi':'V','bias':'V/m','E':'V/m','D':'C/m^2',
        'polarization_sensitivity':'F/m','potential_sensitivity':'m','E_sensitivity':'dimensionless',
        'tensor':'F/m','mixed_state':'P component C/m^2, psi component V; use explicit maps','mass_volume':'m^dimension',
        'maps_cells_constraints':'unscaled dimensionless integer indices','relative_permittivity':'not produced; no implicit epsilon0'})

def figures(out,result):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fields=result['tensors_si'] or result['tensors_dimensionless'];d=result['dimension'];fig,axes=plt.subplots(1,3,figsize=(11.8,3.7),layout='constrained')
    for ax,key,label in zip(axes,['total_tangent_permittivity','background_permittivity','polarization_tangent_contribution'],['Total d<D>/dE','Background contribution','Polarization contribution']):
        a=np.array(fields[key]);m=max(abs(a).max(),1e-30);im=ax.imshow(a,cmap='RdBu_r',vmin=-m,vmax=m)
        for i in range(d):
            for j in range(d):ax.text(j,i,f'{a[i,j]:.5g}',ha='center',va='center',fontsize=9,color='white' if abs(a[i,j])>.65*m else 'black')
        ax.set(xticks=range(d),xticklabels=list('xyz'[:d]),yticks=range(d),yticklabels=list('xyz'[:d]),xlabel='Applied field direction j',ylabel='Displacement component i',title=label);fig.colorbar(im,ax=ax,shrink=.8)
    fig.suptitle('Static branch-local tangent ['+('F/m' if result['tensors_si'] else 'dimensionless absolute D/E')+']; no material calibration',fontsize=10)
    fig.savefig(out/'tangent_tensor.png',dpi=150,bbox_inches='tight');plt.close(fig)

def compute(q,core):
    p=validate_reduced(q['input']);context=q['unit_context'];out=Path(q['artifact_dir']);d=p['dimension']
    require(q['operation']=='dielectric_tangent' and digest(p)==q['input_sha256'] and q['threads']==1,'Native static input identity mismatch','INVALID_REQUEST')
    if context:
        pp,derived=reduce_si(context['canonical_si']);require(pp==p and derived==context['derived'] and digest(context['original_input'])==context['original_input_sha256'],'Native UNIT identity mismatch','INVALID_SCIENTIFIC_RESULT')
    env=environment();require(env['ranks']==1 and env['versions']['fenics-dolfinx']=='0.11.0','Reviewed single-rank DOLFINx required','BACKEND_UNAVAILABLE')
    write_json(out/'environment.json',env);write_json(out/'input.solver-dimensionless.json',p);write_json(out/'scientific_core.json',core.provenance())
    initial=p['initial_condition'];options={'dimension':d,'cells':p['cells'],'parameters':p['parameters'],'kind':initial['kind'],
        'initial':initial.get('values'),'atol':p['equilibrium_atol']}
    if 'wall_half_length' in p:options['wall_half_length']=p['wall_half_length']
    s=TangentSystem(**options)
    require(s.base.m.topology.index_map(d).size_global<=q['max_cells'],'Actual mesh exceeds host limit','RESOURCE_LIMIT')
    try:
        for bias in p['loading_path']:s.solve(bias)
        response=validate_case(s,out/'equilibrium',fd=p['verification']['finite_difference'],analytical=p['verification']['analytical'])
        response['physics_model_version']='0.3';write(out/'equilibrium/tensor.json',response)
        require(response['validation_status']=='PASS','Requested native tangent checks failed','INVALID_SCIENTIFIC_RESULT')
    except InvalidTangent as exc:
        diagnostic={'validation_status':'NOT_VALID','reason':str(exc),'dimension':d,'stability_diagnostics':s.stability()}
        s.save(out/'rejected_state',diagnostic);write_json(out/'rejection.json',diagnostic)
        write_json(out/'material_responses.json',{'schema_version':'mlcc.tangent-dielectric-experiment.bundle.v1','count':0,'responses':[],
            'integration_status':'Rejected static state; no valid material tensor exported','units':'dimensionless'})
        return {'status':'rejected','task_id':q['task_id'],'input_sha256':digest(p),'reason':str(exc)}
    rb=readback(out);require(rb['status']=='PASS','Independent saved-field tangent readback failed','INVALID_SCIENTIFIC_RESULT')
    if p['verification']['finite_difference']:branch_return(out)
    bundle=export(out);require(bundle['count']==1,'One equilibrium response required','INVALID_SCIENTIFIC_RESULT')
    bundle['integration_status']='phase_field module; no automatic RVE/FEM/SPICE transfer'
    write(out/'material_responses.json',bundle);response=bundle['responses'][0]
    require(response['validation_status']=='PASS' and response['field_readback']['status']=='PASS','Response export admission failed','INVALID_SCIENTIFIC_RESULT')
    if p['verification']['finite_difference']:require(response['fd_branch_return']['status']=='PASS','FD center return failed','INVALID_SCIENTIFIC_RESULT')
    write_json(out/'response.dimensionless.json',response)
    checks=dict(response['checks']);checks['independent_readback']=True
    if p['verification']['finite_difference']:checks['branch_return']=True
    write_json(out/'native_checks.json',checks)
    if context:physical_files(out,context,d)
    # Build the authoritative summary only after all native checks and SI views.
    refs=['artifacts/'+f.relative_to(out).as_posix() for f in out.rglob('*') if f.is_file() and 'native' not in f.relative_to(out).parts]
    if p['output']['images']:refs.append('artifacts/tangent_tensor.png')
    refs.append('artifacts/summary.json');refs=sorted(set(refs));result=result_view(p,response,context,refs)
    if p['output']['images']:figures(out,result)
    write_json(out/'summary.json',result)
    return {'status':'succeeded','task_id':q['task_id'],'input_sha256':digest(p),'unit_mapping_sha256':digest(context) if context else None,
            'results':result,'checks':checks,'hashes':{ref:file_hash(out/ref.removeprefix('artifacts/')) for ref in refs}}
