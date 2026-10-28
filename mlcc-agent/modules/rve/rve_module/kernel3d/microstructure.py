"""True 3D geometry descriptions and periodic convex Voronoi clipping, NumPy only."""
import itertools,json,hashlib
import numpy as np

def cube_faces():
    return [np.array(p,float) for p in [
      [[0,0,0],[0,0,1],[0,1,1],[0,1,0]],[[1,0,0],[1,1,0],[1,1,1],[1,0,1]],
      [[0,0,0],[1,0,0],[1,0,1],[0,0,1]],[[0,1,0],[0,1,1],[1,1,1],[1,1,0]],
      [[0,0,0],[0,1,0],[1,1,0],[1,0,0]],[[0,0,1],[1,0,1],[1,1,1],[0,1,1]]]]

def clip(faces,n,b):
    if not faces:return []
    allv=np.concatenate(faces);d=allv@n-b
    if d.max()<1e-10:return faces
    if d.min()>-1e-10:return []
    new=[];cap=[]
    for face in faces:
        out=[]
        for a,c in zip(face,np.roll(face,-1,axis=0)):
            da=float(a@n-b);dc=float(c@n-b);ina=da<=1e-11;inc=dc<=1e-11
            if ina:out.append(a)
            if ina!=inc:
                p=a+(c-a)*da/(da-dc);out.append(p);cap.append(p)
        clean=[]
        for p in out:
            if not clean or np.linalg.norm(p-clean[-1])>1e-9:clean.append(p)
        if len(clean)>1 and np.linalg.norm(clean[0]-clean[-1])<1e-9:clean.pop()
        if len(clean)>=3:new.append(np.array(clean))
    unique={tuple(np.round(p,9)):p for p in cap};vv=np.array(list(unique.values()))
    if len(vv)>=3:
        center=vv.mean(axis=0);axis=np.eye(3)[np.argmin(abs(n))];u=np.cross(n,axis);u/=np.linalg.norm(u);v=np.cross(n,u)
        angle=np.arctan2((vv-center)@v,(vv-center)@u);new.append(vv[np.argsort(angle)])
    return new

def volume(faces):
    if not faces:return 0.
    center=np.concatenate(faces).mean(axis=0);total=0.
    for face in faces:
        for i in range(1,len(face)-1):total+=abs(np.linalg.det(np.array([face[0]-center,face[i]-center,face[i+1]-center])))/6
    return total

