"""V0.1 RVEMesh design extended to true OCC volumes and periodic tetrahedra."""
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
import itertools,hashlib
import numpy as np
import gmsh,ufl
from dolfinx import mesh
from dolfinx.io import gmsh as gmshio
from mpi4py import MPI
from .fem_common import write,ncells,scalar,integral

@dataclass
class RVEMesh:
    mesh:object
    labels:np.ndarray
    facets:object
    micro:dict
    diagnostics:dict
    root:Path

def boundaries(m,L):
    D=m.geometry.dim;L=np.broadcast_to(L,(D,));m.topology.create_connectivity(D-1,D);ext=mesh.exterior_facet_indices(m.topology);xy=mesh.compute_midpoints(m,D-1,ext)
    val=np.full(len(ext),2*D+1,np.int32)
    for i in range(D):
        val[abs(xy[:,i])<L[i]*1e-8]=2*i+1;val[abs(xy[:,i]-L[i])<L[i]*1e-8]=2*i+2
    return mesh.meshtags(m,D-1,ext,val)

def polygon(o,points):
    p=[o.addPoint(*v) for v in points];e=[o.addLine(a,b) for a,b in zip(p,p[1:]+p[:1])];return o.addPlaneSurface([o.addCurveLoop(e)])

def polyhedron(o,faces):
    pp={};edges={};surfaces=[]
    def point(x):
        key=tuple(np.round(x,9))
        if key not in pp:pp[key]=o.addPoint(*x)
        return pp[key]
    for face in faces:
        ids=[point(x) for x in face];lines=[]
        for a,b in zip(ids,ids[1:]+ids[:1]):
            key=tuple(sorted((a,b)))
            if a==b:continue
            if key not in edges:edges[key]=o.addLine(*key)
            lines.append(edges[key] if a<b else -edges[key])
        if len(lines)>=3:surfaces.append(o.addPlaneSurface([o.addCurveLoop(lines)]))
    return o.addVolume([o.addSurfaceLoop(surfaces)])

def periodic_facet_audit(m,ft,L):
    # Physical 3D triangle correspondence independently after Gmsh import.
    result={};L=np.array(L)
    for axis in range(3):
        groups=[]
        for tag in [2*axis+1,2*axis+2]:
            facets=ft.find(tag);geo=mesh.entities_to_geometry(m,2,facets,False);xyz=m.geometry.x[geo]/L
            triangles={tuple(sorted(tuple(np.round(np.delete(p,axis),9)) for p in t)) for t in xyz};groups.append(triangles)
        if groups[0]!=groups[1]:raise ValueError('imported opposite face triangle topology mismatch')
        result['xyz'[axis]]={'triangle_count_each':len(groups[0]),'triangle_bijection':True}
    return result

