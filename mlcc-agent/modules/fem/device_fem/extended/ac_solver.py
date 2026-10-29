"""Real P1 x P1 AC-EQS FEM; complex NumPy is diagnostics/reference only."""
import math
from pathlib import Path
from time import perf_counter
import numpy as np
import ufl
from basix.ufl import element,mixed_element
from dolfinx import fem,mesh
from dolfinx.fem.petsc import LinearProblem,assemble_vector,assemble_matrix
from mpi4py import MPI
from petsc4py import PETSc
from .thermal_core import EPS0,scalar,cell_values,dg,integral,ncells,write,export

def pair(z):return [float(np.real(z)),float(np.imag(z))]
def complex_input(x):
    a=np.asarray(x,dtype=float)
    if a.shape!=(2,) or not np.isfinite(a).all():raise ValueError('voltage must be finite [real,imag]')
    return complex(*a)

def validate_material(material):
    if set(material)!={'eps_r','sigma_S_m','tan_delta'}:raise ValueError('material requires eps_r, sigma_S_m, tan_delta; no double counted eps loss')
    vals=[float(material[k]) for k in ['eps_r','sigma_S_m','tan_delta']]
    if not all(math.isfinite(v) for v in vals) or vals[0]<=0 or min(vals[1:])<0:raise ValueError('passive finite material required')
    return vals

