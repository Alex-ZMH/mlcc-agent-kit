"""Scientific execution only; imported inside existing WSL environment."""
from pathlib import Path
import platform
import sys
import time
import resource
import xml.etree.ElementTree as ET
import numpy as np
import h5py
import dolfinx
import ufl
from dolfinx import fem,io
from mpi4py import MPI
from petsc4py import PETSc
from .kernel import PhaseField,integral
from .initial_conditions import initial_condition
from .validation import validate_input,initial_config
from .common import read_json,write_json,digest,file_hash,dumps


def environment():
    return {'ready':True,'versions':{'fenics-dolfinx':dolfinx.__version__,'ufl':ufl.__version__,
            'python':platform.python_version(),'petsc':'.'.join(map(str,PETSc.Sys.getVersion())),
            'numpy':np.__version__,'mpi':MPI.Get_library_version().strip()},
            'ranks':MPI.COMM_WORLD.size,'python':sys.executable,'method':'CG1 mixed P/phi, Newton line search, preonly/LU; RT0 MUMPS optional'}


def gradients(s):return [float(np.sqrt(integral(s.p.dx(i)**2*s.dx)/s.volume)) for i in range(s.dimension)]


def readback(out,dimension):
    """Compare every stored accepted P/phi frame and final DG0 E, not just PNG."""
    with np.load(out/'fields.npz') as z:
        for k in z.files:
            if z[k].dtype.kind in 'fci' and not np.all(np.isfinite(z[k])):raise ValueError('Nonfinite native array '+k)
        xml=ET.parse(out/'fields.xdmf');errors={};times=z['times'].tolist()
        with h5py.File(out/'fields.h5','r') as h5:
            def array(item):
                name,key=item.text.strip().split(':',1)
                if name!='fields.h5':raise ValueError('Unexpected XDMF link')
                return h5[key][...]
            coords=array(xml.find('.//Geometry/DataItem'));cells=array(xml.find('.//Topology/DataItem'))
            lookup={tuple(np.round(c[:dimension],10)):i for i,c in enumerate(z['coordinates'])}
            permutation=[lookup[tuple(np.round(c,10))] for c in coords]
            for name in ['P','phi']:
                attrs=xml.findall(f'.//Attribute[@Name="{name}"]/DataItem')
                if len(attrs)!=len(times):raise ValueError('History frame count mismatch')
                errors[name]=max(float(np.max(abs(array(a).reshape(-1)-z[name+'_history'][i][permutation]))) for i,a in enumerate(attrs))
                if not np.array_equal(z[name],z[name+'_history'][-1]):raise ValueError('Final field/history mismatch')
            centers=np.mean(coords[cells],axis=1)
            e_lookup={tuple(np.round(c[:dimension],10)):e for c,e in zip(z['E_coordinates'],z['E'])}
            expected=np.array([e_lookup[tuple(np.round(c,10))] for c in centers])
            saved=array(xml.findall('.//Attribute[@Name="E"]/DataItem')[-1])
            errors['E']=float(np.max(abs(saved[:,:dimension]-expected)))
            key='tetrahedra' if dimension==3 else 'triangles'
            if z[key].shape!=cells.shape or cells.shape[1]!=dimension+1:raise ValueError('Topology shape mismatch')
            if not np.allclose(coords.min(axis=0),[-8,0,-2] if dimension==3 else [-8,0]) or not np.allclose(coords.max(axis=0),[8,4,2] if dimension==3 else [8,4]):raise ValueError('Domain mismatch')
        with io.XDMFFile(MPI.COMM_WORLD,str(out/'fields.xdmf'),'r') as f:m=f.read_mesh(name='mesh')
        return {'passed':bool(max(errors.values())<1e-12 and m.topology.dim==dimension and len(cells)==m.topology.index_map(dimension).size_global),
                'dimension':dimension,'cells':len(cells),'history_frames':len(times),'max_errors':errors,'times':times}


def plots(out,data,dimension,history):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    coords=data['coordinates'];mask=np.ones(len(coords),dtype=bool)
    if dimension==3:
        plane=float(coords[np.argmin(abs(coords[:,2])),2]);mask=np.isclose(coords[:,2],plane)
    label='2D full domain' if dimension==2 else f'3D nodal slice z={plane:g} (not full volume)'
    for name in ['P','phi']:
        fig,ax=plt.subplots(figsize=(8,3));im=ax.tricontourf(coords[mask,0],coords[mask,1],data[name][mask],levels=24)
        fig.colorbar(im,ax=ax,label=name+' [dimensionless]');ax.set(xlabel='x [dimensionless]',ylabel='y [dimensionless]',title=label);ax.set_aspect('equal');fig.tight_layout();fig.savefig(out/(name+'.png'),dpi=130);plt.close(fig)
    e=data['E_coordinates'];em=np.linalg.norm(data['E'],axis=1);mask=np.ones(len(e),dtype=bool)
    if dimension==3:
        plane=float(e[np.argmin(abs(e[:,2])),2]);mask=np.isclose(e[:,2],plane)
    fig,ax=plt.subplots(figsize=(8,3));im=ax.scatter(e[mask,0],e[mask,1],c=em[mask],s=12)
    fig.colorbar(im,ax=ax,label='|E| [dimensionless]');ax.set(xlabel='x [dimensionless]',ylabel='y [dimensionless]',title='DG0 cell values'+(f'; cell-center layer z={plane:g}' if dimension==3 else '; 2D full domain'));ax.set_aspect('equal');fig.tight_layout();fig.savefig(out/'E.png',dpi=130);plt.close(fig)
    fig,axes=plt.subplots(2,1,figsize=(7,5),sharex=True)
    axes[0].plot([h['t'] for h in history],[h['mean_P'] for h in history],'.-');axes[0].set_ylabel('mean P [dimensionless]')
    axes[1].plot([h['t'] for h in history],[h['potential'] for h in history],'.-');axes[1].set(xlabel='time [dimensionless]',ylabel='electric enthalpy\n[dimensionless]');fig.tight_layout();fig.savefig(out/'history.png',dpi=130);plt.close(fig)


