"""OCC disjoint regions, true matching periodic Gmsh boundary and material audit."""
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
import hashlib,json
import numpy as np
import gmsh
from dolfinx import mesh,fem
from dolfinx.io import gmsh as gmshio
from mpi4py import MPI
from .fem_common import write,ncells,scalar,integral
import ufl

@dataclass
class RVEMesh:
    mesh:object
    labels:np.ndarray
    facets:object
    micro:dict
    diagnostics:dict
    root:Path

def boundaries(m,L):
    m.topology.create_connectivity(1,2);ext=mesh.exterior_facet_indices(m.topology);xy=mesh.compute_midpoints(m,1,ext)
    v=np.full(len(ext),5,np.int32);tol=L*1e-8
    for axis,value,tag in [(0,0.,1),(0,L,2),(1,0.,3),(1,L,4)]:v[abs(xy[:,axis]-value)<tol]=tag
    return mesh.meshtags(m,1,ext,v)

def create(micro,h,root,max_cells=90000):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);write(root/'microstructure.json',micro)
    if not np.isfinite(h) or not .003<=h<=.2:raise ValueError('normalized h must be .003..0.2')
    cfg=micro['config'];thickness=min([cfg[k] for k in ['gb_width','shell'] if cfg.get(k,0)>0],default=1.)
    if micro['config']['kind']=='polycrystal' and h>thickness/1.5:raise ValueError('gb/shell require at least 1.5 target elements across nominal width')
    start=perf_counter();gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal',0);gmsh.option.setNumber('General.NumThreads',1);gmsh.model.add('RVE')
        o=gmsh.model.occ;square=o.addRectangle(0,0,0,1,1);tools=[]
        for shape in micro['shapes']:
            if shape['kind']=='polygon':
                pp=[o.addPoint(*p,0.) for p in shape['points']];lines=[o.addLine(a,b) for a,b in zip(pp,pp[1:]+pp[:1])];s=o.addPlaneSurface([o.addCurveLoop(lines)])
            else:
                x,y=shape['center'];s=o.addDisk(x,y,0,shape['a'],shape['b'])
                if shape['angle']:o.rotate([(2,s)],x,y,0,0,0,1,shape['angle'])
            tools.append((2,s))
        if tools:
            _,maps=o.fragment([(2,square)],tools);o.synchronize();alltags={t for d,t in maps[0] if d==2}
            base=3000 if cfg['kind']=='polycrystal' else 10;assignment={t:base for t in alltags}
            # Priority is explicit: shell before core, pore last, independent of CAD entity order.
            for shape,group in zip(micro['shapes'],maps[1:]):
                for d,t in group:
                    if d==2 and t in assignment:assignment[t]=shape['region']
        else:o.synchronize();alltags={square};assignment={square:10}
        for region in sorted(set(assignment.values())):
            tags=[t for t,r in assignment.items() if r==region];gmsh.model.addPhysicalGroup(2,tags,region);gmsh.model.setPhysicalName(2,region,f'REGION_{region}')
        if set(map(str,assignment.values()))!=set(micro['regions']):raise ValueError('region disappeared during CAD fragmentation')
        outer=gmsh.model.getBoundary([(2,t) for t in alltags],combined=True,oriented=False);sides={i:[] for i in [1,2,3,4]}
        for d,t in outer:
            box=np.array(gmsh.model.getBoundingBox(d,t));x=(box[:3]+box[3:])/2
            for axis,val,tag in [(0,0,1),(0,1,2),(1,0,3),(1,1,4)]:
                if abs(x[axis]-val)<1e-7 and abs(box[axis+3]-box[axis])<1e-6:sides[tag].append(t)
        pairs=[]
        for master,slave,axis in [(1,2,0),(3,4,1)]:
            if len(sides[master])!=len(sides[slave]):raise ValueError('nonperiodic boundary segmentation')
            used=set()
            for s in sides[slave]:
                sb=np.array(gmsh.model.getBoundingBox(1,s));sb[[axis,axis+3]]-=1
                hits=[t for t in sides[master] if np.max(abs(np.array(gmsh.model.getBoundingBox(1,t))-sb))<1e-6]
                if len(hits)!=1 or hits[0] in used:raise ValueError('ambiguous periodic curve match')
                used.add(hits[0]);aff=np.eye(4);aff[axis,3]=1;gmsh.model.mesh.setPeriodic(1,[s],hits,aff.ravel().tolist());pairs.append([hits[0],s,axis])
        for tag,curves in sides.items():gmsh.model.addPhysicalGroup(1,curves,tag)
        gmsh.option.setNumber('Mesh.MeshSizeMin',h);gmsh.option.setNumber('Mesh.MeshSizeMax',h);gmsh.option.setNumber('Mesh.RandomFactor',0)
        gmsh.model.mesh.generate(2)
        count=sum(len(v) for v in gmsh.model.mesh.getElements(2)[1])
        if not 0<count<=min(max_cells,90000):raise ValueError('triangle count exceeds explicit host/source budget')
        cad={str(r):sum(o.getMass(2,t) for t,rr in assignment.items() if rr==r) for r in set(assignment.values())}
        gmsh.write(str(root/'mesh_normalized.msh'));data=gmshio.model_to_mesh(gmsh.model,MPI.COMM_WORLD,0,gdim=2)
        write(root/'periodic_CAD.json',{'curve_pairs':pairs,'normalized_CAD_area_fractions':cad,'gmsh_h':h})
    except Exception as exc:
        (root/'geometry_failure.txt').write_text(str(exc),encoding='utf-8');raise
    finally:gmsh.finalize()
    m=data.mesh;m.geometry.x[:]*=micro['length_m'];labels=np.zeros(ncells(m),np.int32);labels[data.cell_tags.indices]=data.cell_tags.values
    if set(map(str,set(labels)))!=set(micro['regions']):raise ValueError('missing or unexpected region tags')
    ft=boundaries(m,micro['length_m']);L=micro['length_m']
    fractions={str(tag):integral(scalar(m,(labels==tag).astype(float),'mask')*ufl.dx)/L**2 for tag in set(labels)}
    # Signed area, quality and explicit conforming interface identity.
    xyz=m.geometry.x[m.geometry.dofmap];a=xyz[:,1,:2]-xyz[:,0,:2];b=xyz[:,2,:2]-xyz[:,0,:2];ar=abs(a[:,0]*b[:,1]-a[:,1]*b[:,0])/2
    lengths=np.sum(a*a,axis=1)+np.sum(b*b,axis=1)+np.sum((a-b)**2,axis=1);quality=4*np.sqrt(3)*ar/lengths
    if min(ar)<=0 or min(quality)<1e-5 or abs(sum(fractions.values())-1)>1e-9:raise ValueError('invalid mesh area/quality/coverage')
    rel={k:abs(fractions[k]-cad[k])/max(cad[k],1e-30) for k in cad}
    curved=any(s['kind']=='ellipse' for s in micro['shapes'])
    if max(rel.values())>(.04 if curved else 1e-8):raise ValueError('mesh phase area does not resolve CAD area')
    topo=np.sort(m.geometry.dofmap,axis=1);identity=hashlib.sha256(np.round(m.geometry.x/L,12).tobytes()+topo.tobytes()+labels.tobytes()).hexdigest()
    diagnostics={'cells':ncells(m),'seconds':perf_counter()-start,'fraction_by_region':fractions,'CAD_fraction_by_region':cad,'area_relative_errors':rel,'min_triangle_quality':float(min(quality)),'min_area_m2':float(min(ar)),'mesh_id':identity,'normalized_h':h}
    write(root/'mesh_metrics.json',diagnostics);np.savez(root/'mesh_identity.npz',coordinates_m=m.geometry.x,triangles=m.geometry.dofmap,regions=labels)
    return RVEMesh(m,labels,ft,micro,diagnostics,root)
