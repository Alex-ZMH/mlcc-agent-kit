"""Standalone SI, serial, one-way electrothermal FEM. No runtime/Agent imports."""
from scientific_core.fenicsx import (integral_local as integral, owned_cell_count as ncells,
    scalar_dg0 as scalar, scalar_cell_values as cell_values,
    interpolate_dg0 as dg, export_scalar_dg0 as export)
from scientific_core.fenicsx import cell_dof_values as cell_values_vector
import json
import math
from pathlib import Path
from time import perf_counter
import numpy as np
import gmsh
import ufl
from dolfinx import fem, mesh, io, plot
from dolfinx.io import gmsh as gmshio
from dolfinx.fem.petsc import LinearProblem, assemble_vector
from mpi4py import MPI
from petsc4py import PETSc
from ..validation import body_height

EPS0=8.8541878128e-12
OPTIONS={'ksp_type':'preonly','pc_type':'lu','ksp_error_if_not_converged':True}

def write(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    def numeric(value):
        if isinstance(value,np.generic):return value.item()
        raise TypeError(f'Unsupported JSON value: {type(value)}')
    path.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False,default=numeric),encoding='utf-8')

def boundary_tags(m,length,height):
    m.topology.create_connectivity(1,2)
    ext=mesh.exterior_facet_indices(m.topology);mids=mesh.compute_midpoints(m,1,ext)
    tol=max(length,height)*1e-8
    # Ends are the controllable sink; top/bottom are the other outer faces.
    ends=(abs(mids[:,0])<tol)|(abs(mids[:,0]-length)<tol)
    return mesh.meshtags(m,1,ext,np.where(ends,31,32).astype(np.int32))

def rectangles(payload):
    p=payload['geometry'];r=[]
    for i in range(p['active_gap_count']+1):
        x0,x1=(0.,p['body_length_m']-p['right_margin_m']) if i%2==0 else (p['left_margin_m'],p['body_length_m'])
        y0=p['bottom_cover_m']+i*(p['dielectric_gap_m']+p['electrode_thickness_m'])
        r.append((x0,x1,y0,y0+p['electrode_thickness_m'],11+i%2))
    return r

def electric_tags(m,payload):
    """Straight-segment classifier adapted from vendor_geometry.build_mlcc."""
    m.topology.create_connectivity(1,2);ext=mesh.exterior_facet_indices(m.topology)
    mid=mesh.compute_midpoints(m,1,ext);vals=np.full(len(ext),13,dtype=np.int32)
    tol=payload['geometry']['body_length_m']*1e-8
    for x0,x1,y0,y1,tag in rectangles(payload):
        x,y=mid[:,0],mid[:,1]
        hit=((x>=x0-tol)&(x<=x1+tol)&((abs(y-y0)<tol)|(abs(y-y1)<tol)))|((y>=y0-tol)&(y<=y1+tol)&((abs(x-x0)<tol)|(abs(x-x1)<tol)))
        if np.any((vals[hit]!=13)&(vals[hit]!=tag)):raise ValueError('ambiguous electrode facet')
        vals[hit]=tag
    if not all(np.any(vals==t) for t in [11,12,13]):raise ValueError('missing electric boundary')
    return mesh.meshtags(m,1,ext,vals)