def solve(m,tags,regions,materials,freq,va,vb,depth,*,convention='rms',dense_reference=False):
    if np.dtype(PETSc.ScalarType).kind!='f' or MPI.COMM_WORLD.size!=1:raise ValueError('one rank, real PETSc required')
    if not math.isfinite(freq) or freq<0 or not math.isfinite(depth) or depth<=0:raise ValueError('invalid frequency/depth')
    if convention not in ['rms','peak']:raise ValueError('explicit rms/peak convention required')
    va=complex_input(va);vb=complex_input(vb)
    if convention=='peak':va/=np.sqrt(2);vb/=np.sqrt(2)
    if freq==0 and (va.imag!=0 or vb.imag!=0):raise ValueError('DC limit requires real potentials')
    if abs(va-vb)==0:raise ValueError('nonzero port excitation required for Y/Z')
    if len(regions)!=ncells(m) or set(regions.tolist())!=set(map(int,materials)):raise ValueError('material coverage mismatch')
    er=np.zeros(ncells(m));sigma=er.copy();tan=er.copy()
    for region,mat in materials.items():
        values=validate_material(mat);selection=regions==int(region)
        er[selection],sigma[selection],tan[selection]=values
    omega=2*np.pi*freq;ep=EPS0*er;ei=ep*tan;av=sigma+omega*ei;bv=omega*ep
    mode='AC-EQS'
    if freq==0:
        if np.all(sigma==0):av=ep.copy();bv=np.zeros_like(ep);mode='DC_electrostatic_limit_no_AC_current'
        elif np.any(sigma==0):raise ValueError('f=0 partially insulating conductor: DC degeneracy unsupported')
        else:mode='DC_conduction_limit'
    scale=float(np.max(np.hypot(av,bv)))
    a=scalar(m,av/scale,'scaled_a');b=scalar(m,bv/scale,'scaled_b')
    e=element('Lagrange',m.basix_cell(),1);W=fem.functionspace(m,mixed_element([e,e]));ur,ui=ufl.TrialFunctions(W);vr,vi=ufl.TestFunctions(W)
    form=(a*ufl.dot(ufl.grad(ur),ufl.grad(vr))-b*ufl.dot(ufl.grad(ui),ufl.grad(vr))+
          b*ufl.dot(ufl.grad(ur),ufl.grad(vi))+a*ufl.dot(ufl.grad(ui),ufl.grad(vi)))*ufl.dx
    rhs=fem.Constant(m,0.)*(vr+vi)*ufl.dx
    Sr,rm=W.sub(0).collapse();Si,im=W.sub(1).collapse()
    rm=np.asarray(rm,dtype=np.int32).reshape(-1);im=np.asarray(im,dtype=np.int32).reshape(-1)
    bcs=[];port=[];scalar_ports=[]
    for tag,voltage in [(11,va),(12,vb)]:
        if not len(tags.find(tag)):raise ValueError('missing terminal boundary')
        pd=[]
        for comp,S,vol in [(0,Sr,voltage.real),(1,Si,voltage.imag)]:
            d=fem.locate_dofs_topological((W.sub(comp),S),1,tags.find(tag));boundary=fem.Function(S);boundary.x.array[:]=vol
            bcs.append(fem.dirichletbc(boundary,d,W.sub(comp)));pd.append(np.asarray(d[0]))
        port.append(pd);scalar_ports.append(fem.locate_dofs_topological(Sr,1,tags.find(tag)))
    opts={'ksp_type':'preonly','pc_type':'lu','pc_factor_mat_solver_type':'mumps','ksp_error_if_not_converged':True}
    start=perf_counter();problem=LinearProblem(form,rhs,bcs=bcs,petsc_options_prefix='eqs_',petsc_options=opts);solution=problem.solve();solution.x.scatter_forward()
    reason=int(problem.solver.getConvergedReason())
    if reason<=0 or not np.isfinite(solution.x.array).all():raise RuntimeError('real block solver failed')
    elapsed=perf_counter()-start
    pr=fem.Function(Sr,name='phi_real_V_rms');pi=fem.Function(Si,name='phi_imag_V_rms')
    pr.x.array[:]=solution.x.array[rm];pi.x.array[:]=solution.x.array[im]
    Er=dg(-ufl.grad(pr),m,'E_real_V_m_rms',True);Ei=dg(-ufl.grad(pi),m,'E_imag_V_m_rms',True)
    physical_a=scalar(m,sigma+omega*ei,'a_S_m');physical_b=scalar(m,omega*ep,'b_S_m')
    Jr=dg(physical_a*Er-physical_b*Ei,m,'J_real_A_m2_rms',True);Ji=dg(physical_b*Er+physical_a*Ei,m,'J_imag_A_m2_rms',True)
    norm2=ufl.dot(Er,Er)+ufl.dot(Ei,Ei)
    q=dg(physical_a*norm2,m,'q_loss_W_m3');qdc=dg(scalar(m,sigma,'sigma')*norm2,m,'q_conduction_W_m3')
    qdie=dg(scalar(m,omega*ei,'omega_eps_loss')*norm2,m,'q_dielectric_W_m3')
    qdot=dg(ufl.dot(Jr,Er)+ufl.dot(Ji,Ei),m,'q_J_dot_Estar_W_m3')
    power=depth*integral(q*ufl.dx);conductive=depth*integral(qdc*ufl.dx);dielectric=depth*integral(qdie*ufl.dx)
    # Physical residual gives terminal current entering dielectric, with
    # n_terminal=-n_dielectric. It is independent of raw boundary gradients.
    R=assemble_vector(fem.form(scale*ufl.action(form,solution)));currents=[]
    for rr,ii in port:currents.append(depth*complex(np.sum(R.array[rr]),np.sum(R.array[ii])))
    constrained=np.unique(np.concatenate([p for group in port for p in group]));free=R.array.copy();free[constrained]=0.
    residual=float(np.linalg.norm(free)/max(np.linalg.norm(R.array),1e-30));R.destroy()
    if mode=='DC_electrostatic_limit_no_AC_current':currents=[0j,0j]
    n=ufl.FacetNormal(m);ds=ufl.Measure('ds',domain=m,subdomain_data=tags)
    raw=[-depth*complex(integral(ufl.dot(Jr,n)*ds(tag)),integral(ufl.dot(Ji,n)*ds(tag))) for tag in [11,12]]
    outer=depth*complex(integral(ufl.dot(Jr,n)*ds(13)),integral(ufl.dot(Ji,n)*ds(13)))
    V=va-vb;I=currents[0];Y=I/V;Z=1/Y if abs(Y)>0 else None
    rawY=raw[0]/V;rawP=float(np.real(np.conj(va)*raw[0]+np.conj(vb)*raw[1]));terminal_work=np.conj(va)*currents[0]+np.conj(vb)*currents[1]
    reactive_volume=depth*integral(physical_b*norm2*ufl.dx);work_volume=complex(power,reactive_volume)
    denom=max(abs(currents[0]),abs(currents[1]),1e-30)
    per_region={}
    for tag in sorted(set(regions.tolist())):
        mask=scalar(m,(regions==tag).astype(float),'region_mask')
        per_region[str(tag)]={'area_m2':integral(mask*ufl.dx),'power_W':depth*integral(mask*q*ufl.dx),
                             'E_imag_rms_V_m':math.sqrt(integral(mask*ufl.dot(Ei,Ei)*ufl.dx)/integral(mask*ufl.dx))}
    qdiff=float(np.max(abs(q.x.array-qdot.x.array)))/max(float(np.max(abs(q.x.array))),1.)
    metrics={'mode':mode,'frequency_Hz':freq,'voltage_rms_V':pair(V),'port_current_entering_A':list(map(pair,currents)),
             'raw_port_current_entering_A':list(map(pair,raw)),'raw_outer_outward_A':pair(outer),
             'Y_S':pair(Y),'Z_ohm':pair(Z) if Z is not None else None,'Z_magnitude_ohm':abs(Z) if Z is not None else None,
             'Z_phase_deg':float(np.angle(Z,deg=True)) if Z is not None else None,
             'Cp_parallel_F':Y.imag/omega if omega>0 and Y.imag>0 else None,'G_S':Y.real,
             'tan_delta_effective':Y.real/Y.imag if Y.imag>0 else None,'equivalent_dielectric_series_resistance_ohm':Z.real if Z is not None else None,
             'raw_Y_S':pair(rawY),'raw_Y_reaction_relative':abs(rawY-Y)/max(abs(Y),1e-30),
             'current_balance_relative':abs(sum(currents))/denom,'raw_current_balance_relative':abs(sum(raw)-outer)/max(abs(raw[0]),abs(raw[1]),1e-30),
             'volume_power_W':power,'conduction_power_W':conductive,'dielectric_power_W':dielectric,'terminal_power_W':float(terminal_work.real),
             'raw_terminal_power_W':rawP,'power_relative_error':abs(terminal_work.real-power)/max(power,1e-30),
             'complex_work_relative_error':abs(terminal_work-work_volume)/max(abs(work_volume),1e-30),
             'terminal_complex_power_VIstar_VA':pair(np.conj(terminal_work)),
             'q_dot_identity_relative':qdiff,'q_min_W_m3':float(q.x.array.min()),'regions':per_region,
             'phi_imag_max_V':float(np.max(abs(pi.x.array))),'phi_imag_RMS_V':math.sqrt(integral(pi*pi*ufl.dx)/integral(fem.Constant(m,1.)*ufl.dx)),
             'dofs':len(solution.x.array),'cells':ncells(m),'solver':{'reason':reason,'relative_free_residual':residual,'seconds':elapsed,'options':opts,'coefficient_scaling_S_m':scale}}
    if dense_reference:metrics['independent_complex_algebra']=dense_check(m,Sr,W,rm,im,regions,av,bv,scale,form,scalar_ports,va,vb,pr,pi)
    fields={'pr':pr,'pi':pi,'Er':Er,'Ei':Ei,'Jr':Jr,'Ji':Ji,'q':q,'qdc':qdc,'qdie':qdie,'qdot':qdot}
    return fields,metrics