def create(micro,h,root,max_cells=180000):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);write(root/'microstructure.json',micro)
    if not np.isfinite(h) or not .025<=h<=.4:raise ValueError('normalized target h limited .025..0.4')
    c=micro['config'];thin=min([c[k] for k in ['shell','gb_width'] if c.get(k,0)>0],default=1.)
    if h>thin/1.2:raise ValueError('shell/GB target resolution needs >=1.2 elements per nominal width; refine convergence separately')
    start=perf_counter();gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal',0);gmsh.option.setNumber('General.NumThreads',1);gmsh.model.add('RVE3D');o=gmsh.model.occ;box=o.addBox(0,0,0,1,1,1);tools=[]
        for s in micro['shapes']:
            k=s['kind']
            if k=='box':v=o.addBox(*s['origin'],*s['size'])
            elif k=='ellipsoid':
                if max(s['axes'])-min(s['axes'])<1e-12:v=o.addSphere(*s['center'],s['axes'][0])
                else:
                    v=o.addSphere(*s['center'],1.);o.dilate([(3,v)],*s['center'],*s['axes'])
                if s['angle']:o.rotate([(3,v)],*s['center'],*s['rotation_axis'],s['angle'])
            elif k=='polyhedron':v=polyhedron(o,s['faces'])
            elif k=='extruded_polygon':
                face=polygon(o,[list(p)+[0.] for p in s['points']]);entities=o.extrude([(2,face)],0,0,1);v=next(t for d,t in entities if d==3)
            else:raise ValueError('unsupported shape')
            tools.append((3,v))
        if tools:
            _,maps=o.fragment([(3,box)],tools);o.synchronize();allvol={t for d,t in maps[0] if d==3};assignment={t:3000 if '3000' in micro['regions'] else 10 for t in allvol}
            for shape,group in zip(micro['shapes'],maps[1:]):
                for d,t in group:
                    if d==3 and t in assignment:assignment[t]=shape['region']
            outside=[(3,t) for d,t in o.getEntities(3) if t not in allvol]
            if outside:o.remove(outside,recursive=True);o.synchronize()
        else:o.synchronize();allvol={box};assignment={box:10}
        repairs=[]
        if c['kind']=='polycrystal' and 10 in assignment.values():
            seeds=np.array(micro['statistics']['seeds_normalized'])
            for v,tag in list(assignment.items()):
                if tag!=10:continue
                mass=o.getMass(3,v)
                if mass>1e-8:raise ValueError('nontrivial gap in Voronoi partition')
                center=np.array(o.getCenterOfMass(3,v));delta=abs(seeds-center);delta=np.minimum(delta,1-delta);i=int(np.argmin(np.sum(delta**2,axis=1)))
                assignment[v]=100+i;repairs.append({'volume':v,'normalized_volume':mass,'nearest_periodic_grain':i})
            # Fuse numeric CAD slivers to their nearest physical grain, removing
            # only within-grain boundaries; retain an explicit repair record.
            new={}
            for tag in sorted(set(assignment.values())):
                group=[(3,v) for v,r in assignment.items() if r==tag]
                entities=o.fuse(group[:1],group[1:])[0] if len(group)>1 else group
                for d,v in entities:
                    if d==3:new[v]=tag
            assignment=new;allvol=set(new);o.synchronize()
        write(root/'CAD_assignment_audit.json',{'expected':list(micro['regions']),'assigned':sorted(set(assignment.values())),'numeric_sliver_repairs':repairs,'volumes_by_tag':{str(tag):sum(o.getMass(3,v) for v,r in assignment.items() if r==tag) for tag in set(assignment.values())}})
        if set(map(str,assignment.values()))!=set(micro['regions']):raise ValueError('lost/unexpected 3D material region')
        for tag in sorted(set(assignment.values())):
            gmsh.model.addPhysicalGroup(3,[v for v,r in assignment.items() if r==tag],tag);gmsh.model.setPhysicalName(3,tag,f'REGION_{tag}')
        outer=gmsh.model.getBoundary([(3,v) for v in allvol],combined=True,oriented=False);sides={i:[] for i in range(1,7)}
        for d,t in outer:
            bb=np.array(gmsh.model.getBoundingBox(d,t));mid=(bb[:3]+bb[3:])/2
            for axis in range(3):
                for v in [0,1]:
                    if abs(mid[axis]-v)<1e-7 and abs(bb[axis+3]-bb[axis])<1e-6:sides[2*axis+v+1].append(t)
        write(root/'CAD_face_partition.json',sides);pairs=[]
        for axis in range(3):
            master,slave=sides[2*axis+1],sides[2*axis+2]
            if not master or len(master)!=len(slave):raise ValueError('opposite 3D CAD surface partition mismatch')
            used=set()
            for s in slave:
                bb=np.array(gmsh.model.getBoundingBox(2,s));bb[[axis,axis+3]]-=1
                hits=[t for t in master if np.max(abs(np.array(gmsh.model.getBoundingBox(2,t))-bb))<1e-6 and abs(o.getMass(2,s)-o.getMass(2,t))<1e-7]
                if len(hits)!=1 or hits[0] in used:raise ValueError('ambiguous 3D periodic face match')
                used.add(hits[0]);aff=np.eye(4);aff[axis,3]=1;gmsh.model.mesh.setPeriodic(2,[s],hits,aff.ravel().tolist());pairs.append([hits[0],s,axis])
        for tag,surf in sides.items():gmsh.model.addPhysicalGroup(2,surf,tag)
        gmsh.option.setNumber('Mesh.MeshSizeMin',h);gmsh.option.setNumber('Mesh.MeshSizeMax',h);gmsh.option.setNumber('Mesh.RandomFactor',1e-9);gmsh.option.setNumber('Mesh.RandomSeed',42);gmsh.model.mesh.generate(3)
        count=sum(len(v) for v in gmsh.model.mesh.getElements(3)[1])
        if not 0<count<=min(max_cells,180000):raise ValueError('tetrahedron count exceeds explicit host/source budget')
        cad={str(tag):sum(o.getMass(3,v) for v,r in assignment.items() if r==tag) for tag in set(assignment.values())}
        gmsh.write(str(root/'mesh_normalized.msh'));data=gmshio.model_to_mesh(gmsh.model,MPI.COMM_WORLD,0,gdim=3)
        write(root/'periodic_CAD.json',{'surface_pairs':pairs,'CAD_volume_fractions':cad,'h_normalized':h})
    except Exception as e:
        (root/'geometry_failure.txt').write_text(str(e));raise
    finally:gmsh.finalize()
    m=data.mesh;L=np.array(micro['lengths_m']);m.geometry.x[:]*=L;labels=np.zeros(ncells(m),np.int32);labels[data.cell_tags.indices]=data.cell_tags.values;ft=boundaries(m,L)
    if set(map(str,set(labels)))!=set(micro['regions']):raise ValueError('imported region coverage mismatch')
    fractions={str(t):integral(scalar(m,(labels==t).astype(float),'mask')*ufl.dx)/np.prod(L) for t in set(labels)}
    cells=m.geometry.dofmaps[0];xyz=m.geometry.x[cells];V=abs(np.linalg.det(xyz[:,1:]-xyz[:,0,None,:]))/6;edges=sum(np.sum((xyz[:,i]-xyz[:,j])**2,axis=1) for i,j in itertools.combinations(range(4),2));quality=12*(3*V)**(2/3)/edges
    errors={k:abs(fractions[k]/cad[k]-1) for k in cad};curved=any(s['kind']=='ellipsoid' for s in micro['shapes'])
    write(root/'preliminary_volume_audit.json',{'fraction_by_region':fractions,'CAD_fraction_by_region':cad,'volume_relative_errors':errors,'min_quality':float(min(quality)),'min_volume':float(min(V)),'cells':ncells(m)})
    if min(V)<=0 or min(quality)<1e-5 or abs(sum(fractions.values())-1)>1e-8 or max(errors.values())>(.12 if curved else 1e-7):raise ValueError('tetrahedra/coverage/CAD volume audit failed')
    faceaudit=periodic_facet_audit(m,ft,L);identity=hashlib.sha256(np.round(m.geometry.x/L,11).tobytes()+cells.tobytes()+labels.tobytes()).hexdigest()
    diag={'cells':ncells(m),'dimension':m.topology.dim,'cell_vertices':cells.shape[1],'seconds':perf_counter()-start,'fraction_by_region':fractions,'CAD_fraction_by_region':cad,'volume_relative_errors':errors,'min_volume_m3':float(min(V)),'min_tet_quality':float(min(quality)),'periodic_faces':faceaudit,'mesh_id':identity,'normalized_h':h}
    write(root/'mesh_metrics.json',diag);np.savez(root/'mesh_identity.npz',coordinates_m=m.geometry.x,tetrahedra=cells,regions=labels)
    return RVEMesh(m,labels,ft,micro,diag,root)