def device_mesh(payload,h,out,*,split_y=None,max_cells=150000):
    """One conforming OCC fragment; ceramic submesh has exact parent cell IDs."""
    if h<=0:raise ValueError('mesh size must be positive')
    p=payload['geometry'];L=p['body_length_m'];H=body_height(payload)
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.NumThreads',1);gmsh.model.add('ceramic_Ni')
        occ=gmsh.model.occ;body=occ.addRectangle(0,0,0,L,H);tools=[]
        for x0,x1,y0,y1,_ in rectangles(payload):tools.append((2,occ.addRectangle(x0,y0,0,x1-x0,y1-y0)))
        nmetal=len(tools)
        # AC experiment-only CAD extension: align a synthetic dielectric
        # interface with the mesh. Thermal solver and transfer are unchanged.
        if split_y is not None:
            if not 0<split_y<H:raise ValueError('dielectric interface outside body')
            tools.append((2,occ.addRectangle(0,0,0,L,split_y)))
        _,maps=occ.fragment([(2,body)],tools);occ.synchronize()
        metal={t for group in maps[1:1+nmetal] for dim,t in group if dim==2}
        allsurfs={t for dim,t in maps[0] if dim==2};ceramic=allsurfs-metal
        gmsh.model.addPhysicalGroup(2,sorted(ceramic),10);gmsh.model.setPhysicalName(2,10,'CERAMIC')
        gmsh.model.addPhysicalGroup(2,sorted(metal),20);gmsh.model.setPhysicalName(2,20,'NI')
        outer=gmsh.model.getBoundary([(2,t) for t in allsurfs],combined=True,oriented=False)
        gmsh.model.addPhysicalGroup(1,[t for dim,t in outer if dim==1],30)
        gmsh.option.setNumber('Mesh.MeshSizeMin',h);gmsh.option.setNumber('Mesh.MeshSizeMax',h)
        gmsh.model.mesh.generate(2)
        n=sum(len(v) for v in gmsh.model.mesh.getElements(2)[1])
        if n>max_cells:raise ValueError('Host mesh cell resource bound exceeded')
        gmsh.write(str(out/'mesh.msh'));data=gmshio.model_to_mesh(gmsh.model,MPI.COMM_WORLD,0,gdim=2)
    finally:gmsh.finalize()
    parent,ct=data.mesh,data.cell_tags
    labels=np.zeros(ncells(parent),dtype=np.int32);labels[ct.indices]=ct.values
    if set(labels)!={10,20}:raise ValueError('material partition incomplete')
    selected=ct.find(10);child,entity,_,_=mesh.create_submesh(parent,2,selected)
    mapping=entity.sub_topology_to_topology(np.arange(ncells(child),dtype=np.int32),False)
    if len(set(mapping.tolist()))!=len(mapping) or set(mapping.tolist())!=set(selected.tolist()):raise ValueError('bad cell map')
    # Independent geometric identity and cell area check (not only array order).
    a=mesh.compute_midpoints(parent,2,mapping);b=mesh.compute_midpoints(child,2,np.arange(ncells(child),dtype=np.int32))
    if not np.allclose(a,b,rtol=0,atol=1e-15):raise ValueError('submesh geometry mismatch')
    tags=electric_tags(child,payload)
    return parent,labels,child,mapping,tags,boundary_tags(parent,L,H)

def solve_linear(a,b,bcs,prefix):
    problem=LinearProblem(a,b,bcs=bcs,petsc_options_prefix=prefix,petsc_options=OPTIONS)
    start=perf_counter();sol=problem.solve();sol.x.scatter_forward()
    reason=int(problem.solver.getConvergedReason())
    r=problem.b.duplicate();problem.A.mult(sol.x.petsc_vec,r);r.axpy(-1.,problem.b)
    relative=float(r.norm()/max(problem.b.norm(),1e-30));r.destroy()
    if reason<=0 or not np.isfinite(sol.x.array).all():raise RuntimeError('linear solve failed')
    return sol,{'reason':reason,'iterations':int(problem.solver.getIterationNumber()),'relative_residual':relative,'seconds':perf_counter()-start}

def coefficient(loss,epsilon):
    kind=loss['model']
    if kind=='dc':
        s=float(loss['sigma_S_m'])
        if not math.isfinite(s) or s<0:raise ValueError('sigma must be finite and >=0')
        return s
    if kind=='ac':
        f=float(loss['frequency_Hz']);tan=float(loss['tan_delta'])
        if not all(math.isfinite(v) and v>=0 for v in [f,tan]):raise ValueError('invalid frequency/tan delta')
        if loss.get('voltage_convention') not in ['rms','peak']:raise ValueError('AC voltage convention required')
        return 2*np.pi*f*epsilon*tan
    if kind=='lossless':return 0.
    raise ValueError('unknown loss mechanism')