def compute(q):
    p=validate_input(q['input'],q['operation']);out=Path(q['artifact_dir']);env=environment()
    context=q.get('unit_context')
    if context:
        from .scaling import to_dimensionless
        check_input,check_derived=to_dimensionless(context['canonical_si'])
        if digest(check_input)!=digest(p) or check_derived!=context['derived'] or digest(context['original_input'])!=context['original_input_sha256']:
            raise ValueError('SI mapping/input identity mismatch before solve')
    if env['versions']['fenics-dolfinx']!='0.11.0' or env['ranks']!=1:raise ValueError('Unsupported scientific environment')
    m=p['mesh'];start=time.perf_counter()
    s=PhaseField(n=m['nx'],ny=m['ny'],nz=m.get('nz'),g=p['g'],epsilon=p['epsilon'],field=p['applied_E'],initial=initial_condition(initial_config(p)))
    cells=s.m.topology.index_map(p['dimension']).size_global
    if cells>q['max_cells']:raise ValueError('Actual mesh exceeds host resource budget')
    ig=gradients(s);ip,iphi=s.fields()
    write_json(out/'initial.json',{'input':p,'effective_initial':initial_config(p),'P_gradient_rms':ig,'initial_phi_equilibrated':True})
    write_json(out/'environment.json',env)
    np.savez_compressed(out/'initial_fields.npz',coordinates=ip.function_space.tabulate_dof_coordinates(),P=ip.x.array.real,phi=iphi.x.array.real)
    try:
        if p['operation']=='steady':s.steady();s.record(0.)
        else:
            c=p['evolution'];s.evolve(c['end'],c['dt'],max_retries=c['max_halvings'])
    except Exception:
        s.save(out) # Retain last accepted state / full failed-attempt diagnostics.
        raise
    data=s.save(out);gauss=s.gauss(reconstruct=p['output']['rt0']);rb=readback(out,p['dimension'])
    if not rb['passed']:raise ValueError('Native field readback failed')
    warnings=[]
    if p['output']['images']:
        try:plots(out,data,p['dimension'],s.history)
        except Exception as exc:
            warnings.append('Plot export failed; solver evidence remains valid: '+str(exc));write_json(out/'plot_failure.json',{'error':str(exc)})
    pp,phi=s.fields()
    def stats(a):return {'min':float(np.min(a)),'max':float(np.max(a)),'mean':float(np.mean(a))}
    ps=stats(data['P']);ps['mean']=s.history[-1]['mean_P']
    phis=stats(data['phi']);phis['mean']=integral(s.phi*s.dx)/s.volume
    rejected=[l for l in s.logs if not l['converged']];accepted=[l for l in s.logs if l['converged']]
    r={'operation':p['operation'],'dimension':p['dimension'],'polarization_components':1,'polarization_axis':'y','model_profile':p['model_profile'],'units':'dimensionless',
       'mesh':{'cells':cells,'dofs':len(s.u.x.array),'P_dofs':len(pp.x.array),'phi_dofs':len(phi.x.array)},'environment':env,
       'time':{'completed':s.history[-1]['t'],'accepted_steps':len(s.history)-1 if p['operation']=='evolve' else 0,'rejected_steps':len(rejected),'nonlinear_solves':len(s.logs),'max_accepted_residual':max(l['residual'] for l in accepted)},
       'fields':{'P':ps,'phi':phis,'E_magnitude':stats(np.linalg.norm(data['E'],axis=1)),'P_gradient_rms':gradients(s),'initial_P_gradient_rms':ig},
       'electric_enthalpy':s.history[-1]['potential'],'wall':{'centerline_unique_x':s.history[-1]['wall_x'],'meaning':'Unique crossing on y=2 (and z=0 in 3D) only; null if absent/ambiguous/unresolved. Not a global wall position.'},
       'gauss':gauss,'readback':rb,'artifact_refs':[]}
    write_json(out/'diagnostics.json',{'seconds':time.perf_counter()-start,'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'gauss':gauss,'readback':rb})
    # Finite logs/JSON are mandatory; fail closed rather than replacing NaN with a plausible value.
    dumps(r);dumps(read_json(out/'nonlinear.json'))
    if context:
        from .si_export import export_si
        warnings.extend(export_si(out,data,s.history,r,context,p['output']['images']))
    from scientific_core import provenance
    write_json(out/'scientific_core.json',provenance())
    hashes={'artifacts/'+f.relative_to(out).as_posix():file_hash(f) for f in out.rglob('*') if f.is_file() and 'native' not in f.relative_to(out).parts}
    r['artifact_refs']=sorted(hashes)
    write_json(out/'metrics.json',r);hashes['artifacts/metrics.json']=file_hash(out/'metrics.json')
    return {'status':'succeeded','task_id':q['task_id'],'input_sha256':digest(p),'results':r,'hashes':hashes,'warnings':warnings,
            'unit_mapping_sha256':digest(context) if context else None,'original_input_sha256':context['original_input_sha256'] if context else None}
