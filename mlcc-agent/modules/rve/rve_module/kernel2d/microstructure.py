"""Pure NumPy periodic Voronoi/convex offsets; explicit stable region identities."""
import hashlib,json
import numpy as np

def area(p):
    p=np.asarray(p);return abs(float(np.sum(p[:,0]*np.roll(p[:,1],-1)-p[:,1]*np.roll(p[:,0],-1))))/2 if len(p)>2 else 0.

def clip(poly,n,b):
    out=[]
    if len(poly)<3:return np.empty((0,2))
    for a,c in zip(poly,np.roll(poly,-1,axis=0)):
        da=float(a@n-b);dc=float(c@n-b);ina=da<=2e-13;inc=dc<=2e-13
        if ina:out.append(a)
        if ina!=inc:out.append(a+(c-a)*da/(da-dc))
    clean=[]
    for x in out:
        if not clean or np.linalg.norm(x-clean[-1])>1e-10:clean.append(x)
    if len(clean)>1 and np.linalg.norm(clean[0]-clean[-1])<1e-10:clean.pop()
    return np.array(clean).reshape(-1,2)

BOX=np.array([[0.,0.],[1.,0.],[1.,1.],[0.,1.]])

class MicrostructureBuilder:
    def __init__(self,config):
        self.config=dict(config);self.kind=config['kind'];self.L=float(config['length_m'])
        if not np.isfinite(self.L) or self.L<=0:raise ValueError('positive length required')
        self.regions={};self.shapes=[];self.stats={}
    def region(self,tag,role,grain=None,orientation=None):
        self.regions[str(tag)]={'tag':tag,'role':role,'grain_id':grain,'orientation_rad':orientation,'material_id':f'{role}_{grain if grain is not None else "shared"}'}
    def polygon(self,p,tag):
        if area(p)>1e-10:self.shapes.append({'kind':'polygon','points':np.asarray(p).tolist(),'region':tag})
    def build(self):
        cfg=self.config;k=self.kind
        if k=='homogeneous':self.region(10,'matrix')
        elif k=='layers':
            f=float(cfg.get('fraction',.4));axis=int(cfg.get('axis',0))
            if not 0<f<1 or axis not in [0,1]:raise ValueError('invalid layer fraction/axis')
            self.region(10,'matrix');self.region(20,'inclusion')
            p=BOX.copy();p[:,axis]*=f;self.polygon(p,20);self.stats['analytic_fraction']=f
        elif k=='rotated_layers':
            f=float(cfg.get('fraction',.4))
            if not 0<f<1:raise ValueError('invalid layer fraction')
            self.region(10,'matrix');self.region(20,'inclusion')
            for shift in [0,1]:
                p=clip(BOX.copy(),np.array([-1.,-1.]),-shift)
                p=clip(p,np.array([1.,1.]),shift+f);self.polygon(p,20)
            self.stats.update(analytic_fraction=f,layer_normal=[float(1/np.sqrt(2)),float(1/np.sqrt(2))])
        elif k in ['circle','ellipse','core_shell']:
            r=float(cfg.get('radius',.2));shell=float(cfg.get('shell',.05 if k=='core_shell' else 0.))
            if not 0<r<.4 or shell<0 or r+shell>=.45:raise ValueError('inclusion/core-shell must fit interior')
            self.region(10,'matrix');self.region(20,'core' if k=='core_shell' else 'inclusion')
            if k=='core_shell':
                if shell<=0:raise ValueError('positive shell required')
                self.region(30,'shell');self.shapes.append({'kind':'ellipse','a':r+shell,'b':r+shell,'angle':0.,'center':[.5,.5],'region':30})
            aspect=float(cfg.get('aspect',.5)) if k=='ellipse' else 1.
            if not .25<=aspect<=1:raise ValueError('ellipse aspect limited to .25..1')
            self.shapes.append({'kind':'ellipse','a':r,'b':r*aspect,'angle':float(cfg.get('angle_rad',0.)),'center':[.5,.5],'region':20})
            self.stats['analytic_inclusion_fraction']=float(np.pi*r*r*aspect)
        elif k=='polycrystal':self.voronoi()
        else:raise ValueError('unknown microstructure')
        pore=float(cfg.get('pore_fraction',0.))
        if not np.isfinite(pore) or not 0<=pore<=.08:raise ValueError('single interior pore fraction limited to 0..0.08')
        if pore:
            self.region(9000,'pore');self.shapes.append({'kind':'ellipse','a':float(np.sqrt(pore/np.pi)),'b':float(np.sqrt(pore/np.pi)),'angle':0.,'center':[.5,.5],'region':9000})
            self.stats['target_pore_fraction']=pore
        data={'schema':'rve.microstructure.v1','dimension':2,'coordinate_convention':'shape coordinates normalized by physical length_m','length_m':self.L,'config':cfg,'regions':self.regions,'shapes':self.shapes,'statistics':self.stats,'periodic_material_geometry':True}
        data['rve_id']=hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False).encode()).hexdigest()[:20]
        return data
    def voronoi(self):
        c=self.config;N=int(c.get('grains',9));seed=int(c.get('seed',11));gb=float(c.get('gb_width',.025));shell=float(c.get('shell',.025));jitter=float(c.get('jitter',.7))
        if not 4<=N<=36 or int(np.sqrt(N))**2!=N:raise ValueError('grain count must be a square: 4,9,16,25,36')
        if not .01<=gb<=.08 or not 0<=shell<=.08 or not 0<=jitter<=.85:raise ValueError('limited resolved gb/shell/jitter required')
        rng=np.random.default_rng(seed);n=int(np.sqrt(N));seeds=np.array([[(i+.5)/n,(j+.5)/n] for j in range(n) for i in range(n)])+(rng.random((N,2))-.5)*jitter/n
        angles=rng.uniform(0,np.pi,N);images=[(i,p+np.array([x,y])) for x in [-1,0,1] for y in [-1,0,1] for i,p in enumerate(seeds)]
        self.region(3000,'grain_boundary');totals=np.zeros(N);coreareas=np.zeros(N)
        for i in range(N):
            self.region(100+i,'core',i,float(angles[i]))
            if shell:self.region(200+i,'shell',i,float(angles[i]))
        for i,s in images:
            constraints=[]
            for j,t in images:
                d=t-s;norm=np.linalg.norm(d)
                if norm<1e-12:continue
                constraints.append((d/norm,(float(t@t-s@s)/2)/norm))
            def cell(offset):
                poly=BOX.copy()
                for n,b in constraints:
                    poly=clip(poly,n,b-offset)
                    if len(poly)<3:break
                return poly
            full=cell(0.);totals[i]+=area(full)
            if area(full)<1e-10:continue
            inner=cell(gb/2);core=cell(gb/2+shell);coreareas[i]+=area(core)
            if shell:self.polygon(inner,200+i)
            self.polygon(core,100+i)
        if abs(sum(totals)-1)>1e-9 or min(coreareas)<.001:raise ValueError('Voronoi coverage or eroded grain core invalid')
        self.stats.update(seed=seed,seeds_normalized=seeds.tolist(),orientation_rad=angles.tolist(),grain_areas_fraction=totals.tolist(),
            grain_core_areas_fraction=coreareas.tolist(),grain_count=N,mean_equivalent_diameter_m=float(2*self.L*np.mean(np.sqrt(totals/np.pi))),
            equivalent_diameter_CV=float(np.std(np.sqrt(totals))/np.mean(np.sqrt(totals))),
            gb_definition='Each Voronoi face offset inward by gb_width/2 on both grains; gap has nominal full width gb_width*length_m. Triple junctions are offset intersections.',
            shell_definition='Further inward offset by shell*length_m from grain interior to core; not a color label.')

def build(config):return MicrostructureBuilder(config).build()