def electric(m,tags,va,vb,er,loss,depth):
    if not all(math.isfinite(v) for v in [va,vb,er,depth]) or er<=0 or depth<=0:raise ValueError('invalid electrical input')
    V=fem.functionspace(m,('Lagrange',1));u,v=ufl.TrialFunction(V),ufl.TestFunction(V)
    eps=EPS0*er;factor=coefficient(loss,eps)
    if loss['model']=='ac' and loss['voltage_convention']=='peak':va/=np.sqrt(2);vb/=np.sqrt(2)
    dofs=[fem.locate_dofs_topological(V,1,tags.find(t)) for t in [11,12]]
    bcs=[fem.dirichletbc(PETSc.ScalarType(x),d,V) for x,d in zip([va,vb],dofs)]
    # Same P1 weak form and PETSc direct path as device_fem/fenicsx.py.
    phi,solver=solve_linear(eps*ufl.inner(ufl.grad(u),ufl.grad(v))*ufl.dx,fem.Constant(m,0.)*v*ufl.dx,bcs,'et_e_')
    phi.name='potential_V';E=dg(-ufl.grad(phi),m,'E_V_m',True)
    q=scalar(m,0.,'q_W_m3') if factor==0 else dg(factor*ufl.inner(E,E),m,'q_W_m3')
    loss_power=depth*integral(q*ufl.dx)
    R=assemble_vector(fem.form(eps*ufl.inner(ufl.grad(phi),ufl.grad(v))*ufl.dx))
    currents=[float(np.sum(R.array[d]))*factor/eps*depth for d in dofs];R.destroy()
    terminal_power=va*currents[0]+vb*currents[1]
    n=ufl.FacetNormal(m);ds=ufl.Measure('ds',domain=m,subdomain_data=tags)
    raw_currents=[-depth*integral(factor*ufl.dot(E,n)*ds(t)) for t in [11,12]]
    conduction_error=None
    if loss['model']=='dc' and factor>0:
        conductive,_=solve_linear(factor*ufl.inner(ufl.grad(u),ufl.grad(v))*ufl.dx,fem.Constant(m,0.)*v*ufl.dx,bcs,'et_dc_')
        conduction_error=float(np.max(abs(conductive.x.array-phi.x.array))/max(abs(va-vb),1.))
    report={'solver':solver,'loss_power_W':loss_power,'power_per_depth_W_m':loss_power/depth,
            'terminal_power_W':terminal_power,'terminal_current_or_equivalent_loss_current_A':currents,
            'raw_terminal_current_or_equivalent_A':raw_currents,
            'terminal_power_relative_error':abs(terminal_power-loss_power)/max(loss_power,1e-30),
            'conductive_phi_difference_relative':conduction_error,
            'electrostatic_energy_J':depth*.5*integral(eps*ufl.inner(E,E)*ufl.dx),
            'effective_voltage_difference_rms_or_dc_V':va-vb,'loss_factor_S_m':factor,
            'Emax_V_m':float(np.max(np.linalg.norm(E.x.array.reshape(-1,2),axis=1))),
            'qmin_W_m3':float(q.x.array.min()),'qmax_W_m3':float(q.x.array.max()),
            'note':'AC currents here are equivalent loss-current reactions, not full complex terminal admittance'}
    return phi,E,q,report

def transfer(q,parent,mapping,labels):
    child=q.function_space.mesh
    if len(mapping)!=ncells(child) or len(set(mapping.tolist()))!=len(mapping) or np.any(labels[mapping]!=10):raise ValueError('incompatible source/target cell identity')
    if not np.allclose(mesh.compute_midpoints(parent,2,mapping),mesh.compute_midpoints(child,2,np.arange(ncells(child),dtype=np.int32)),rtol=0,atol=1e-15):raise ValueError('incompatible mesh geometry')
    for c,p in enumerate(mapping):
        a=parent.geometry.x[parent.geometry.dofmap[p]];b=child.geometry.x[child.geometry.dofmap[c]]
        a=a[np.lexsort(a.T[::-1])];b=b[np.lexsort(b.T[::-1])]
        if not np.allclose(a,b,rtol=0,atol=1e-15):raise ValueError('incompatible triangle connectivity/coordinates')
    result=np.zeros(ncells(parent));result[mapping]=cell_values(q);out=scalar(parent,result,'q_W_m3')
    incoming=integral(q*ufl.dx);received=integral(out*ufl.dx)
    if abs(incoming-received)>1e-12*max(abs(incoming),1e-20):raise ValueError('nonconservative transfer')
    return out,{'relative_error':abs(incoming-received)/max(abs(incoming),1e-30),'input_W_m':incoming,'received_W_m':received,
                'Ni_source_max_W_m3':float(np.max(abs(result[labels==20]))) if np.any(labels==20) else 0.,'mapped_cells':len(mapping)}

