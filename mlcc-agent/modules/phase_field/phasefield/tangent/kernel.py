"""Equilibrium-only UFL AD + implicit sensitivity. Frozen vector kernel is read-only.

The new unknown is (P,psi), phi=psi-Ebar.x, psi|all exterior=0.
Ebar is a genuine UFL coefficient; each AD direction is spatially constant.
No BE mass or time step enters the equilibrium or sensitivity equations.
"""
from pathlib import Path
import sys,itertools,time,hashlib,json,resource
import numpy as np
import ufl
from dolfinx import fem,io,plot
from dolfinx.fem.petsc import NonlinearProblem,assemble_matrix,assemble_vector,set_bc
from petsc4py import PETSc
from mpi4py import MPI
from ..vector.kernel import VectorPhaseField,write,integral
from ..vector.physics import Parameters,wall_profile,hessian
from scientific_core.fenicsx import interpolate_dg0,cell_dof_values
IDS=itertools.count()

class InvalidTangent(RuntimeError):pass

class TangentSystem:
    def __init__(self,dimension=2,cells=None,parameters=None,kind='uniform',initial=None,wall_half_length=8.,atol=1e-12):
        self.spec=dict(dimension=dimension,cells=cells or ([32]+[2]*(dimension-1) if kind.startswith('wall') else [2]*dimension),parameters=parameters or {},kind=kind,initial=initial,wall_half_length=wall_half_length,atol=atol)
        if not np.isfinite(atol) or not 0<atol<=1e-8:raise ValueError('strict finite equilibrium tolerance required')
        self.base=VectorPhaseField(dimension,self.spec['cells'],parameters,kind,initial)
        b=self.base;D=dimension;self.D=D;self.u=b.u;self.V=b.V;self.dx=b.dx;self.p=b.par;self.maps=b.maps;self.P=b.P;self.psi=b.phi
        if b.wallkind:
            if not np.isfinite(wall_half_length) or not 1<=wall_half_length<=8:raise ValueError('explicit finite specimen half length in [1,8] required')
            # Explicit physical specimen geometry, no internal numerical pinning.
            q=b.m.geometry.x[:,:D]@b.R;q[:,0]*=wall_half_length/8;b.m.geometry.x[:,:D]=q@b.R.T;b.lo[0]=-wall_half_length;b.hi[0]=wall_half_length
            b.xy=b.S.tabulate_dof_coordinates();b.qcoords=b.xy[:,:D]@b.R;b.volume=float(np.prod(b.hi-b.lo))
            for i,v,dofs in b.pbc:
                v.interpolate(lambda x,i=i:wall_profile((b.R.T@x[:D])[0],D,b.wallkind,b.par)[:,i]);self.u.x.array[b.maps[i][dofs]]=v.x.array[dofs]
            for i in range(D):
                z=fem.Function(b.spaces[i]);z.interpolate(lambda x,i=i:wall_profile((b.R.T@x[:D])[0],D,b.wallkind,b.par,1.05)[:,i]);self.u.x.array[b.maps[i]]=z.x.array
                for j,v,dofs in b.pbc:
                    if j==i:self.u.x.array[b.maps[i][dofs]]=v.x.array[dofs]
        self.volume=integral(1.*self.dx);self.control=fem.Function(fem.functionspace(b.m,('DG',0,(D,))),name='Ebar');self.direction=fem.Function(self.control.function_space)
        self.E=self.control-ufl.grad(self.psi);self.phi=self.psi-ufl.dot(self.control,ufl.SpatialCoordinate(b.m));self.displacement=self.p.epsilon*self.E+self.P
        tests=ufl.TestFunctions(self.V);v=ufl.as_vector(tests[:D]);q=tests[D]
        # Bulk/gradient from the exact frozen kernel, differentiated with UFL.
        bulk_gradient=ufl.derivative((b.fbulk+b.fgrad)*self.dx,self.u,ufl.as_vector(tests))
        self.F=bulk_gradient-ufl.dot(self.E,v)*self.dx+(-self.p.epsilon*ufl.dot(self.E,ufl.grad(q))-ufl.dot(self.P,ufl.grad(q)))*self.dx
        self.J=ufl.derivative(self.F,self.u);self.dR=ufl.derivative(self.F,self.control,self.direction)
        self.H=b.fbulk+b.fgrad-self.p.epsilon/2*ufl.dot(self.E,self.E)-ufl.dot(self.P,self.E)
        self.zero=fem.Function(b.spaces[D]);dofs=fem.locate_dofs_geometrical((self.V.sub(D),b.spaces[D]),b.boundary)
        self.bcs=b.bcs[:-1]+[fem.dirichletbc(self.zero,dofs,self.V.sub(D))];self.constrained=np.unique(np.concatenate([bc.dof_indices()[0] for bc in self.bcs]));self.free=np.setdiff1d(np.arange(len(self.u.x.array)),self.constrained)
        self.problem=NonlinearProblem(self.F,self.u,J=self.J,bcs=self.bcs,petsc_options_prefix=f'tangent_eq_{next(IDS)}_',petsc_options={'snes_type':'newtonls','snes_linesearch_type':'bt','snes_atol':atol,'snes_rtol':1e-12,'snes_max_it':60,'snes_error_if_not_converged':False,'ksp_type':'preonly','pc_type':'lu','pc_factor_mat_solver_type':'mumps','ksp_error_if_not_converged':True})
        self.monitor=[];self.problem.solver.setMonitor(lambda s,i,n:self.monitor.append({'iteration':i,'residual':float(n)}));self.path=[];self.field=np.zeros(D);self.logs=[];self.atol=atol
        self.mesh_id=hashlib.sha256(b.S.tabulate_dof_coordinates().tobytes()+np.array(self.spec['cells']).tobytes()+np.array([D]).tobytes()).hexdigest()
        self.u.x.array[self.maps[D]]=0.;self.set_field(np.zeros(D));self.u.x.scatter_forward()
        self.mass=assemble_matrix(fem.form(ufl.inner(ufl.TrialFunction(self.V),ufl.TestFunction(self.V))*self.dx));self.mass.assemble()
    def set_field(self,E):
        E=np.asarray(E,float)
        if E.shape!=(self.D,) or not np.isfinite(E).all():raise ValueError('finite dimension-matched macro field required')
        self.field=E.copy();self.control.x.array[:]=np.tile(E,len(self.control.x.array)//self.D);self.control.x.scatter_forward()
    def residual(self):
        r=assemble_vector(fem.form(self.F));vals=r.array.copy();r.destroy();return float(np.linalg.norm(vals[self.free]))
    def solve(self,E=None,append=True,max_it=60):
        old=self.u.x.array.copy();oldE=self.field.copy();oldpath=len(self.path)
        if E is not None:self.set_field(E)
        self.monitor=[];self.problem.solver.setTolerances(atol=self.atol,rtol=1e-12,max_it=max_it);start=time.perf_counter();err=None
        try:
            self.problem.solve();reason=int(self.problem.solver.getConvergedReason());r=self.residual();ok=reason>0 and r<max(5*self.atol,1e-11) and np.isfinite(self.u.x.array).all()
        except (RuntimeError,PETSc.Error) as exc:reason=int(self.problem.solver.getConvergedReason());r=None;ok=False;err=str(exc)
        row={'bias':self.field.tolist(),'reason':reason,'residual':r,'iterations':int(self.problem.solver.getIterationNumber()),'seconds':time.perf_counter()-start,'monitor':self.monitor.copy(),'accepted':bool(ok),'error':err};self.logs.append(row)
        if not ok:
            changed=bool(np.max(abs(self.u.x.array-old))>0);self.u.x.array[:]=old;self.set_field(oldE);self.u.x.scatter_forward();row.update(rollback_exact=bool(np.array_equal(old,self.u.x.array) and np.array_equal(oldE,self.field) and oldpath==len(self.path)),trial_changed=changed);raise InvalidTangent('equilibrium solve failed; complete bias branch restored')
        if append:self.path.append({'bias':self.field.tolist(),'mean_P':self.means(self.P).tolist(),'residual':r,'state_sha256':hashlib.sha256(self.u.x.array.tobytes()).hexdigest()})
        return self
    def means(self,expr):return np.array([integral(expr[i]*self.dx)/self.volume for i in range(self.D)])
    def checkpoint(self):return {'u':self.u.x.array.copy(),'field':self.field.copy(),'path':json.loads(json.dumps(self.path)),'mesh_id':self.mesh_id}
    def restore(self,s):
        if s['u'].shape!=self.u.x.array.shape or not np.isfinite(s['u']).all() or s.get('mesh_id')!=self.mesh_id:raise ValueError('invalid or mesh-incompatible branch checkpoint')
        self.u.x.array[:]=s['u'];self.set_field(s['field']);self.path=json.loads(json.dumps(s['path']));self.u.x.scatter_forward()
    def stability(self):
        """Eliminate phi; inspect mass-scaled constrained energy Hessian, not saddle J."""
        A=assemble_matrix(fem.form(self.J));A.assemble();dense=A.getValues(range(A.getSize()[0]),range(A.getSize()[1]));A.destroy()
        pi=np.concatenate([m[~np.isin(m,self.constrained)] for m in self.maps[:self.D]]);qi=np.setdiff1d(self.maps[self.D],self.constrained)
        PP=dense[np.ix_(pi,pi)];PQ=dense[np.ix_(pi,qi)];QP=dense[np.ix_(qi,pi)];QQ=dense[np.ix_(qi,qi)]
        S=PP-PQ@np.linalg.solve(QQ,QP) if len(qi) else PP.copy();M=self.mass.getValues(pi,pi);e,U=np.linalg.eigh(M);invsqrt=(U/np.sqrt(e))@U.T;K=invsqrt@((S+S.T)/2)@invsqrt;lam=np.linalg.eigvalsh(K);asym=np.linalg.norm(S-S.T)/max(np.linalg.norm(S),1.)
        # Scale-relative diagnostic precision for finite dimensional local differentiability.
        cut=1e-7*max(1.,float(np.max(abs(lam))));status='stable' if lam[0]>cut else 'unstable' if lam[0]<-cut else 'near_singular'
        return {'status':status,'minimum_reduced_energy_eigenvalue':float(lam[0]),'maximum_reduced_energy_eigenvalue':float(lam[-1]),'spectral_condition':float(max(abs(lam))/max(min(abs(lam)),1e-300)),'classification_cutoff':cut,'negative_modes':int(np.sum(lam < -cut)),'near_zero_modes':int(np.sum(abs(lam)<=cut)),'Schur_symmetry_relative':float(asym),'free_P_DOFs':len(pi),'free_phi_DOFs':len(qi),'eigenvalues':lam.tolist(),'method':'mass-scaled static P energy Hessian after eliminating psi under fixed-voltage and stated P end constraints; no BE regularization'}
    def tangent(self,frozen=False,require_stable=True):
        if self.residual()>1e-9:raise InvalidTangent('not a static equilibrium: sensitivity refused')
        stability=self.stability()
        if require_stable and stability['status']!='stable':raise InvalidTangent('unstable or near-singular equilibrium: no valid relaxed material tangent')
        bcs=self.bcs.copy()
        if frozen:
            for i in range(self.D):
                z=fem.Function(self.base.spaces[i]);z.x.array[:]=0.;pairs=[self.maps[i],np.arange(len(self.maps[i]),dtype=np.int32)];bcs.append(fem.dirichletbc(z,pairs,self.V.sub(i)))
        constrained=np.unique(np.concatenate([bc.dof_indices()[0] for bc in bcs]));A=assemble_matrix(fem.form(self.J),bcs=bcs);A.assemble();ksp=PETSc.KSP().create(MPI.COMM_WORLD);ksp.setOperators(A);ksp.setType('preonly');ksp.getPC().setType('lu');ksp.getPC().setFactorSolverType('mumps');ksp.setErrorIfNotConverged(True)
        tensor=np.zeros((self.D,self.D));bg=tensor.copy();pol=tensor.copy();emean=tensor.copy();sens=[];logs=[]
        start=time.perf_counter()
        for j in range(self.D):
            self.direction.x.array[:]=np.tile(np.eye(self.D)[j],len(self.direction.x.array)//self.D);self.direction.x.scatter_forward();rhs=assemble_vector(fem.form(-self.dR));rhs.array[constrained]=0.;svec=A.createVecRight();t0=time.perf_counter();ksp.solve(rhs,svec);r=A.createVecLeft();A.mult(svec,r);r.axpy(-1.,rhs);res=r.norm()/max(rhs.norm(),1.)
            s=fem.Function(self.V);s.x.array[:]=svec.array;s.x.scatter_forward()
            for i in range(self.D):
                for expr,target in [(self.displacement,tensor),(self.p.epsilon*self.E,bg),(self.P,pol),(self.E,emean)]:
                    Q=(expr[i]/self.volume)*self.dx;deriv=ufl.derivative(Q,self.control,self.direction)+ufl.derivative(Q,self.u,s);target[i,j]=integral(deriv)
            sens.append(s.x.array.copy());logs.append({'direction':j,'linear_relative_residual':float(res),'reason':int(ksp.getConvergedReason()),'seconds':time.perf_counter()-t0,'rhs_norm':float(rhs.norm()),'sensitivity_norm':float(svec.norm())});rhs.destroy();svec.destroy();r.destroy()
        elapsed=time.perf_counter()-start;ksp.destroy();A.destroy();self.sensitivities=np.array(sens)
        return {'dimension':self.D,'physics_model':'frozen vector V0.3 dimensionless quartic LGD + isotropic gradient + self-consistent electrostatics','response_type':'frozen_polarization' if frozen else 'relaxed_quasistatic_polarization','bias_field':self.field.tolist(),'actual_mean_field':self.means(self.E).tolist(),'mean_displacement':self.means(self.displacement).tolist(),'mean_polarization':self.means(self.P).tolist(),'loading_path':self.path.copy(),'branch_id':hashlib.sha256(self.u.x.array.tobytes()).hexdigest(),'equilibrium_residual':self.residual(),'background_permittivity':bg.tolist(),'polarization_tangent_contribution':pol.tolist(),'total_tangent_permittivity':tensor.tolist(),'actual_mean_field_response':emean.tolist(),'mean_field_response_condition':float(np.linalg.cond(emean)),'ad_sensitivity_residuals':logs,'seconds_all_directions':elapsed,'tensor_units':'dimensionless absolute D/E response; NOT relative SI permittivity','normalization_scales':{'P0':None,'E0':None,'SI_conversion':'only after physical P0,E0 supplied: epsilon_abs=(P0/E0)*epsilon_star, epsilon_r=epsilon_abs/epsilon0'},'stability_diagnostics':stability,'mesh':{'cells':self.spec['cells'],'simplexes':self.base.m.topology.index_map(self.D).size_local,'DOFs_per_component':len(self.maps[0]),'total_DOFs':len(self.u.x.array),'volume':self.volume},'boundary':'ALL exterior psi=0 => phi=-Ebar.x; P natural except fixed prescribed wall-end values; no periodicity/internal pins','applicability_limits':['synthetic dimensionless model, no material calibration','finite-specimen fixed-voltage response; not universal periodic homogenized material tensor','wall-end polarization constraints and specimen size affect wall response','no finite frequency, elasticity or RVE integration'],'validation_status':'computed_pending_independent_validation'}
    def save(self,out,result=None,sensitivity=None):
        out=Path(out);out.mkdir(parents=True,exist_ok=False);b=self.base;P=np.column_stack([self.u.x.array[m] for m in self.maps[:self.D]]);psi=self.u.x.array[self.maps[self.D]].copy();coords=b.S.tabulate_dof_coordinates();phi=psi-coords[:,:self.D]@self.field;top,types,points=plot.vtk_mesh(b.S);cells=top.reshape(-1,self.D+2)[:,1:]
        arrays={'coordinates':points,'cells':cells,'P':P,'psi':psi,'phi':phi,'bias':self.field,'mixed_state':self.u.x.array,'maps':np.array(self.maps),'constrained':self.constrained,'mass_volume':self.volume,'mesh_id':self.mesh_id}
        if sensitivity is not None:arrays['sensitivities']=sensitivity
        np.savez_compressed(out/'fields.npz',**arrays)
        import pyvista as pv
        grid=pv.UnstructuredGrid(top,types,points);grid.point_data['P']=np.pad(P,((0,0),(0,3-self.D)));grid.point_data['phi']=phi;grid.point_data['psi']=psi
        for i in range(self.D):grid.point_data['P'+'xyz'[i]]=P[:,i]
        z=interpolate_dg0(self.E,b.m,'E',vector=True);grid.cell_data['E']=np.pad(cell_dof_values(z),((0,0),(0,3-self.D)))
        grid.cell_data['D']=np.pad(self.p.epsilon*cell_dof_values(z)+P[cells].mean(axis=1),((0,0),(0,3-self.D)))
        if sensitivity is not None:
            for j,row in enumerate(sensitivity):
                for i in range(self.D):grid.point_data[f'dP{i}_dE{j}']=row[self.maps[i]]
                s=fem.Function(self.V);s.x.array[:]=row;gradpsi=ufl.grad(ufl.split(s)[self.D]);ez=interpolate_dg0(ufl.as_vector(np.eye(self.D)[j])-gradpsi,b.m,'dE',vector=True);grid.cell_data[f'dE_dE{j}']=np.pad(cell_dof_values(ez),((0,0),(0,3-self.D)));grid.point_data[f'dphi_dE{j}']=row[self.maps[self.D]]-coords[:,j]
        grid.save(out/'fields.vtu')
        with io.XDMFFile(MPI.COMM_WORLD,str(out/'fields.xdmf'),'w') as x:
            x.write_mesh(b.m)
            for i in range(self.D):s=self.u.sub(i).collapse();s.name='P'+'xyz'[i];x.write_function(s)
            ph=fem.Function(b.spaces[self.D],name='phi');ph.x.array[:]=phi;x.write_function(ph);x.write_function(z)
        write(out/'config.json',self.spec);write(out/'loading_path.json',self.path);write(out/'nonlinear.json',self.logs)
        write(out/'resources.json',{'simplexes':len(cells),'DOFs_per_P_component':len(P),'phi_DOFs':len(phi),'total_DOFs':len(self.u.x.array),'process_cumulative_peak_RSS_MiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'scope':'single-rank direct LU scientific prototype'})
        if result is not None:write(out/'tensor.json',result)
        return out
