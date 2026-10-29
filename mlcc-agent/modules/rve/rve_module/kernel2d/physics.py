"""Two explicit physical adapters over a shared, minimal linear elliptic cell kernel."""
from time import perf_counter
import resource
import numpy as np
import ufl
from dolfinx import fem,mesh
from dolfinx.fem.petsc import assemble_matrix,assemble_vector
from petsc4py import PETSc
from mpi4py import MPI
from .fem_common import scalar,dg,integral,ncells,write,export
from .rve_mesh import boundaries

EPS0=8.8541878128e-12

def constraints(V,L,bc):
    x=V.tabulate_dof_coordinates()[:,:2]/L;N=len(x);tol=1e-8;keys={}
    reduced=np.full(N,-1,np.int32);pairs=[];corners=[]
    if bc not in ['periodic','affine_dirichlet']:raise ValueError('explicit periodic or affine_dirichlet required')
    if bc=='periodic':
        canonical=x.copy();canonical[abs(canonical-1)<tol]=0
        key=lambda p:tuple(np.round(p,9))
        # Master coordinate must be present, not interpolated from a nearest neighbor.
        master={key(p):i for i,p in enumerate(x) if p[0]<1-tol and p[1]<1-tol}
        group=[]
        for i,p in enumerate(canonical):
            if key(p) not in master:raise ValueError('unmatched periodic P1 node: mesh is not periodic')
            j=master[key(p)];group.append(j)
            if abs(x[i,0]-1)<tol or abs(x[i,1]-1)<tol:pairs.append([i,j])
            if np.all((abs(x[i])<tol)|(abs(x[i]-1)<tol)):corners.append(i)
        if len(corners)!=4 or len(set(group[i] for i in corners))!=1:raise ValueError('corner equivalence invalid')
        gauge=group[corners[0]];masters=sorted(set(group)-{gauge});ids={k:i for i,k in enumerate(masters)}
        for i,j in enumerate(group):reduced[i]=ids.get(j,-1)
    else:
        interior=np.flatnonzero(np.all((x>tol)&(x<1-tol),axis=1));reduced[interior]=np.arange(len(interior));masters=interior
    nr=len(masters)
    if nr==0:raise ValueError('no unconstrained fluctuation DOFs')
    P=PETSc.Mat().createAIJ([N,nr],nnz=1,comm=MPI.COMM_WORLD)
    for i,j in enumerate(reduced):
        if j>=0:P.setValue(i,int(j),1.)
    P.assemble()
    return P,reduced,np.array(pairs,np.int32).reshape(-1,2),{'full_dofs':N,'reduced_dofs':nr,'slave_pairs':len(pairs),'corner_count':len(corners),'gauge':'one corner equivalence class removed, then volume mean(w)=0' if bc=='periodic' else 'w=0 all exterior square faces'}

def tensor_material(value):
    a=np.asarray(value,float)
    if a.shape==():a=np.eye(2)*a
    if a.shape!=(2,2) or not np.isfinite(a).all() or np.max(abs(a-a.T))>1e-12*max(np.linalg.norm(a),1e-30) or min(np.linalg.eigvalsh(a))<=0:raise ValueError('finite symmetric positive definite scalar/2x2 tensor required')
    return a

class PhysicsAdapter:
    def __init__(self,materials):self.materials=materials
    def prepare_materials(self,rve):
        if set(self.materials)!=set(rve.micro['regions']):raise ValueError('all and only actual regions require explicit materials')
        arrays=np.zeros((len(rve.labels),2,2));records={}
        for tag,entry in self.materials.items():
            if set(entry)!={'value','units','source','applicability'} or entry['units']!=self.input_unit or not entry['source'] or not entry['applicability']:raise ValueError('material units/source/applicability required')
            k=tensor_material(entry['value'])*self.factor;arrays[rve.labels==int(tag)]=k;records[tag]={**entry,'physical_tensor':k.tolist()}
        return arrays,records
    def solve_load_case(self,rve,G,bc,root,void_mode='explicit',dense=False):
        arrays,records=self.prepare_materials(rve);m=rve.mesh;labels=rve.labels;ft=rve.facets;mapping=np.arange(ncells(m),dtype=np.int32)
        if self.name!='thermal' and void_mode!='explicit':raise ValueError('electrostatic pore must be explicit epsilon, not zero/removed')
        if void_mode not in ['explicit','insulating_cavity']:raise ValueError('unknown pore physics')
        if void_mode=='insulating_cavity':
            selected=np.flatnonzero(labels!=9000).astype(np.int32)
            if len(selected)==len(labels):raise ValueError('no pore for insulating cavity')
            m,emap,_,_=mesh.create_submesh(m,2,selected);mapping=emap.sub_topology_to_topology(np.arange(ncells(m),dtype=np.int32),False)
            arrays=arrays[mapping];labels=labels[mapping];ft=boundaries(m,rve.micro['length_m'])
        return elliptic(self,m,labels,ft,arrays,records,rve,G,bc,root,void_mode,mapping,dense)