def dense_check(m,S,W,rm,im,regions,a,b,scale,form,ports,va,vb,pr,pi):
    """Independent element-gradient NumPy complex FEM, no UFL algebra reuse."""
    N=S.dofmap.index_map.size_local
    if N>500:raise ValueError('dense reference restricted to <=500 scalar DOFs')
    xy=S.tabulate_dof_coordinates()[:,:2];K=np.zeros((N,N),dtype=complex)
    for cell in range(ncells(m)):
        dofs=S.dofmap.cell_dofs(cell);x=xy[dofs];M=np.column_stack([np.ones(3),x]);g=np.linalg.inv(M)[1:,:]
        area=abs(np.linalg.det(M))/2;K[np.ix_(dofs,dofs)]+=(a[cell]+1j*b[cell])*area*(g.T@g)
    bc=np.r_[ports[0],ports[1]];values=np.r_[np.full(len(ports[0]),va),np.full(len(ports[1]),vb)];free=np.setdiff1d(np.arange(N),bc)
    z=np.zeros(N,dtype=complex);z[bc]=values;z[free]=np.linalg.solve(K[np.ix_(free,free)],-K[np.ix_(free,bc)]@values)
    A=assemble_matrix(fem.form(form));A.assemble();dense=A.getValues(np.arange(2*N,dtype=np.int32),np.arange(2*N,dtype=np.int32));A.destroy()
    blocks={}
    for name,r,c,target in [('rr',rm,rm,K.real),('ri',rm,im,-K.imag),('ir',im,rm,K.imag),('ii',im,im,K.real)]:
        blocks[name]=float(np.linalg.norm(dense[np.ix_(r,c)]-target/scale)/max(np.linalg.norm(target/scale),1e-30))
    reference_current=np.sum((K@z)[ports[0]])
    return {'potential_max_error_V':float(np.max(abs(z-(pr.x.array+1j*pi.x.array)))),'block_relative_errors':blocks,
            'reference_Y_per_depth_S_m':pair(reference_current/(va-vb)),'reference_scalar_dofs':N}

