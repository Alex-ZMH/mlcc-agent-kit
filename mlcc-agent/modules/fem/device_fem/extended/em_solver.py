"""Strict 2D (Ex,Ey,Hz) Maxwell in real PETSc. RMS, exp(+j wt)."""
from time import perf_counter
import resource
import numpy as np
import ufl
from basix.ufl import element,mixed_element
from dolfinx import fem,mesh
from dolfinx.fem.petsc import LinearProblem,assemble_vector,assemble_matrix
from mpi4py import MPI
from petsc4py import PETSc
from .thermal_core import EPS0,scalar,dg,integral,ncells,export,write,cell_values

MU0=4e-7*np.pi
def pair(z):return [float(np.real(z)),float(np.imag(z))]
def c(z):return complex(*z)
def rectangle(nx,ny,L,H):
    m=mesh.create_rectangle(MPI.COMM_WORLD,[[0.,0.],[L,H]],[nx,ny],cell_type=mesh.CellType.triangle)
    return m,tags(m,0.,L,0.,H)
def tags(m,x0,x1,y0,y1):
    m.topology.create_connectivity(1,2);ext=mesh.exterior_facet_indices(m.topology);p=mesh.compute_midpoints(m,1,ext);tol=max(x1-x0,y1-y0)*1e-8
    val=np.where(abs(p[:,1]-y1)<tol,1,np.where(abs(p[:,1]-y0)<tol,2,np.where(abs(p[:,0]-x0)<tol,3,4))).astype(np.int32)
    return mesh.meshtags(m,1,ext,val)

