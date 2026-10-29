"""Shared real 2D/3D full-vector mixed CG1 TDGL/electrostatic kernel."""
from pathlib import Path
import itertools,json,time,resource,hashlib
from functools import lru_cache
import numpy as np
import ufl
from basix.ufl import element,mixed_element
from dolfinx import fem,mesh,io,plot
from dolfinx.fem.petsc import NonlinearProblem,LinearProblem,assemble_vector,assemble_matrix
from mpi4py import MPI
from petsc4py import PETSc
from .physics import Parameters,wall_states,wall_profile,frame
from scientific_core.fenicsx import integral_local as integral, interpolate_dg0, cell_dof_values, scalar_cell_values, owned_cell_count
IDS=itertools.count()
def write(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,indent=2,allow_nan=False,default=lambda a:a.tolist() if isinstance(a,np.ndarray) else a.item() if isinstance(a,np.generic) else str(a)),encoding='utf-8')
class VectorPhaseField:
    def __init__(self,dimension=2,cells=None,parameters=None,kind='uniform',initial=None,field=None,mms=None,width=1.5):
        started=time.perf_counter()
        if dimension not in [2,3] or MPI.COMM_WORLD.size!=1:raise ValueError('2/3D, single MPI rank required')
        self.D=dimension;D=dimension;self.par=Parameters(**(parameters or {}));p=self.par;self.kind=kind;self.mms=mms
        if kind not in ['uniform','perturb','wall_180','wall_90xy','wall_90xz'] or mms not in [None,'affine','trigonometric']:raise ValueError('unsupported initial/boundary formulation')
        if mms and (kind.startswith('wall') or (field is not None and np.linalg.norm(field)>0)):raise ValueError('MMS prescribed boundaries incompatible with wall or external-field control')
        if not np.isfinite(width) or width<=0:raise ValueError('positive finite initial width required')
        cells=list(cells or ([32,2] if kind.startswith('wall') else [4]*D))
        if len(cells)!=D or any(isinstance(n,bool) or not isinstance(n,int) or n<1 for n in cells):raise ValueError('positive dimension-matched integer cell counts required')
        self.wallkind=kind.split('_',1)[1] if kind.startswith('wall_') else None
        if self.wallkind:
            self.left,self.right,n=wall_states(D,self.wallkind);self.R=frame(n);self.lo=np.array([-8.]+[-1.]*(D-1));self.hi=-self.lo
            if 16/cells[0]>p.delta/2+1e-12:raise ValueError('unresolved wall: require at least 4 cells per 2*delta; convergence still mandatory')
        else:self.R=np.eye(D);self.lo=np.array([-2.]*D if kind=='perturb' else [0.]*D);self.hi=np.array([2.]*D if kind=='perturb' else [1.]*D)
        self.volume=float(np.prod(self.hi-self.lo));self.area=float(np.prod((self.hi-self.lo)[1:]));self.cells=cells
        self.m=mesh.create_rectangle(MPI.COMM_WORLD,[self.lo,self.hi],cells,cell_type=mesh.CellType.triangle) if D==2 else mesh.create_box(MPI.COMM_WORLD,[self.lo,self.hi],cells,cell_type=mesh.CellType.tetrahedron)
        self.m.geometry.x[:,:D]=self.m.geometry.x[:,:D]@self.R.T
        self.dx=ufl.Measure('dx',domain=self.m,metadata={'quadrature_degree':6});el=element('Lagrange',self.m.basix_cell(),1);self.V=fem.functionspace(self.m,mixed_element([el]*(D+1)));self.u=fem.Function(self.V);self.old=fem.Function(self.V)
        self.spaces=[];self.maps=[]
        for i in range(D+1):
            space,mapping=self.V.sub(i).collapse();self.spaces.append(space);self.maps.append(np.asarray(mapping,np.int32).reshape(-1))
        self.S=self.spaces[0];self.xy=self.S.tabulate_dof_coordinates();self.qcoords=self.xy[:,:D]@self.R
        if len(self.u.x.array)>25000:raise ValueError('PoC direct LU cap 25000 total DOFs')
        for s in self.spaces:assert np.allclose(s.tabulate_dof_coordinates(),self.xy)
        self.meshid=hashlib.sha256(self.xy.tobytes()+np.array(cells).tobytes()).hexdigest();self.dt=fem.Constant(self.m,.05);self.rate=fem.Constant(self.m,1.);self.time=fem.Constant(self.m,0.);self.E=np.zeros(D);self.t=0.;self.logs=[];self.history=[];self.snapshots=[];self.phis=[];self.attempt=0
        self.phib=fem.Function(self.spaces[D]);self.pbc=[];self.bcs=[];self.external=fem.Constant(self.m,np.zeros(D,dtype=PETSc.ScalarType))
        self.boundary=lambda x:np.any(np.isclose(self.R.T@x[:D],self.lo[:,None])|np.isclose(self.R.T@x[:D],self.hi[:,None]),axis=0)
        normal_ends=lambda x:np.isclose((self.R.T@x[:D])[0],self.lo[0])|np.isclose((self.R.T@x[:D])[0],self.hi[0])
        for i in range(D+1):
            value=self.phib if i==D else fem.Function(self.spaces[i])
            if i==D or self.wallkind or mms:
                where=self.boundary if i==D or mms else normal_ends;dofs=fem.locate_dofs_geometrical((self.V.sub(i),self.spaces[i]),where);self.bcs.append(fem.dirichletbc(value,dofs,self.V.sub(i)))
                if i<D:self.pbc.append((i,value,np.asarray(dofs[1],np.int32)))
        self.set_field(np.zeros(D) if field is None else field)
        splits=ufl.split(self.u);olds=ufl.split(self.old);tests=ufl.TestFunctions(self.V);self.P=ufl.as_vector(splits[:D]);self.phi=splits[D];self.Pold=ufl.as_vector(olds[:D]);v=ufl.as_vector(tests[:D]);q=tests[D]
        self.fbulk=p.a*ufl.dot(self.P,self.P)+p.b*sum(z**4 for z in splits[:D])+p.c*sum(splits[i]**2*splits[j]**2 for i in range(D) for j in range(i));self.fgrad=p.g/2*ufl.inner(ufl.grad(self.P),ufl.grad(self.P));self.felec=-p.epsilon/2*ufl.dot(ufl.grad(self.phi),ufl.grad(self.phi))+ufl.dot(self.P,ufl.grad(self.phi));self.enthalpy=self.fbulk+self.fgrad+self.felec
        force=ufl.as_vector([2*p.a*splits[i]+4*p.b*splits[i]**3+2*p.c*splits[i]*sum(splits[j]**2 for j in range(D) if j!=i) for i in range(D)])
        self.terms={'time':self.rate/(p.mobility*self.dt)*ufl.dot(self.P-self.Pold,v)*self.dx,'Landau':ufl.dot(force,v)*self.dx,'gradient':p.g*ufl.inner(ufl.grad(self.P),ufl.grad(v))*self.dx,'P_phi':ufl.dot(ufl.grad(self.phi),v)*self.dx,'phi_P':-ufl.dot(self.P,ufl.grad(q))*self.dx,'phi_phi':p.epsilon*ufl.dot(ufl.grad(self.phi),ufl.grad(q))*self.dx}
        self.sourceP=ufl.as_vector([0.]*D);self.rho=0.;self.exactP=None;self.exactphi=None
        if mms:
            x=ufl.SpatialCoordinate(self.m);decay=ufl.exp(-self.time)
            if mms=='affine':
                self.exactP=ufl.as_vector([.2+.03*i+.04*sum((j+i+1)*x[j] for j in range(D))/D*decay for i in range(D)]);self.exactphi=.04*sum((-1)**j*x[j] for j in range(D))*decay
            else:
                self.exactP=ufl.as_vector([.2+.03*i+.08*ufl.sin(np.pi*sum((1+(j==i))*x[j] for j in range(D)))*decay for i in range(D)]);self.exactphi=.07*ufl.sin(np.pi*sum(x[j] for j in range(D)))*decay
            z=self.exactP
            offset=ufl.as_vector([.2+.03*i for i in range(D)]);fg=ufl.as_vector([2*p.a*z[i]+4*p.b*z[i]**3+2*p.c*z[i]*sum(z[j]**2 for j in range(D) if j!=i) for i in range(D)])
            self.sourceP=-(z-offset)/p.mobility+fg-p.g*ufl.div(ufl.grad(z))+ufl.grad(self.exactphi);self.rho=-p.epsilon*ufl.div(ufl.grad(self.exactphi))+ufl.div(z)
        self.F=sum(self.terms.values())-ufl.dot(self.sourceP,v)*self.dx-self.rho*q*self.dx;self.J=ufl.derivative(self.F,self.u)
        self.expressions=[]
        if mms:
            for i in range(D):self.expressions.append(fem.Expression(self.exactP[i],self.spaces[i].element.interpolation_points))
            self.phiexpr=fem.Expression(self.exactphi,self.spaces[D].element.interpolation_points)
        self.initial=initial
        for i in range(D):
            value=fem.Function(self.spaces[i])
            if mms:value.interpolate(self.expressions[i])
            elif self.wallkind:value.interpolate(lambda x,i=i:wall_profile((self.R.T@x[:D])[0],D,self.wallkind,p,width)[:,i])
            elif kind=='perturb':value.interpolate(lambda x,i=i:(.75 if i==0 else .05)+.14*np.sin(np.pi*(x[i]+.3*x[(i+1)%D])/2)*np.cos(np.pi*x[-1]/2))
            else:
                data=np.array(initial if initial is not None else [1.]+[0.]*(D-1),float)
                if data.shape!=(D,) or not np.isfinite(data).all():raise ValueError('dimension-matched finite vector IC required')
                value.x.array[:]=data[i]
            self.u.x.array[self.maps[i]]=value.x.array
        self.update_boundary()
        for i,value,dofs in self.pbc:self.u.x.array[self.maps[i][dofs]]=value.x.array[dofs]
        self.old.x.array[:]=self.u.x.array;self.equilibrate_phi();self.old.x.array[:]=self.u.x.array
        self.monitor=[]
        self.problem=NonlinearProblem(self.F,self.u,J=self.J,bcs=self.bcs,petsc_options_prefix=f'vector_{next(IDS)}_',petsc_options={'snes_type':'newtonls','snes_linesearch_type':'bt','snes_rtol':1e-10,'snes_atol':1e-11,'snes_max_it':25,'snes_error_if_not_converged':False,'ksp_type':'preonly','pc_type':'lu','pc_factor_mat_solver_type':'mumps','ksp_error_if_not_converged':True})
        self.problem.solver.setMonitor(lambda snes,it,norm:self.monitor.append({'it':it,'residual':float(norm)}));self.creation_seconds=time.perf_counter()-started;self.record()
    def set_field(self,E):
        E=np.array(E,float)
        if E.shape!=(self.D,) or not np.isfinite(E).all():raise ValueError('finite dimension-matched electric field required')
        self.E=E;self.external.value[:]=E;self.phib.interpolate(lambda x:-E@x[:self.D])
    def update_boundary(self):
        if self.mms:self.phib.interpolate(self.phiexpr)
        else:self.phib.interpolate(lambda x:-self.E@x[:self.D])
        for i,v,dofs in self.pbc:
            if self.mms:v.interpolate(self.expressions[i])
            else:v.interpolate(lambda x,i=i:wall_profile((self.R.T@x[:self.D])[0],self.D,self.wallkind,self.par)[:,i])
    def equilibrate_phi(self):
        T=self.spaces[self.D];trial=ufl.TrialFunction(T);q=ufl.TestFunction(T);d=fem.locate_dofs_geometrical(T,self.boundary)
        problem=LinearProblem(self.par.epsilon*ufl.dot(ufl.grad(trial),ufl.grad(q))*self.dx,(ufl.dot(self.P,ufl.grad(q))+self.rho*q)*self.dx,bcs=[fem.dirichletbc(self.phib,d)],petsc_options_prefix=f'vec_init_{next(IDS)}_',petsc_options={'ksp_type':'preonly','pc_type':'lu','pc_factor_mat_solver_type':'mumps'})
        result=problem.solve()
        if problem.solver.getConvergedReason()<=0:raise RuntimeError('initial electrostatic solve failed')
        self.u.x.array[self.maps[self.D]]=result.x.array;self.u.x.scatter_forward()
    def fields(self):return np.column_stack([self.u.x.array[m] for m in self.maps[:self.D]]),self.u.x.array[self.maps[self.D]].copy()
    def diagnostic(self):
        D=self.D;p=self.par;volume=self.volume;P,phi=self.fields();energy=integral(self.enthalpy*self.dx);means=np.array([integral(self.P[i]*self.dx)/volume for i in range(D)]);meansE=np.array([-integral(self.phi.dx(i)*self.dx)/volume for i in range(D)])
        T=self.spaces[D];q=ufl.TestFunction(T);r=assemble_vector(fem.form((p.epsilon*ufl.dot(ufl.grad(self.phi),ufl.grad(q))-ufl.dot(self.P,ufl.grad(q))-self.rho*q)*self.dx));bd=fem.locate_dofs_geometrical(T,self.boundary);free=np.ones(len(r.array),bool);free[bd]=False;values=r.array.copy();r.destroy();rawD=-p.epsilon*ufl.grad(self.phi)+self.P
        row={'t':self.t,'E_applied':self.E.tolist(),'mean_P':means.tolist(),'mean_E':meansE.tolist(),'enthalpy':energy,'bulk':integral(self.fbulk*self.dx),'gradient':integral(self.fgrad*self.dx),'electric_enthalpy':integral(self.felec*self.dx),'P_rms':float(np.sqrt(integral(ufl.dot(self.P,self.P)*self.dx)/volume)),
             'E_depolarization_rms':float(np.sqrt(integral(ufl.dot(-ufl.grad(self.phi)-self.external,-ufl.grad(self.phi)-self.external)*self.dx)/volume)),'bound_charge_rms':float(np.sqrt(integral(ufl.div(self.P)**2*self.dx)/volume)),
             'Gauss_free_residual':float(np.linalg.norm(values[free])),'Gauss_reaction_balance':float(abs(sum(values[bd])+integral(self.rho*self.dx))),'potential_BC_error':float(max(abs(phi[bd]-self.phib.x.array[bd]))),'raw_boundary_D_flux':integral(ufl.dot(rawD,ufl.FacetNormal(self.m))*ufl.ds(domain=self.m)),
             'gradient_by_spatial_axis_rms':[float(np.sqrt(integral(sum(self.P[i].dx(j)**2 for i in range(D))*self.dx)/volume)) for j in range(D)]}
        if self.exactP is not None:row.update(P_exact_L2=float(np.sqrt(integral(ufl.dot(self.P-self.exactP,self.P-self.exactP)*self.dx)/volume)),phi_exact_L2=float(np.sqrt(integral((self.phi-self.exactphi)**2*self.dx)/volume)),E_exact_L2=float(np.sqrt(integral(ufl.dot(ufl.grad(self.phi-self.exactphi),ufl.grad(self.phi-self.exactphi))*self.dx)/volume)))
        if self.wallkind:
            svals=np.unique(np.round(self.qcoords[:,0],10));profile=np.array([P[np.isclose(self.qcoords[:,0],s)].mean(axis=0) for s in svals]);contrast=(profile@((self.right-self.left)/np.dot(self.right-self.left,self.right-self.left))*2)/p.Ps
            def crossing(value):
                k=np.flatnonzero((contrast[:-1]-value)*(contrast[1:]-value)<=0)
                if not len(k):return None
                j=k[len(k)//2];return float(svals[j]+(value-contrast[j])*(svals[j+1]-svals[j])/(contrast[j+1]-contrast[j]))
            low,high=crossing(-np.tanh(1)),crossing(np.tanh(1));pos=crossing(0)
            analytic=self.wallkind=='180' or abs(p.c-6*p.b)<1e-12
            row.update(wall_position=pos,wall_delta=(high-low)/2 if high is not None and low is not None else None,wall_excess_energy=(energy+p.a**2/(4*p.b)*volume)/self.area,profile_exact_RMS=float(np.sqrt(np.mean((profile-wall_profile(svals,D,self.wallkind,p))**2))) if analytic else None,min_polarization_magnitude=float(np.min(np.linalg.norm(P,axis=1))),farfield_angle_deg=float(np.degrees(np.arccos(np.clip(profile[0]@profile[-1]/(np.linalg.norm(profile[0])*np.linalg.norm(profile[-1])),-1,1)))),favored_right_fraction=float(integral(ufl.conditional(ufl.gt(ufl.dot(self.P,ufl.as_vector(self.right-self.left)),0),1.,0.)*self.dx)/volume))
        return row
    def record(self):
        self.history.append(self.diagnostic());P,phi=self.fields();self.snapshots.append(P.copy());self.phis.append(phi.copy())
    def checkpoint(self):return (self.u.x.array.copy(),self.old.x.array.copy(),self.t,float(self.dt.value),float(self.time.value),self.E.copy(),self.phib.x.array.copy(),[(v,v.x.array.copy()) for _,v,_ in self.pbc],float(self.rate.value))
    def restore(self,state):
        self.u.x.array[:]=state[0];self.old.x.array[:]=state[1];self.t=state[2];self.dt.value=state[3];self.time.value=state[4];self.E=state[5].copy();self.external.value[:]=self.E;self.phib.x.array[:]=state[6]
        for v,a in state[7]:v.x.array[:]=a
        self.rate.value=state[8]
        self.u.x.scatter_forward();self.old.x.scatter_forward()
    def advance(self,end,dt,field=None,fail_iterations=None,max_retries=6):
        if not np.isfinite([end,dt]).all() or not 0<dt<=.2 or end<=self.t:raise ValueError('forward time and 0<dt<=0.2 required')
        if not np.array_equal(self.u.x.array,self.old.x.array) or (self.history and abs(self.history[-1]['t']-self.t)>1e-12):raise ValueError('accepted/current/history state inheritance is inconsistent')
        proposed=dt;retries=0
        while self.t<end-1e-12:
            target=end if end-self.t<=proposed*(1+1e-8) else self.t+proposed;h=target-self.t;state=self.checkpoint();Eold=self.E.copy();oldenergy=self.history[-1]['enthalpy'];oldP=np.array(self.history[-1]['mean_P']);self.time.value=target;self.dt.value=h
            if field is not None:self.set_field(field(target))
            self.update_boundary();self.monitor=[];self.rate.value=1.;maxit=(fail_iterations or {}).get(self.attempt,25);self.problem.solver.setTolerances(max_it=maxit);start=time.perf_counter();error=None
            try:self.problem.solve();reason=int(self.problem.solver.getConvergedReason());norm=float(self.problem.solver.getFunctionNorm());ok=reason>0 and norm<1e-8 and np.isfinite(self.u.x.array).all()
            except (RuntimeError,PETSc.Error) as exc:ok=False;reason=int(self.problem.solver.getConvergedReason());norm=float(self.problem.solver.getFunctionNorm());error=str(exc)
            changed=not np.array_equal(state[0],self.u.x.array);work=float(-(self.E-Eold)@oldP*self.volume-self.par.epsilon/2*self.volume*(self.E@self.E-Eold@Eold));newenergy=integral(self.enthalpy*self.dx)
            energygap=newenergy-oldenergy-work;rate2=integral(ufl.dot(self.P-self.Pold,self.P-self.Pold)*self.dx)/(self.par.mobility*h)
            if not self.mms and energygap>1e-8*max(1,abs(oldenergy),self.volume):ok=False;error='fixed-voltage work/enthalpy inequality failed'
            log={'attempt':self.attempt,'start_t':self.t,'target_t':target,'dt':h,'reason':reason,'residual':norm if np.isfinite(norm) else None,'iterations':int(self.problem.solver.getIterationNumber()),'accepted':bool(ok),'monitor':self.monitor.copy(),'seconds':time.perf_counter()-start,'trial_changed':changed,'voltage_work':work,'energy_change_minus_work':energygap,'BE_increment_dissipation':rate2,'error':error};self.attempt+=1;self.logs.append(log)
            if not ok:
                self.restore(state);log['rollback_exact']=bool(np.array_equal(self.u.x.array,state[0]) and np.array_equal(self.old.x.array,state[1]) and self.t==state[2] and float(self.dt.value)==state[3] and float(self.time.value)==state[4] and float(self.rate.value)==state[8] and np.array_equal(self.E,state[5]) and np.array_equal(self.external.value,state[5]) and np.array_equal(self.phib.x.array,state[6]) and all(np.array_equal(v.x.array,a) for v,a in state[7]));retries+=1
                if retries>max_retries:raise RuntimeError('nonlinear step failed; last accepted state restored')
                proposed=h/2;continue
            self.t=target;self.old.x.array[:]=self.u.x.array;self.old.x.scatter_forward();self.record();retries=0
        return self
    def steady(self):
        state=self.checkpoint();self.rate.value=0.;self.problem.solver.setTolerances(max_it=50);self.monitor=[];self.problem.solve();reason=int(self.problem.solver.getConvergedReason());norm=float(self.problem.solver.getFunctionNorm())
        if reason<=0 or norm>1e-8 or not np.isfinite(self.u.x.array).all():self.restore(state);raise RuntimeError('steady mixed Newton failed and restored')
        self.old.x.array[:]=self.u.x.array;self.logs.append({'steady':True,'accepted':True,'reason':reason,'residual':norm,'iterations':int(self.problem.solver.getIterationNumber()),'monitor':self.monitor.copy()});self.record();return self
    def save(self,out):
        out=Path(out);out.mkdir(parents=True,exist_ok=True);P,phi=self.fields();top,types,points=plot.vtk_mesh(self.S);cells=top.reshape(-1,self.D+2)[:,1:]
        import pyvista as pv
        grid=pv.UnstructuredGrid(top,types,points);grid.point_data['P']=np.pad(P,((0,0),(0,3-self.D)));grid.point_data['phi']=phi
        for i in range(self.D):grid.point_data['P'+'xyz'[i]]=P[:,i]
        def dg(expr,name,vector=False):
            z=interpolate_dg0(expr,self.m,name,vector=vector);vals=cell_dof_values(z) if vector else scalar_cell_values(z)
            grid.cell_data[name]=np.pad(vals,((0,0),(0,3-self.D))) if vector else vals;return z
        E=dg(-ufl.grad(self.phi),'E',True);rho=dg(-ufl.div(self.P),'rho_bound');disp=dg(-self.par.epsilon*ufl.grad(self.phi)+self.P,'D_cell_mean',True);grid.save(out/'fields.vtu')
        with io.XDMFFile(MPI.COMM_WORLD,str(out/'fields.xdmf'),'w') as x:
            x.write_mesh(self.m)
            for i in range(self.D):z=self.u.sub(i).collapse();z.name='P'+'xyz'[i];x.write_function(z,self.t)
            z=self.u.sub(self.D).collapse();z.name='phi';x.write_function(z,self.t);x.write_function(E,self.t);x.write_function(rho,self.t)
        np.savez_compressed(out/'fields.npz',coordinates=points,cells=cells,P=P,phi=phi,times=np.array([r['t'] for r in self.history]),P_history=np.array(self.snapshots),phi_history=np.array(self.phis),frame=self.R,mesh_id=self.meshid)
        config={'dimension':self.D,'cells':self.cells,'parameters':self.par.as_dict(),'kind':self.kind,'initial':self.initial,'mms':self.mms,'geometry_lo':self.lo,'geometry_hi':self.hi,'frame':self.R,'units':'dimensionless; all P components and phi are independent CG1 unknowns','electric_BC':'phi=-E_applied dot x on ALL outer faces; no duplicate body electric field'}
        write(out/'config.json',config);write(out/'history.json',self.history);write(out/'nonlinear.json',self.logs);write(out/'metrics.json',{'final':self.history[-1],'resources':{'cells':owned_cell_count(self.m),'DOFs_per_P_component':len(P),'potential_DOFs':len(phi),'total_DOFs':len(self.u.x.array),'creation_seconds':self.creation_seconds,'peak_process_RSS_MiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'nonlinear_iterations':sum(r['iterations'] for r in self.logs),'solve_seconds':sum(r.get('seconds',0) for r in self.logs)},'mesh_id':self.meshid,'solver':'DOLFINx mixed CG1/PETSc SNES newtonls/MUMPS LU, one MPI rank','status':'PASS' if all(r['residual'] is not None and r['residual']<1e-8 for r in self.logs if r['accepted']) else 'FAIL'})
        return self.history[-1]
