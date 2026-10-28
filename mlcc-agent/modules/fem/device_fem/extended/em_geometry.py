"""Conforming ceramic/Ni/air domain with two connected Ni electrode networks."""
import numpy as np
import gmsh
from mpi4py import MPI
from dolfinx import mesh
from dolfinx.io import gmsh as gmshio
from .thermal_core import rectangles,body_height,ncells,write
from .em_solver import tags

def build(payload,h,out,bus=20e-6,feed=40e-6,bottom=10e-6,*,max_cells=150000):
    out.mkdir(parents=True,exist_ok=True)
    p=payload['geometry'];L=p['body_length_m'];H=body_height(payload)
    if min(h,bus,feed,bottom)<=0:raise ValueError('positive geometry/mesh required')
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal',0);gmsh.option.setNumber('General.NumThreads',1);gmsh.model.add('MLCC_EM')
        o=gmsh.model.occ;outer=o.addRectangle(-bus,-bottom,0,L+2*bus,H+bottom+feed)
        tools=[(2,o.addRectangle(0,0,0,L,H))]
        for x0,x1,y0,y1,_ in rectangles(payload):tools.append((2,o.addRectangle(x0,y0,0,x1-x0,y1-y0)))
        tools.extend([(2,o.addRectangle(-bus,0,0,bus,H)),(2,o.addRectangle(L,0,0,bus,H))])
        _,maps=o.fragment([(2,outer)],tools);o.synchronize()
        allsurf={t for d,t in maps[0] if d==2};metal={t for group in maps[2:] for d,t in group if d==2}
        ceramic={t for d,t in maps[1] if d==2}-metal;air=allsurf-metal-ceramic
        for label,group in [(10,ceramic),(20,metal),(30,air)]:gmsh.model.addPhysicalGroup(2,sorted(group),label)
        boundary=gmsh.model.getBoundary([(2,t) for t in allsurf],combined=True,oriented=False)
        gmsh.model.addPhysicalGroup(1,[t for d,t in boundary if d==1],90)
        gmsh.option.setNumber('Mesh.MeshSizeMin',h);gmsh.option.setNumber('Mesh.MeshSizeMax',h);gmsh.model.mesh.generate(2)
        n=sum(len(v) for v in gmsh.model.mesh.getElements(2)[1])
        if n>max_cells:raise ValueError('Host mesh cell resource bound exceeded')
        gmsh.write(str(out/'mesh.msh'));data=gmshio.model_to_mesh(gmsh.model,MPI.COMM_WORLD,0,gdim=2)
    finally:gmsh.finalize()
    m=data.mesh;regions=np.zeros(ncells(m),np.int32);regions[data.cell_tags.indices]=data.cell_tags.values
    if set(regions)!={10,20,30}:raise ValueError('incomplete material partition')
    ft=tags(m,-bus,L+bus,-bottom,H+feed)
    # Connected components through shared facets, not just apparent touching in a plot.
    m.topology.create_connectivity(2,1);m.topology.create_connectivity(1,2)
    c2f=m.topology.connectivity(2,1);f2c=m.topology.connectivity(1,2)
    remaining=set(np.flatnonzero(regions==20).tolist());components=[]
    while remaining:
        stack=[remaining.pop()];cc=[]
        while stack:
            k=stack.pop();cc.append(k)
            for facet in c2f.links(k):
                for neighbor in f2c.links(facet):
                    if int(neighbor) in remaining:remaining.remove(int(neighbor));stack.append(int(neighbor))
        components.append(cc)
    if len(components)!=2:raise ValueError('Ni networks must have exactly two disconnected components')
    contacts=[]
    for cc in components:
        mids=mesh.compute_midpoints(m,2,np.array(cc,np.int32));contacts.append('A' if mids[:,0].min()<0 else 'B')
    if sorted(contacts)!=['A','B']:raise ValueError('Ni contact connectivity failed')
    diag={'cells':ncells(m),'Ni_component_cell_counts':list(map(len,components)),'Ni_contact_networks':contacts,
          'L_m':L,'body_height_m':H,'bus_width_m':bus,'feed_air_m':feed,'bottom_air_m':bottom,'h_m':h}
    write(out/'geometry.json',diag);return m,ft,regions,diag

def solid(m,regions,L,bus):
    selected=np.flatnonzero(regions!=30).astype(np.int32);s,entity,_,_=mesh.create_submesh(m,2,selected)
    mapping=entity.sub_topology_to_topology(np.arange(ncells(s),dtype=np.int32),False)
    if set(mapping)!=set(selected):raise ValueError('invalid thermal entity map')
    if not np.allclose(mesh.compute_midpoints(m,2,mapping),mesh.compute_midpoints(s,2,np.arange(ncells(s),dtype=np.int32)),rtol=0,atol=1e-15):raise ValueError('thermal map geometry mismatch')
    s.topology.create_connectivity(1,2);ext=mesh.exterior_facet_indices(s.topology);mid=mesh.compute_midpoints(s,1,ext)
    ends=(abs(mid[:,0]+bus)<1e-12)|(abs(mid[:,0]-L-bus)<1e-12)
    ft=mesh.meshtags(s,1,ext,np.where(ends,31,32).astype(np.int32))
    return s,mapping,regions[mapping],ft