def solve(m,ft,regions,materials,f,depth,current=1.+0j,source=None,cavity=False,dense=False,lifting_bounds=None):
    if not np.isfinite(f) or f<=0 or not np.isfinite(depth) or depth<=0:raise ValueError('Maxwell requires finite f>0 and depth>0; DC excluded')
    if MPI.COMM_WORLD.size!=1 or np.dtype(PETSc.ScalarType).kind!='f':raise ValueError('serial real PETSc required')
    if len(regions)!=ncells(m) or set(map(str,set(regions.tolist())))!=set(materials):raise ValueError('material coverage mismatch')
    er=np.zeros(ncells(m));sig=er.copy();tan=er.copy()
    for key,mat in materials.items():
        if set(mat)!={'eps_r','sigma_S_m','tan_delta'}:raise ValueError('explicit eps_r/sigma/tan_delta only')
        values=[float(mat[k]) for k in ['eps_r','sigma_S_m','tan_delta']]
        if not np.isfinite(values).all() or values[0]<=0 or min(values[1:])<0:raise ValueError('finite passive material required')
        er[regions==int(key)],sig[regions==int(key)],tan[regions==int(key)]=values
    omega=2*np.pi*f;ep=EPS0*er;a=sig+omega*ep*tan;b=omega*ep;kap=a+1j*b;inv=1/kap
    if not np.isfinite(inv).all():raise ValueError('nonrepresentable material/frequency')
    scale=float(np.max(abs(inv)));cr=scalar(m,inv.real/scale,'scaled_inv_real');ci=scalar(m,inv.imag/scale,'scaled_inv_imag')
    e=element('Lagrange',m.basix_cell(),1);W=fem.functionspace(m,mixed_element([e,e]));ur,ui=ufl.TrialFunctions(W);vr,vi=ufl.TestFunctions(W)
    A=(cr*(ufl.dot(ufl.grad(ur),ufl.grad(vr))+ufl.dot(ufl.grad(ui),ufl.grad(vi)))+
       ci*(-ufl.dot(ufl.grad(ui),ufl.grad(vr))+ufl.dot(ufl.grad(ur),ufl.grad(vi)))+
       omega*MU0/scale*(-ui*vr+ur*vi))*ufl.dx
    fr,fi=source if source is not None else (fem.Constant(m,0.),fem.Constant(m,0.))
    B=(fr*vr+fi*vi)/scale*ufl.dx
    S,rm=W.sub(0).collapse();T,im=W.sub(1).collapse();rm=np.asarray(rm,dtype=np.int32).reshape(-1);im=np.asarray(im,dtype=np.int32).reshape(-1)
    original_B=B;lift=fem.Function(W)
    if lifting_bounds is not None:
        lo,hi_bound=lifting_bounds
        profile=np.clip((S.tabulate_dof_coordinates()[:,1]-lo)/(hi_bound-lo),0.,1.)/depth
        lift.x.array[rm]=current.real*profile;lift.x.array[im]=current.imag*profile
        B=original_B-ufl.action(A,lift)
    bcs=[];port=[[],[]];allbc=[]
    if not cavity:
        if not np.isfinite([current.real,current.imag]).all() or abs(current)==0:raise ValueError('nonzero finite RMS port current required')
        for tag,h in [(1,current/depth),(2,0j)]:
            if not len(ft.find(tag)):raise ValueError('missing port or magnetic wall')
            for comp,V,value in [(0,S,h.real),(1,T,h.imag)]:
                d=fem.locate_dofs_topological((W.sub(comp),V),1,ft.find(tag));v=fem.Function(V);v.x.array[:]=value if lifting_bounds is None else 0.
                bcs.append(fem.dirichletbc(v,d,W.sub(comp)));allbc.extend(d[0].tolist())
                if tag==1:port[comp]=d[0]
    opts={'ksp_type':'preonly','pc_type':'lu','pc_factor_mat_solver_type':'mumps','ksp_error_if_not_converged':True,'mat_mumps_icntl_10':5}
    start=perf_counter();problem=LinearProblem(A,B,bcs=bcs,petsc_options_prefix='maxwell_',petsc_options=opts);uh=problem.solve();uh.x.scatter_forward();elapsed=perf_counter()-start
    reason=int(problem.solver.getConvergedReason())
    refinement=[]
    # Defect correction uses the original variational residual, not A*x-b
    # formed from the already rounded assembled matrix. Dirichlet increments are zero.
    if not cavity:
        defect_form=fem.form(ufl.action(A,uh)+ufl.action(A,lift)-original_B);best=uh.x.array.copy();bestnorm=float('inf')
        for iteration in range(6):
            defect=assemble_vector(defect_form);defect.array[np.asarray(allbc,np.int32)]=0.
            norm=float(defect.norm());refinement.append(norm)
            if norm<bestnorm:bestnorm=norm;best=uh.x.array.copy()
            if iteration<5:
                defect.scale(-1.);increment=defect.duplicate();problem.solver.solve(defect,increment)
                uh.x.array[:]+=increment.array;uh.x.scatter_forward();increment.destroy()
            defect.destroy()
        uh.x.array[:]=best;uh.x.scatter_forward()
    if reason<=0 or not np.isfinite(uh.x.array).all():raise RuntimeError('Maxwell solve failed')
    hr=fem.Function(S,name='H_real_A_m_rms');hi=fem.Function(T,name='H_imag_A_m_rms');hr.x.array[:]=uh.x.array[rm]+lift.x.array[rm];hi.x.array[:]=uh.x.array[im]+lift.x.array[im]
    ir=scalar(m,inv.real,'inv_kappa_real');ii=scalar(m,inv.imag,'inv_kappa_imag')
    zr,zi=ufl.split(uh);lr,li=ufl.split(lift)
    rr=ufl.as_vector((zr.dx(1)+lr.dx(1),-zr.dx(0)-lr.dx(0)));ri=ufl.as_vector((zi.dx(1)+li.dx(1),-zi.dx(0)-li.dx(0)))
    Er=dg(ir*rr-ii*ri,m,'E_real_V_m_rms',True);Ei=dg(ir*ri+ii*rr,m,'E_imag_V_m_rms',True)
    Jr=dg(rr,m,'Jtotal_real_A_m2',True);Ji=dg(ri,m,'Jtotal_imag_A_m2',True)
    sg=scalar(m,sig,'sigma_S_m');Jcr=dg(sg*Er,m,'Jconduction_real_A_m2',True);Jci=dg(sg*Ei,m,'Jconduction_imag_A_m2',True)
    E2=ufl.dot(Er,Er)+ufl.dot(Ei,Ei);H2=hr*hr+hi*hi
    qc=dg(sg*E2,m,'q_conduction_W_m3');qd=dg(scalar(m,omega*ep*tan,'dielectric_loss')*E2,m,'q_dielectric_W_m3');q=dg(scalar(m,a,'a')*E2,m,'q_total_W_m3')
    losses={};energies={}
    for tag in sorted(set(regions.tolist())):
        mask=scalar(m,(regions==tag).astype(float),'region')
        losses[str(tag)]={'total_W':depth*integral(mask*q*ufl.dx),'conduction_W':depth*integral(mask*qc*ufl.dx),'dielectric_W':depth*integral(mask*qd*ufl.dx),'area_m2':integral(mask*ufl.dx)}
    We=.5*depth*integral(scalar(m,ep,'eps_real')*E2*ufl.dx);Wm=.5*depth*integral(MU0*H2*ufl.dx);P=depth*integral(q*ufl.dx);expected=complex(P,2*omega*(Wm-We))
    residual=assemble_vector(fem.form(scale*(ufl.action(A,uh)+ufl.action(A,lift)-original_B)));free=residual.array.copy();free[np.asarray(allbc,dtype=np.int32)]=0
    rhs=assemble_vector(fem.form((fr*vr+fi*vi)*ufl.dx));denom=max(float(np.linalg.norm(residual.array)),float(rhs.norm()),1e-30);weak=float(np.linalg.norm(free)/denom);rhs.destroy()
    V=None;rawV=None;Z=None;rawpower=None;current_raw=None
    if not cavity:
        V=complex(np.sum(residual.array[port[0]]),np.sum(residual.array[port[1]]));Z=V/current
        ds=ufl.Measure('ds',domain=m,subdomain_data=ft);normal=ufl.FacetNormal(m)
        # At top n=+y: c*dH/dn=Ex and inward Poynting=Ex*conj(H).
        rawV=complex(integral(Er[0]*ds(1)),integral(Ei[0]*ds(1)));power=V*np.conj(current);rawpower=rawV*np.conj(current)
        current_raw=[-depth*complex(integral(ufl.dot(Jr,normal)*ds(3)),integral(ufl.dot(Ji,normal)*ds(3))),
                     depth*complex(integral(ufl.dot(Jr,normal)*ds(4)),integral(ufl.dot(Ji,normal)*ds(4)))]
    else:power=depth*complex(integral((fr*hr+fi*hi)*ufl.dx),integral((fi*hr-fr*hi)*ufl.dx))
    residual.destroy()
    ampere=dg(scalar(m,a,'a')*Er-scalar(m,b,'b')*Ei-Jr,m,'ampere_residual_real',True)
    amperei=dg(scalar(m,b,'b')*Er+scalar(m,a,'a')*Ei-Ji,m,'ampere_residual_imag',True)
    ampere_error=float(np.linalg.norm(np.r_[ampere.x.array,amperei.x.array])/max(np.linalg.norm(np.r_[Jr.x.array,Ji.x.array]),1e-30))
    I2=abs(current)**2 if not cavity else None
    result={'frequency_Hz':f,'depth_m':depth,'Z_ohm':pair(Z) if Z is not None else None,'V_port_V_rms':pair(V) if V is not None else None,
      'I_port_A_rms':pair(current) if not cavity else None,'raw_V_port_V_rms':pair(rawV) if rawV is not None else None,
      'raw_Z_relative_difference':abs(rawV-V)/max(abs(V),1e-30) if V is not None else None,'raw_contact_current_A':list(map(pair,current_raw)) if current_raw else None,
      'raw_contact_current_error':max(abs(x-current)/abs(current) for x in current_raw) if current_raw else None,
      'input_complex_power_VA':pair(power),'raw_input_complex_power_VA':pair(rawpower) if rawpower is not None else None,
      'volume_loss_W':P,'regions':losses,'electric_energy_J':We,'magnetic_energy_J':Wm,'energy_complex_power_VA':pair(expected),
      'complex_power_relative_error':abs(power-expected)/max(abs(power),abs(expected),1e-30),'active_power_relative_error':abs(power.real-P)/max(P,1e-30),
      'R_total_ohm':P/I2 if I2 else None,'L_magnetic_energy_H':2*Wm/I2 if I2 else None,'C_electric_energy_F':2*We/abs(V)**2 if V is not None and abs(V)>0 else None,
      'weak_Maxwell_relative_residual':weak,'ampere_algebraic_relative':ampere_error,'cellwise_strong_Faraday_RMS_V_m2':omega*MU0*np.sqrt(integral(H2*ufl.dx)/integral(fem.Constant(m,1.)*ufl.dx)),
      'note_cell_curl':'P1 H gives DG0 E; elementwise curl(E)=0. Strong Faraday above is not a convergent strong residual. Maxwell is verified weakly and against independent wave/skin solutions.',
      'solver':{'reason':reason,'seconds':perf_counter()-start,'initial_LU_seconds':elapsed,'options':opts,'lifting_bounds_m':lifting_bounds,'defect_correction_scaled_norms':refinement,'dofs':len(uh.x.array),'peak_RSS_MiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'coefficient_contrast':float(np.max(abs(inv))/np.min(abs(inv)))},'cells':ncells(m)}
    if dense:result['dense_reference']=dense_check(m,S,rm,im,inv,omega,scale,A,hr,hi,ft,current/depth)
    fields={'hr':hr,'hi':hi,'Er':Er,'Ei':Ei,'Jr':Jr,'Ji':Ji,'Jcr':Jcr,'Jci':Jci,'qc':qc,'qd':qd,'q':q}
    return fields,result

def dense_check(m,S,rm,im,inv,omega,scale,A,hr,hi,ft,H):
    N=S.dofmap.index_map.size_local
    if N>500:raise ValueError('dense reference limited to 500 scalar DOFs')
    K=np.zeros((N,N),complex);xy=S.tabulate_dof_coordinates()[:,:2]
    for i in range(ncells(m)):
        dd=S.dofmap.cell_dofs(i);M=np.column_stack([np.ones(3),xy[dd]]);grad=np.linalg.inv(M)[1:];area=abs(np.linalg.det(M))/2
        K[np.ix_(dd,dd)]+=inv[i]*area*(grad.T@grad)+1j*omega*MU0*area/12*(np.ones((3,3))+np.eye(3))
    top=fem.locate_dofs_topological(S,1,ft.find(1));bottom=fem.locate_dofs_topological(S,1,ft.find(2));fixed=np.r_[top,bottom];free=np.setdiff1d(np.arange(N),fixed)
    z=np.zeros(N,complex);z[top]=H;z[free]=np.linalg.solve(K[np.ix_(free,free)],-K[np.ix_(free,fixed)]@z[fixed])
    mat=assemble_matrix(fem.form(A));mat.assemble();D=mat.getValues(np.arange(2*N,dtype=np.int32),np.arange(2*N,dtype=np.int32));mat.destroy();blocks={}
    for name,r,col,target in [('rr',rm,rm,K.real),('ri',rm,im,-K.imag),('ir',im,rm,K.imag),('ii',im,im,K.real)]:blocks[name]=float(np.linalg.norm(D[np.ix_(r,col)]-target/scale)/max(np.linalg.norm(target/scale),1e-30))
    return {'H_max_error_A_m':float(np.max(abs(z-hr.x.array-1j*hi.x.array))),'block_relative_errors':blocks}

def save(out,m,F,regions):
    points=[F['hr'],F['hi']]
    for name,values in [('H_amplitude_A_m',np.hypot(F['hr'].x.array,F['hi'].x.array)),('H_phase_rad',np.arctan2(F['hi'].x.array,F['hr'].x.array)),
                        ('B_real_T',MU0*F['hr'].x.array),('B_imag_T',MU0*F['hi'].x.array)]:
        field=fem.Function(F['hr'].function_space,name=name);field.x.array[:]=values;points.append(field)
    cells=[F[k] for k in ['Er','Ei','Jr','Ji','Jcr','Jci','qc','qd','q']]
    for real,imag,name in [('Er','Ei','E'),('Jr','Ji','Jtotal'),('Jcr','Jci','Jconduction')]:
        amp=fem.Function(F[real].function_space,name=name+'_component_amplitude');amp.x.array[:]=np.hypot(F[real].x.array,F[imag].x.array)
        phase=fem.Function(F[real].function_space,name=name+'_component_phase_rad');phase.x.array[:]=np.arctan2(F[imag].x.array,F[real].x.array);cells.extend([amp,phase])
    return export(out/'fields',m,points,cells,regions)