class ElectrostaticAdapter(PhysicsAdapter):
    name='electrostatics';input_unit='1';factor=EPS0;variable='potential_V';field='E_V_m';flux='D_C_m2';property_name='effective_permittivity';output_unit='F/m';drive_unit='V/m'

class ThermalAdapter(PhysicsAdapter):
    name='thermal';input_unit='W/(m K)';factor=1.;variable='temperature_deviation_K';field='negative_grad_T_K_m';flux='heat_flux_W_m2';property_name='effective_thermal_conductivity';output_unit='W/(m K)';drive_unit='K/m'

def elliptic(adapter,m,labels,ft,arrays,records,rve,G,bc,root,void_mode,mapping,dense):
    if MPI.COMM_WORLD.size!=1 or np.dtype(PETSc.ScalarType).kind!='f':raise ValueError('single rank real PETSc only')
    start=perf_counter();L=rve.micro['length_m'];fullarea=L**2;G=np.asarray(G,float)
    if G.shape!=(2,) or not np.isfinite(G).all() or np.linalg.norm(G)==0:raise ValueError('finite nonzero two component macro load required')
    V=fem.functionspace(m,('Lagrange',1));u,v=ufl.TrialFunction(V),ufl.TestFunction(V);w=fem.Function(V,name='periodic_fluctuation')
    components=[[scalar(m,arrays[:,i,j],f'C{i}{j}') for j in range(2)] for i in range(2)];C=ufl.as_matrix(components);scale=float(np.max(np.linalg.eigvalsh(arrays)))
    drive=ufl.as_vector(tuple(float(g) for g in G));Aform=ufl.dot((C/scale)*ufl.grad(u),ufl.grad(v))*ufl.dx
    Bform=ufl.dot((C/scale)*drive,ufl.grad(v))*ufl.dx
    A=assemble_matrix(fem.form(Aform));A.assemble();b=assemble_vector(fem.form(Bform))
    P,index,pairs,cd=constraints(V,L,bc);K=A.PtAP(P);rhs=P.createVecRight();P.multTranspose(b,rhs);z=rhs.duplicate()
    ksp=PETSc.KSP().create();ksp.setOperators(K);ksp.setType('preonly');ksp.getPC().setType('lu');ksp.getPC().setFactorSolverType('mumps');ksp.setErrorIfNotConverged(True);ksp.solve(rhs,z)
    if ksp.getConvergedReason()<=0 or not np.isfinite(z.array).all():raise RuntimeError('cell problem solve failed')
    P.mult(z,w.x.petsc_vec);w.x.scatter_forward();initial_w=w.x.array.copy()
    if bc=='periodic':w.x.array[:]-=integral(w*ufl.dx)/integral(fem.Constant(m,1.)*ufl.dx)
    potential=fem.Function(V,name=adapter.variable);xy=V.tabulate_dof_coordinates();potential.x.array[:]=w.x.array-xy[:,:2]@G
    field=dg(drive-ufl.grad(w),m,adapter.field,True);flux=dg(C*field,m,adapter.flux,True);density=dg(ufl.dot(field,flux),m,'local_field_flux_work')
    averages=lambda f:np.array([integral(f[i]*ufl.dx)/fullarea for i in range(2)])
    meanfield=averages(field);meanflux=averages(flux);micro=integral(density*ufl.dx)/fullarea;macro=float(G@meanflux)
    energy_error=abs(micro-macro)/max(abs(micro),abs(macro),1e-30)
    R=assemble_vector(fem.form(ufl.dot((C/scale)*(ufl.grad(w)-drive),ufl.grad(v))*ufl.dx));proj=P.createVecRight();P.multTranspose(R,proj)
    denom=max(rhs.norm(),np.linalg.norm(R.array),1e-30);weak=float(proj.norm()/denom)
    perioderr=float(np.max(abs(w.x.array[pairs[:,0]]-w.x.array[pairs[:,1]]))/max(L*np.linalg.norm(G),1e-30)) if len(pairs) else None
    # Independent raw DG0 boundary normal flux diagnostics, not falsely exact H(div) flux.
    normal=ufl.FacetNormal(m);ds=ufl.Measure('ds',domain=m,subdomain_data=ft)
    raw=[integral(ufl.dot(flux,normal)*ds(t)) for t in [1,2,3,4,5]]
    rawden=max(np.linalg.norm(meanflux)*L,1e-30)
    rawbalance=abs(sum(raw))/rawden;anti=[abs(raw[0]+raw[1])/rawden,abs(raw[2]+raw[3])/rawden]
    exterior=fem.locate_dofs_topological(V,1,np.concatenate([ft.find(i) for i in [1,2,3,4]]));isext=np.zeros(len(w.x.array),bool);isext[exterior]=True
    reactions=R.array*scale;weak_boundary=float(abs(sum(reactions[isext]))/max(np.linalg.norm(reactions),1e-30))
    pair_reaction_error=None
    if bc=='periodic':
        # Every periodic equivalence class has zero summed reaction, incl. all four corners.
        classes={}
        for i,x in enumerate(xy[:,:2]/L):
            if isext[i]:classes.setdefault(tuple(np.round(np.where(abs(x-1)<1e-8,0,x),9)),[]).append(i)
        pair_reaction_error=float(np.linalg.norm([sum(reactions[d]) for d in classes.values()])/max(np.linalg.norm(reactions),1e-30))
    grad_error=float(np.linalg.norm(meanfield-G)/np.linalg.norm(G))
    cavity_extension=None
    if void_mode=='insulating_cavity':
        # Fill missing gradient volume by divergence theorem for any continuous
        # extension u inside the void; no heat flow in that extension is solved.
        missing=np.array([integral(potential*normal[i]*ds(5))/fullarea for i in range(2)])
        completed=meanfield+missing;cavity_extension={'solid_field_integral_over_full_area':meanfield.tolist(),'missing_gradient_from_void_trace':missing.tolist(),'completed_full_cell_average':completed.tolist(),'meaning':'gradient extension only; void carries zero physical heat flux. Effective k uses full L^2 and prescribed macro G.'}
        grad_error=float(np.linalg.norm(completed-G)/np.linalg.norm(G))
    # Interior face jumps quantify the limitation of unrecovered DG0 flux.
    dS=ufl.Measure('dS',domain=m);jump=ufl.jump(flux,normal)
    jumpnorm=float(np.sqrt(integral(jump*jump*dS)))
    lossless_units='J/m3' if adapter.name=='electrostatics' else 'W K/m3'
    result={'physics':adapter.name,'load_G':G.tolist(),'drive_units':adapter.drive_unit,'boundary_condition':bc,'mean_driving_field':meanfield.tolist(),'mean_flux':meanflux.tolist(),
        'average_field_relative_error':grad_error,'micro_work_density':micro,'macro_work_density':macro,'work_units':lossless_units,'Hill_Mandel_relative_error':energy_error,
        'physical_electric_energy_J_m3':micro/2 if adapter.name=='electrostatics' else None,'weak_projected_residual':weak,
        'PBC_fluctuation_relative_error':perioderr,'PBC_boundary_reaction_antiperiodicity':pair_reaction_error,'weak_total_boundary_balance':weak_boundary,
        'raw_boundary_flux':raw,'raw_flux_balance_relative':rawbalance,'raw_pair_integrated_antiperiodicity':anti,'DG0_interior_normal_flux_jump_L2':jumpnorm,
        'flux_note':'raw DG0 normal jumps are not exactly conservative; periodic weak reactions and mesh convergence are checked separately. No pointwise strong conservation claim.',
        'constraints':cd,'void_mode':void_mode,'void_gradient_extension':cavity_extension,'normalization_area_m2':fullarea,'solved_area_fraction':integral(fem.Constant(m,1.)*ufl.dx)/fullarea,
        'solver':{'reason':int(ksp.getConvergedReason()),'cells':ncells(m),'DOFs':len(w.x.array),'reduced_DOFs':len(z.array),'seconds':perf_counter()-start,'peak_RSS_MiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'type':'PETSc preonly MUMPS LU on P^T A P'}}
    if dense:
        N=len(w.x.array)
        if N>600:raise ValueError('dense independent reference <=600 DOFs')
        independent=np.zeros((N,N));br=np.zeros(N);coords=V.tabulate_dof_coordinates()[:,:2]
        for cell in range(ncells(m)):
            d=V.dofmap.cell_dofs(cell);M=np.column_stack([np.ones(3),coords[d]]);grad=np.linalg.inv(M)[1:];ar=abs(np.linalg.det(M))/2
            independent[np.ix_(d,d)]+=ar*grad.T@arrays[cell]@grad/scale;br[d]+=ar*grad.T@arrays[cell]@G/scale
        pp=P.getValues(np.arange(N,dtype=np.int32),np.arange(K.getSize()[0],dtype=np.int32));zr=np.linalg.solve(pp.T@independent@pp,pp.T@br);wr=pp@zr
        result['independent_numpy_reference']={'w_max_error_per_LG':float(max(abs(wr-initial_w))/(L*np.linalg.norm(G))),
            'matrix_relative_error':float(np.linalg.norm(A.getValues(np.arange(N,dtype=np.int32),np.arange(N,dtype=np.int32))-independent)/np.linalg.norm(independent))}
    root.mkdir(parents=True,exist_ok=True)
    coef=[scalar(m,arrays[:,i,j],f'constitutive_{i}{j}') for i in range(2) for j in range(2)]
    points=[potential,w]
    if adapter.name=='thermal':
        T=fem.Function(V,name='temperature_K_reference_300');T.x.array[:]=potential.x.array+300.;points.append(T)
    result['field_export']=export(root/'fields',m,points,[field,flux,density,*coef],labels)
    np.savez(root/'periodic_constraints.npz',reduced_index=index,slave_master=pairs,coordinates_m=xy,fluctuation=w.x.array,parent_cell=mapping)
    write(root/'metrics.json',result)
    for obj in [A,b,P,K,rhs,z,ksp,R,proj]:obj.destroy()
    return result