def amplitude_fields(fields):
    points=[];cells=[]
    for r,i,prefix,unit in [(fields['pr'],fields['pi'],'phi','V_rms')]:
        for name,values in [('amplitude',np.hypot(r.x.array,i.x.array)),('phase',np.arctan2(i.x.array,r.x.array))]:
            f=fem.Function(r.function_space,name=f'{prefix}_{name}_{unit if name=="amplitude" else "rad"}');f.x.array[:]=values;points.append(f)
    for r,i,prefix,unit in [(fields['Er'],fields['Ei'],'E','V_m_rms'),(fields['Jr'],fields['Ji'],'J','A_m2_rms')]:
        for name,values in [('component_amplitude',np.hypot(r.x.array,i.x.array)),('component_phase',np.arctan2(i.x.array,r.x.array))]:
            f=fem.Function(r.function_space,name=f'{prefix}_{name}_{unit if name.endswith("amplitude") else "rad"}');f.x.array[:]=values;cells.append(f)
        norm=dg(ufl.sqrt(ufl.dot(r,r)+ufl.dot(i,i)),r.function_space.mesh,f'{prefix}_rms_norm_{unit}');cells.append(norm)
    return points,cells

def save_fields(out,m,fields,regions):
    extra_p,extra_c=amplitude_fields(fields)
    report=export(out/'electrical',m,[fields['pr'],fields['pi'],*extra_p],[fields[k] for k in ['Er','Ei','Jr','Ji','q','qdc','qdie','qdot']]+extra_c,regions)
    write(out/'field_conventions.json',{'phasors':'RMS; real waveform=sqrt(2)*Re(z exp(j omega t))','vector_phase':'per Cartesian component; a vector has no unique scalar phase',
                                     'zero_amplitude_phase':'atan2(0,0) stored as 0; undefined phase must be masked by amplitude',
                                     'coordinate_unit':'m','material_tag':'electrical dielectric region, not Ni thermal region'})
    return report

def plate(n,L=.01,H=.002,split=.4):
    m=mesh.create_rectangle(MPI.COMM_WORLD,[[0.,0.],[L,H]],[n,max(2,n//5)],cell_type=mesh.CellType.triangle)
    m.topology.create_connectivity(1,2);ext=mesh.exterior_facet_indices(m.topology);mid=mesh.compute_midpoints(m,1,ext)
    tags=mesh.meshtags(m,1,ext,np.where(abs(mid[:,0])<1e-12,11,np.where(abs(mid[:,0]-L)<1e-12,12,13)).astype(np.int32))
    centers=mesh.compute_midpoints(m,2,np.arange(ncells(m),dtype=np.int32));regions=np.where(centers[:,0]<split*L,101,102).astype(np.int32)
    return m,tags,regions
