"""DOLFINx 0.11 serial benchmark solvers, monolithic P/phi Newton solve."""
import itertools
import json
import math
from pathlib import Path
import numpy as np
import ufl
from basix.ufl import element, mixed_element
from dolfinx import mesh, fem, io
from dolfinx.fem.petsc import NonlinearProblem, LinearProblem
from mpi4py import MPI
from petsc4py import PETSc
from .physics import wall
from scientific_core.fenicsx import integral_global

_ids=itertools.count()
DX = {'quadrature_degree': 8}

def integral(expr):
    return integral_global(expr, comm=MPI.COMM_WORLD)

class PhaseField:
    def __init__(self,n,ny,g,epsilon,field,initial,nz=None):
        if MPI.COMM_WORLD.size != 1: raise ValueError('Single MPI rank required')
        self.two=True; self.g=g; self.epsilon=epsilon; self.field=field
        self.dimension=3 if nz is not None else 2
        self.volume=256. if nz is not None else 64.
        self.mms=False; self.last_rate_rms=0.; self.mms_boundaries=[]
        if nz is not None:
            self.m=mesh.create_box(MPI.COMM_WORLD,[[-8.,0.,-2.],[8.,4.,2.]],[n,ny,nz],cell_type=mesh.CellType.tetrahedron)
        else:
            self.m=mesh.create_rectangle(MPI.COMM_WORLD,[[-8.,0.],[8.,4.]],[n,ny])
        self.dx=ufl.Measure('dx',domain=self.m,metadata=DX)
        el=element('Lagrange',self.m.basix_cell(),1)
        self.V=fem.functionspace(self.m,mixed_element([el,el]))
        self.u=fem.Function(self.V); self.old=fem.Function(self.V)
        self.dt=fem.Constant(self.m,PETSc.ScalarType(.05))
        self.rate=fem.Constant(self.m,PETSc.ScalarType(1.))
        self.time=fem.Constant(self.m,PETSc.ScalarType(0.))
        self.source_P=0.; self.source_Q=0.
        self.S,self.pmap=self.V.sub(0).collapse(); self.T,self.phimap=self.V.sub(1).collapse()
        self.pmap=np.asarray(self.pmap,dtype=np.int32).reshape(-1)
        self.phimap=np.asarray(self.phimap,dtype=np.int32).reshape(-1)
        p,phi=ufl.split(self.u); po,_=ufl.split(self.old); v,q=ufl.TestFunctions(self.V)
        init=fem.Function(self.S); init.interpolate(initial)
        self.u.x.array[self.pmap]=init.x.array
        phib=fem.Function(self.T); phib.interpolate(lambda x:-field*x[1])
        self.u.x.array[self.phimap]=phib.x.array; self.electrode_value=phib
        self.electrode=lambda x:np.isclose(x[1],0)|np.isclose(x[1],4)
        bd=fem.locate_dofs_geometrical((self.V.sub(1),self.T),self.electrode)
        self.bcs=[fem.dirichletbc(phib,bd,self.V.sub(1))]
        F=(self.rate*(p-po)/self.dt*v+(-p+p**3)*v+g*ufl.dot(ufl.grad(p),ufl.grad(v))+phi.dx(1)*v)*self.dx
        F+=(epsilon*ufl.dot(ufl.grad(phi),ufl.grad(q))-p*q.dx(1))*self.dx
        self.old.x.array[:]=self.u.x.array; self.u.x.scatter_forward(); self.old.x.scatter_forward()
        self.p=p; self.phi=phi
        options={'snes_type':'newtonls','snes_linesearch_type':'bt','snes_rtol':1e-10,'snes_atol':1e-11,
                 'snes_max_it':30,'snes_error_if_not_converged':False,'ksp_type':'preonly','pc_type':'lu',
                 'ksp_error_if_not_converged':True}
        self.residual=F; self.jacobian=ufl.derivative(F,self.u)
        self.problem=NonlinearProblem(F,self.u,bcs=self.bcs,J=self.jacobian,petsc_options_prefix=f'phase_{next(_ids)}_',petsc_options=options)
        self.monitor=[]; self.logs=[]; self.history=[]; self.snapshots=[]
        self.problem.solver.setMonitor(lambda snes,it,r:self.monitor.append({'iteration':it,'residual':float(r) if np.isfinite(r) else None}))
        self.energy=(-p*p/2+p**4/4+g/2*ufl.dot(ufl.grad(p),ufl.grad(p))-epsilon/2*ufl.dot(ufl.grad(phi),ufl.grad(phi))+p*phi.dx(1))
        self.equilibrate_phi()

    def equilibrate_phi(self):
        p,_=self.fields(); a=ufl.TrialFunction(self.T); q=ufl.TestFunction(self.T)
        bd=fem.locate_dofs_geometrical(self.T,self.electrode)
        val=fem.Function(self.T); val.interpolate(lambda x:-self.field*x[1])
        if self.mms_boundaries:val.x.array[:]=self.electrode_value.x.array
        problem=LinearProblem(self.epsilon*ufl.dot(ufl.grad(a),ufl.grad(q))*self.dx,(p*q.dx(1)+self.source_Q*q)*self.dx,
                              bcs=[fem.dirichletbc(val,bd)],petsc_options_prefix=f'init_{next(_ids)}_',petsc_options={'ksp_type':'preonly','pc_type':'lu'})
        result=problem.solve()
        if problem.solver.getConvergedReason()<=0: raise RuntimeError('initial Gauss solve failed')
        self.u.x.array[self.phimap]=result.x.array; self.u.x.scatter_forward()
        self.old.x.array[:]=self.u.x.array; self.old.x.scatter_forward()

    def fields(self):
        if not self.two: return self.u,None
        return self.u.sub(0).collapse(),self.u.sub(1).collapse()

    def solve(self,dt=None,steady=False,max_it=30):
        self.rate.value=0. if steady else 1.
        if dt is not None: self.dt.value=dt
        self.problem.solver.setTolerances(max_it=max_it)
        self.monitor=[]
        try:
            self.problem.solve()
            reason=int(self.problem.solver.getConvergedReason())
            norm=float(self.problem.solver.getFunctionNorm())
            ok=reason>0 and np.isfinite(norm) and norm<1e-8 and np.all(np.isfinite(self.u.x.array))
            error=None
        except (RuntimeError,PETSc.Error) as exc:
            ok=False; reason=int(self.problem.solver.getConvergedReason()); norm=float(self.problem.solver.getFunctionNorm()); error=str(exc)
        log={'dt':dt,'steady':steady,'reason':reason,'residual':norm if np.isfinite(norm) else None,'iterations':int(self.problem.solver.getIterationNumber()),
             'converged':bool(ok),'monitor':list(self.monitor),'error':error}
        self.logs.append(log)
        return ok

    def steady(self):
        saved=self.u.x.array.copy()
        if not self.solve(steady=True):
            self.u.x.array[:]=saved; self.u.x.scatter_forward()
            raise RuntimeError('steady nonlinear solve failed')
        self.old.x.array[:]=self.u.x.array; self.old.x.scatter_forward()

    def record(self,t):
        p,phi=self.fields(); area=self.volume
        vals=p.x.array.real
        coords=p.function_space.tabulate_dof_coordinates()
        # Horizontal middle row, genuine FE nodal crossing; no fabricated trajectory.
        choose=np.isclose(coords[:,1],2.) if self.two else np.ones(len(vals),dtype=bool)
        if self.dimension==3:choose&=np.isclose(coords[:,2],0.)
        x=coords[choose,0]; y=vals[choose]; order=np.argsort(x); x=x[order]; y=y[order]
        crossing=np.flatnonzero(y[:-1]*y[1:]<=0)
        pos=float(x[crossing[0]]-y[crossing[0]]*(x[crossing[0]+1]-x[crossing[0]])/(y[crossing[0]+1]-y[crossing[0]])) if len(crossing)==1 and y[crossing[0]+1]!=y[crossing[0]] else None
        row={'t':float(t),'mean_P':integral(self.p*self.dx)/area,'potential':integral(self.energy*self.dx),'wall_x':pos,'rate_rms':self.last_rate_rms}
        self.history.append(row)
        self.snapshots.append({'t':float(t),'P':vals.copy(),'phi':phi.x.array.real.copy() if phi else None})

    def evolve(self,end,dt,max_retries):
        if not 0<dt<1 or end<=0: raise ValueError('Require end>0 and 0<dt<1')
        if self.history:raise ValueError('One evolve trajectory per instance; restart/continuation is not implemented')
        self.record(0.); t=0.; proposed=dt; attempt=0;retries=0
        # Operational guard: repeated shrink events cannot create unbounded history/work.
        # This cap matches the deterministic preflight estimate; never coarsen/change input.
        accepted_cap=math.ceil(end/dt)*2**max_retries+1
        while t < end-1e-12:
            if len(self.history)-1>=accepted_cap:
                raise RuntimeError('Accepted-step resource cap reached; last accepted state retained')
            h=min(proposed,end-t); state=self.u.x.array.copy(); old=self.old.x.array.copy()
            accepted_dt=float(self.dt.value);field=self.field
            boundary=self.electrode_value.x.array.copy() if self.two else None
            boundary_states=[(value,value.x.array.copy()) for value,_ in self.mms_boundaries]
            self.time.value=t+h
            for value,expression in self.mms_boundaries:value.interpolate(expression);value.x.scatter_forward()
            ok=self.solve(h)
            self.logs[-1].update(attempt=attempt,start_time=t,target_time=t+h,accepted=bool(ok))
            attempt+=1
            if not ok:
                self.logs[-1]['trial_state_changed_before_rollback']=bool(not np.array_equal(self.u.x.array,state))
                self.logs[-1]['boundary_changed_during_trial']=bool(self.two and not np.array_equal(boundary,self.electrode_value.x.array))
                self.u.x.array[:]=state; self.old.x.array[:]=old
                self.u.x.scatter_forward(); self.old.x.scatter_forward()
                self.time.value=t
                self.dt.value=accepted_dt
                for value,saved_boundary in boundary_states:value.x.array[:]=saved_boundary;value.x.scatter_forward()
                self.logs[-1].update(restored_time=float(self.time.value),restored_dt=float(self.dt.value),field_unchanged=bool(self.field==field),boundary_unchanged=bool(not self.two or np.array_equal(boundary,self.electrode_value.x.array)))
                self.logs[-1]['rollback_exact']=bool(np.array_equal(self.u.x.array,state) and np.array_equal(self.old.x.array,old) and float(self.time.value)==t and float(self.dt.value)==accepted_dt and self.field==field and (not self.two or np.array_equal(boundary,self.electrode_value.x.array)) and all(np.array_equal(value.x.array,saved_boundary) for value,saved_boundary in boundary_states))
                if retries>=max_retries: raise RuntimeError(f'failed after {max_retries} halvings; state rolled back')
                retries+=1
                proposed=h/2; continue
            current=self.p; previous=ufl.split(self.old)[0] if self.two else self.old
            self.last_rate_rms=float(np.sqrt(integral((current-previous)**2*self.dx)/self.volume)/h)
            self.old.x.array[:]=self.u.x.array; self.old.x.scatter_forward()
            t+=h; self.record(t)
            retries=0
        return self

    def gauss(self,reconstruct=None):
        if not self.two: return {}
        p,phi=self.fields(); S=phi.function_space; q=ufl.TestFunction(S)
        from dolfinx.fem.petsc import assemble_vector
        form=fem.form((self.epsilon*ufl.dot(ufl.grad(phi),ufl.grad(q))-p*q.dx(1)-self.source_Q*q)*self.dx)
        r=assemble_vector(form); r.ghostUpdate(addv=PETSc.InsertMode.ADD,mode=PETSc.ScatterMode.REVERSE)
        boundary=fem.locate_dofs_geometrical(S,self.electrode)
        values=r.array.copy(); free=np.ones(len(values),dtype=bool); free[boundary]=False
        source_total=integral(self.source_Q*self.dx)
        weak=float(np.linalg.norm(values[free])); reaction_balance=float(abs(np.sum(values[boundary])+source_total))
        r.destroy()
        polar=[0]*self.dimension;polar[1]=p
        n=ufl.FacetNormal(self.m); D=-self.epsilon*ufl.grad(phi)+ufl.as_vector(polar)
        flux=integral(ufl.dot(D,n)*ufl.ds(domain=self.m))
        bd_error=float(np.max(abs(phi.x.array[boundary]-self.electrode_value.x.array[boundary])))
        if reconstruct is None:reconstruct=not self.mms
        reconstructed=self.reconstruct_flux(D) if reconstruct else {'rt0_status':'not_checked_for_this_case'}
        return {'free_weak_residual_l2':weak,'electrode_reaction_balance':reaction_balance,'raw_total_boundary_flux':flux,'source_integral':source_total,'raw_flux_source_imbalance':float(flux-source_total),'voltage_boundary_error':bd_error,**reconstructed}

    def reconstruct_flux(self,raw):
        """Constrained L2 RT0 projection: div D_h=0, zero side normal flux.

        This is explicit postprocessing, not a claim of strong CG1 conservation.
        Corrections are reported and must converge upon mesh refinement.
        """
        rt=element('RT',self.m.basix_cell(),1); dg=element('DG',self.m.basix_cell(),0)
        W=fem.functionspace(self.m,mixed_element([rt,dg])); sigma,lam=ufl.TrialFunctions(W); tau,q=ufl.TestFunctions(W)
        R,_=W.sub(0).collapse(); zero=fem.Function(R)
        def sides(x):
            mark=np.isclose(abs(x[0]),8)
            if self.dimension==3:mark|=np.isclose(abs(x[2]),2)
            return mark
        fdim=self.dimension-1
        facets=mesh.locate_entities_boundary(self.m,fdim,sides)
        dofs=fem.locate_dofs_topological((W.sub(0),R),fdim,facets)
        bc=fem.dirichletbc(zero,dofs,W.sub(0))
        a=(ufl.inner(sigma,tau)+lam*ufl.div(tau)+ufl.div(sigma)*q)*self.dx
        rhs=(ufl.inner(raw,tau)+self.source_Q*q)*self.dx
        lp=LinearProblem(a,rhs,bcs=[] if self.mms else [bc],petsc_options_prefix=f'flux_{next(_ids)}_',petsc_options={'ksp_type':'preonly','pc_type':'lu','pc_factor_mat_solver_type':'mumps','ksp_error_if_not_converged':True})
        sol=lp.solve()
        if lp.solver.getConvergedReason()<=0: raise RuntimeError('flux reconstruction failed')
        sig=sol.sub(0).collapse(); n=ufl.FacetNormal(self.m)
        self.flux_RT=sig
        Q,_=W.sub(1).collapse();a0=ufl.TrialFunction(Q);q0=ufl.TestFunction(Q)
        source0=fem.Function(Q)
        if self.mms:
            projection=LinearProblem(a0*q0*self.dx,self.source_Q*q0*self.dx,petsc_options_prefix=f'charge_projection_{next(_ids)}_',petsc_options={'ksp_type':'preonly','pc_type':'jacobi'})
            source0=projection.solve()
            if projection.solver.getConvergedReason()<=0:raise RuntimeError('DG0 source projection failed')
        self.flux_source_DG0=source0
        divergence=float(np.sqrt(integral((ufl.div(sig)-source0)**2*self.dx)/self.volume))
        total=integral(ufl.dot(sig,n)*ufl.ds(domain=self.m))
        correction=float(np.sqrt(integral(ufl.inner(sig-raw,sig-raw)*self.dx)/self.volume))
        tags=mesh.meshtags(self.m,fdim,np.sort(facets),np.ones(len(facets),dtype=np.int32))
        ds=ufl.Measure('ds',domain=self.m,subdomain_data=tags,metadata=DX)
        side_flux_rms=float(np.sqrt(integral(ufl.dot(sig,n)**2*ds(1))/integral(ufl.as_ufl(1.)*ds(1))))
        self.m.topology.create_connectivity(fdim,self.dimension)
        interior=ufl.Measure('dS',domain=self.m,metadata=DX)
        interior_area=integral(ufl.as_ufl(1.)*interior)
        jump_rt=float(np.sqrt(integral(ufl.jump(sig,n)**2*interior)/interior_area))
        jump_raw=float(np.sqrt(integral(ufl.jump(raw,n)**2*interior)/interior_area))
        if hasattr(self,'output') and self.output.is_dir():
            dofmap=np.array([sig.function_space.dofmap.cell_dofs(c) for c in range(self.m.topology.index_map(self.dimension).size_local)])
            np.savez_compressed(self.output/'flux_reconstruction.npz',coefficients=sig.x.array,cell_dofs=dofmap,basis='Basix RT degree 1 (RT0)',degree=1)
        result={'rt0_status':'passed','rt0_divergence_rms':divergence,'rt0_total_boundary_flux':float(total),'rt0_correction_rms':correction,
                'rt0_interior_normal_jump_rms':jump_rt,'raw_interior_normal_jump_rms':jump_raw,
                'rt0_flux_source_imbalance':float(total-integral(self.source_Q*self.dx)),
                'rt0_side_normal_rms':side_flux_rms,'raw_side_normal_rms':float(np.sqrt(integral(ufl.dot(raw,n)**2*ds(1))/integral(ufl.as_ufl(1.)*ds(1)))),
                'source_DG0_projection_rms':float(np.sqrt(integral((source0-self.source_Q)**2*self.dx)/self.volume)),
                'rt0_continuous_source_residual_rms':float(np.sqrt(integral((ufl.div(sig)-self.source_Q)**2*self.dx)/self.volume))}
        if self.mms:
            pol=[0]*self.dimension;pol[1]=self.exact_P;exact=-self.epsilon*ufl.grad(self.exact_phi)+ufl.as_vector(pol)
            result.update(raw_D_exact_rms=float(np.sqrt(integral(ufl.inner(raw-exact,raw-exact)*self.dx)/self.volume)),
                          rt0_D_exact_rms=float(np.sqrt(integral(ufl.inner(sig-exact,sig-exact)*self.dx)/self.volume)))
        return result

    def save(self,out):
        out=Path(out); out.mkdir(parents=True,exist_ok=True)
        self.output=out
        p,phi=self.fields(); p.name='P'
        coords=p.function_space.tabulate_dof_coordinates()
        data={'coordinates':coords,'P':p.x.array.real,'times':np.array([s['t'] for s in self.snapshots]),
              'P_history':np.array([s['P'] for s in self.snapshots])}
        if self.two:
            key='tetrahedra' if self.dimension==3 else 'triangles'
            data[key]=np.array([p.function_space.dofmap.cell_dofs(c) for c in range(self.m.topology.index_map(self.dimension).size_local)])
        with io.XDMFFile(self.m.comm,str(out/'fields.xdmf'),'w') as f:
            f.write_mesh(self.m)
            for s in self.snapshots:
                temp=fem.Function(p.function_space); temp.name='P'; temp.x.array[:]=s['P']; f.write_function(temp,s['t'])
            if not self.snapshots: f.write_function(p,0.)
            if phi:
                phi.name='phi'
                for s in self.snapshots:
                    tmp=fem.Function(phi.function_space); tmp.name='phi'; tmp.x.array[:]=s['phi']; f.write_function(tmp,s['t'])
                if not self.snapshots: f.write_function(phi,0.)
                W=fem.functionspace(self.m,('DG',0,(self.dimension,))); E=fem.Function(W); E.name='E'
                E.interpolate(fem.Expression(-ufl.grad(phi),W.element.interpolation_points))
                f.write_function(E,self.history[-1]['t'] if self.history else 0.)
                # DG electric field has its own cell coordinates in NPZ (not nodal smoothing).
                data.update(phi=phi.x.array.real,E=E.x.array.real.reshape(-1,self.dimension),E_coordinates=W.tabulate_dof_coordinates(),phi_history=np.array([s['phi'] for s in self.snapshots]))
        np.savez_compressed(out/'fields.npz',**data)
        (out/'history.json').write_text(json.dumps(self.history,indent=2,allow_nan=False))
        (out/'nonlinear.json').write_text(json.dumps(self.logs,indent=2,allow_nan=False))
        (out/'metadata.json').write_text(json.dumps({'dimension':self.dimension,'volume':self.volume,'polarization_axis':'y','polarization_components':1,'units':'dimensionless',
                    'g':self.g,'epsilon':self.epsilon,'applied_E':self.field,'mms':self.mms,'accepted_times':[s['t'] for s in self.snapshots]},indent=2,allow_nan=False))
        if self.history:
            import csv
            with (out/'history.csv').open('w',newline='') as f:
                writer=csv.writer(f);writer.writerow(['t','mean_P','electric_enthalpy','centerline_unique_wall_x'])
                writer.writerows([[h['t'],h['mean_P'],h['potential'],h['wall_x']] for h in self.history])
        return data