def thermal(m,k,q,tags,bc,depth,Tinf=300.):
    kval=cell_values(k)
    if not np.isfinite(kval).all() or np.min(kval)<=0:raise ValueError('k must be positive finite')
    if q.function_space.mesh is not m or k.function_space.mesh is not m:raise ValueError('incompatible thermal mesh')
    if not math.isfinite(depth) or depth<=0 or not math.isfinite(Tinf) or Tinf<=0:raise ValueError('invalid depth/ambient')
    kind=bc['kind'];h=float(bc.get('h_W_m2K',0.));groups=bc.get('groups',[31])
    if not math.isfinite(h) or h<0:raise ValueError('invalid convection coefficient')
    if kind not in ['dirichlet','robin','insulated']:raise ValueError('invalid thermal boundary')
    if kind=='insulated' or (kind=='robin' and h==0):raise ValueError('no thermal sink: steady Neumann problem has no unique solution')
    if not groups or any(len(tags.find(g))==0 for g in groups):raise ValueError('empty thermal sink')
    V=fem.functionspace(m,('Lagrange',1));u,v=ufl.TrialFunction(V),ufl.TestFunction(V)
    dx=ufl.Measure('dx',domain=m);ds=ufl.Measure('ds',domain=m,subdomain_data=tags)
    a=k*ufl.inner(ufl.grad(u),ufl.grad(v))*dx;b=q*v*dx;bcs=[];dofs=np.array([],dtype=np.int32)
    if kind=='dirichlet':
        dofs=np.unique(np.concatenate([fem.locate_dofs_topological(V,1,tags.find(g)) for g in groups]));bcs=[fem.dirichletbc(PETSc.ScalarType(0.),dofs,V)]
    else:
        for g in groups:a+=h*u*v*ds(g)
    theta,solver=solve_linear(a,b,bcs,'et_t_');theta.name='temperature_rise_K'
    T=fem.Function(V,name='temperature_K');T.x.array[:]=theta.x.array+Tinf
    flux=dg(-k*ufl.grad(theta),m,'heat_flux_W_m2',True)
    grad=dg(ufl.grad(theta),m,'temperature_gradient_K_m',True)
    source=depth*integral(q*dx)
    R=assemble_vector(fem.form(ufl.action(a,theta)-b));free=R.array.copy();reaction=-depth*float(np.sum(free[dofs]));free[dofs]=0
    weak=float(np.linalg.norm(free)/max(np.linalg.norm(assemble_vector(fem.form(b)).array),1e-30));R.destroy()
    convection=depth*sum(integral(h*theta*ds(g)) for g in groups) if kind=='robin' else 0.
    out=reaction+convection
    n=ufl.FacetNormal(m);raw=depth*integral(ufl.dot(-k*ufl.grad(theta),n)*ufl.ds(domain=m))
    pergroup={str(g):depth*integral(ufl.dot(-k*ufl.grad(theta),n)*ds(g)) for g in set(tags.values.tolist())}
    avg=integral(theta*dx)/integral(fem.Constant(m,1.)*dx)
    coords=V.tabulate_dof_coordinates();idx=int(np.argmax(theta.x.array));peak=float(theta.x.array[idx])
    report={'solver':solver,'weak_residual_relative':weak,'source_power_W':source,'outward_power_W':out,
            'dirichlet_reaction_out_W':reaction,'robin_out_W':convection,'raw_gradient_out_W':raw,'raw_flux_by_tag_W':pergroup,
            'balance_relative':abs(out-source)/max(abs(source),1e-30),'balance_absolute_W':abs(out-source),
            'raw_balance_relative':abs(raw-source)/max(abs(source),1e-30),
            'Tmax_K':Tinf+peak,'Tavg_K':Tinf+avg,'dTmax_K':peak,'dTavg_K':avg,
            'hotspot_xy_m':coords[idx,:2].tolist(),'gradient_max_K_m':float(np.max(np.linalg.norm(grad.x.array.reshape(-1,2),axis=1))),
            'Rth_hotspot_K_W':peak/source if source>0 else None,'Rth_average_K_W':avg/source if source>0 else None,
            'minimum_rise_K':float(theta.x.array.min()),'boundary':bc,'Tinf_K':Tinf,
            'flux_convention':'positive outward -k grad(T).n; reaction flux is discrete, raw gradient is independent diagnostic'}
    return T,theta,flux,report