class MicrostructureBuilder:
    def __init__(self,cfg):
        self.cfg=dict(cfg);self.regions={};self.shapes=[];self.stats={}
    def region(self,tag,role,grain=None,orientation=None):self.regions[str(tag)]={'tag':tag,'role':role,'grain_id':grain,'material_id':f'{role}_{grain if grain is not None else "shared"}','orientation_euler_rad':orientation}
    def add(self,faces,tag):
        if volume(faces)>1e-9:self.shapes.append({'kind':'polyhedron','faces':[f.tolist() for f in faces],'region':tag})
    def build(self):
        c=self.cfg;k=c['kind'];L=np.array(c['lengths_m'],float)
        if L.shape!=(3,) or not np.isfinite(L).all() or min(L)<=0:raise ValueError('three positive physical lengths required')
        if k=='homogeneous':self.region(10,'matrix')
        elif k=='layers':
            axis=int(c.get('axis',0));f=float(c.get('fraction',.4))
            if axis not in [0,1,2] or not 0<f<1:raise ValueError('invalid 3D layer axis/fraction')
            self.region(10,'matrix');self.region(20,'inclusion');size=np.ones(3);size[axis]=f;self.shapes.append({'kind':'box','origin':[0,0,0],'size':size.tolist(),'region':20});self.stats['analytic_inclusion_fraction']=f
        elif k in ['sphere','ellipsoid','core_shell']:
            center=np.array(c.get('center',[.5,.5,.5]),float);r=float(c.get('radius',.22));shell=float(c.get('shell',.07 if k=='core_shell' else 0.));axes=np.array(c.get('axes',[r,r,r]),float)
            if center.shape!=(3,) or axes.shape!=(3,) or not np.isfinite(np.r_[center,axes,shell]).all() or min(axes)<=0 or max(axes)+shell>=.44 or shell<0:raise ValueError('limited finite inclusion dimensions required')
            if not np.all((center>=0)&(center<=1)):raise ValueError('center must be in unit cell')
            self.region(10,'matrix');self.region(20,'core' if k=='core_shell' else 'inclusion')
            if k=='core_shell':
                if shell<=0 or max(abs(axes-axes[0]))>1e-12:raise ValueError('spherical core-shell with positive thickness required')
                self.region(30,'shell')
            rot=np.array(c.get('rotation_axis',[1,1,0]),float);angle=float(c.get('angle_rad',0.))
            if not np.isfinite(np.r_[rot,angle]).all() or np.linalg.norm(rot)==0:raise ValueError('valid rotation required')
            for shift in itertools.product([-1,0,1],repeat=3):
                point=center+shift
                # Conservative bounding sphere after arbitrary rotation.
                if np.any(point+max(axes)+shell<0) or np.any(point-max(axes)-shell>1):continue
                if k=='core_shell':self.shapes.append({'kind':'ellipsoid','center':point.tolist(),'axes':(axes+shell).tolist(),'angle':0.,'rotation_axis':rot.tolist(),'region':30})
                self.shapes.append({'kind':'ellipsoid','center':point.tolist(),'axes':axes.tolist(),'angle':angle,'rotation_axis':rot.tolist(),'region':20})
            self.stats['analytic_core_or_inclusion_fraction']=float(4*np.pi*np.prod(axes)/3)
            if k=='core_shell':self.stats['analytic_shell_fraction']=float(4*np.pi*(np.prod(axes+shell)-np.prod(axes))/3)
        elif k=='polycrystal':self.voronoi()
        elif k=='extrusion':
            # Explicit 2D polygons supplied from the immutable V0.1 fixture.
            self.regions=c['regions'];self.stats['source_2d_rve_id']=c['source_rve_id']
            for s in c['polygons']:self.shapes.append({'kind':'extruded_polygon','points':s['points'],'region':s['region']})
        else:raise ValueError('unsupported 3D microstructure')
        p=float(c.get('pore_fraction',0.))
        if not np.isfinite(p) or not 0<=p<=.05:raise ValueError('single internal sphere pore fraction <=.05')
        if p:
            radius=(3*p/(4*np.pi))**(1/3);self.region(9000,'pore');self.shapes.append({'kind':'ellipsoid','center':[.5]*3,'axes':[radius]*3,'angle':0.,'rotation_axis':[1,0,0],'region':9000});self.stats['target_pore_fraction']=p
        data={'schema':'rve.microstructure.v02','dimension':3,'lengths_m':L.tolist(),'config':c,'regions':self.regions,'shapes':self.shapes,'statistics':self.stats,'coordinate_convention':'normalized box; physical field coordinates in m'}
        data['rve_id']=hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False).encode()).hexdigest()[:20];return data
    def voronoi(self):
        c=self.cfg;N=int(c.get('grains',8));seed=int(c.get('seed',11));gb=float(c.get('gb_width',0.));shell=float(c.get('shell',0.));jitter=float(c.get('jitter',.45))
        if N not in [8,12,16,20,27] or not 0<=gb<=.12 or not 0<=shell<=.08 or not 0<=jitter<=.7:raise ValueError('bounded 8/12/16/20/27 grains and offsets required')
        rng=np.random.default_rng(seed)
        counts={8:[2,2,2],12:[3,2,2],16:[4,2,2],20:[5,2,2],27:[3,3,3]}[N];counts=np.array(counts)
        seeds=np.array([(np.array(i)+.5)/counts for i in itertools.product(*[range(n) for n in counts])]);seeds+=(rng.random((N,3))-.5)*jitter/counts
        images=[(i,s+shift) for shift in itertools.product([-1,0,1],repeat=3) for i,s in enumerate(seeds)];points=np.array([s for i,s in images]);angles=rng.uniform(0,np.pi,(N,3))
        if gb:self.region(3000,'grain_boundary')
        for i in range(N):
            self.region(100+i,'core' if shell else 'grain',i,angles[i].tolist())
            if shell:self.region(200+i,'shell',i,angles[i].tolist())
        total=np.zeros(N);corevol=np.zeros(N)
        for i,s in images:
            delta=points-s;dist=np.linalg.norm(delta,axis=1);order=np.argsort(dist);planes=[(delta[j]/dist[j],float((points[j]@points[j]-s@s)/2/dist[j])) for j in order if dist[j]>1e-10]
            def cell(offset):
                fs=cube_faces()
                for n,b in planes:
                    fs=clip(fs,n,b-offset)
                    if not fs:break
                return fs
            full=cell(0.);v=volume(full);total[i]+=v
            if v<1e-9:continue
            inner=cell(gb/2) if gb else full
            core=cell(gb/2+shell) if shell else inner;corevol[i]+=volume(core)
            if shell:self.add(inner,200+i)
            self.add(core,100+i)
        if abs(sum(total)-1)>1e-7 or min(corevol)<1e-4:raise ValueError('invalid periodic 3D Voronoi coverage/core degeneration')
        self.stats.update(seed=seed,grain_count=N,seeds_normalized=seeds.tolist(),orientation_euler_rad=angles.tolist(),grain_volume_fractions=total.tolist(),core_volume_fractions=corevol.tolist(),
          gb_definition='Each Voronoi half-space face moved inward by gb_width/2; intersections resolve triple/quadruple junctions geometrically.',mean_equivalent_sphere_diameter_normalized=float(np.mean((6*total/np.pi)**(1/3))))

def build(config):return MicrostructureBuilder(config).build()
