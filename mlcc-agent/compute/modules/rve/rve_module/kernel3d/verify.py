"""Independent 3D VTU/HDF5, tetrahedral gradients, flux and PBC readback."""
from pathlib import Path
import json,sys,itertools
import numpy as np
import h5py,pyvista as pv
from .fem_common import write

def read(p):return json.loads(p.read_text())
def check(folder,prop):
    r=read(folder/'metrics.json');g=pv.read(folder/'fields.vtu');xyz=g.points;cells=g.cells.reshape(-1,5)[:,1:];L=np.ptp(xyz,axis=0);volbox=float(np.prod(L));pts=xyz[cells];vol=abs(np.linalg.det(pts[:,1:]-pts[:,0,None,:]))/6
    p=r['physics'];un='potential_V' if p=='electrostatics' else 'temperature_deviation_K';fn='E_V_m' if p=='electrostatics' else 'negative_grad_T_K_m';jn='D_C_m2' if p=='electrostatics' else 'heat_flux_W_m2';v=g.point_data;cd=g.cell_data
    C=np.array([[cd[f'constitutive_{i}{j}'] for j in range(3)] for i in range(3)]).transpose(2,0,1);J=cd[jn];E=cd[fn]
    M=np.concatenate([np.ones((len(cells),4,1)),pts],axis=2);gradient=-np.linalg.solve(M,v[un][cells][...,None])[...,0][:,1:];graderr=float(np.linalg.norm(gradient-E)/max(np.linalg.norm(E),1e-30));constit=np.einsum('cij,cj->ci',C,E);cerr=float(np.linalg.norm(constit-J)/max(np.linalg.norm(J),1e-30))
    mean=vol@J/volbox;work=float(vol@np.sum(E*J,axis=1)/volbox);jerr=float(np.linalg.norm(mean-r['mean_flux'])/max(np.linalg.norm(mean),1e-30));werr=abs(work-r['micro_work_density'])/max(abs(work),1e-30)
    G=np.array(r['load_G']);lift=float(max(abs(v[un]+xyz@G-v['periodic_fluctuation']))/(max(L)*np.linalg.norm(G)))
    mapping={tuple(np.round(x/L,10)):i for i,x in enumerate(xyz)};npz=np.load(folder/'periodic_constraints.npz');order=np.array([mapping[tuple(np.round(x/L,10))] for x in npz['coordinates_m']]);pairs=npz['slave_master'];fluct=v['periodic_fluctuation'];perr=float(max(abs(fluct[order[pairs[:,0]]]-fluct[order[pairs[:,1]]]))/(max(L)*np.linalg.norm(G))) if len(pairs) else 0.
    with h5py.File(folder/'fields.h5') as f:
        mg=f['Mesh'][next(iter(f['Mesh']))];coords=mg['geometry'][()];top=mg['topology'][()];byxyz={tuple(np.round(x/L,10)):i for i,x in enumerate(coords)};perm=np.array([byxyz[tuple(np.round(x/L,10))] for x in xyz]);bycell={tuple(sorted(t)):i for i,t in enumerate(top)};cp=np.array([bycell[tuple(sorted(perm[t]))] for t in cells]);diff=0.
        if len(set(perm))!=len(perm) or len(set(cp))!=len(cp):raise ValueError('nonbijective HDF5 geometry')
        for name in list(v)+[k for k in cd if k!='material_tag']:
            arr=v[name] if name in v else cd[name];raw=f['Function'][name]['0'][()][perm if name in v else cp];diff=max(diff,float(max(abs(arr.reshape(-1)-raw.reshape(-1)))))
    faces={}
    for i,t in enumerate(cells):
        for face in itertools.combinations(t,3):faces.setdefault(tuple(sorted(map(int,face))),[]).append(i)
    raw=np.zeros(7)
    for nodes,adj in faces.items():
        if len(adj)>2:raise ValueError('nonmanifold volume mesh')
        if len(adj)!=1:continue
        triangle=xyz[list(nodes)];mid=triangle.mean(axis=0);normal=np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0])/2;centroid=pts[adj[0]].mean(axis=0)
        if normal@(mid-centroid)<0:normal=-normal
        tag=6
        for axis in range(3):
            if abs(mid[axis])<L[axis]*1e-8:tag=2*axis
            if abs(mid[axis]-L[axis])<L[axis]*1e-8:tag=2*axis+1
        raw[tag]+=normal@J[adj[0]]
    rawerr=float(np.linalg.norm(raw-r['raw_boundary_flux'])/max(np.linalg.norm(mean)*max(L)**2,1e-30))
    expected=set(map(int,prop['materials']))
    if r['void_mode']=='insulating_cavity':expected.remove(9000)
    checks={'true_tetrahedra':set(g.celltypes)=={10} and cells.shape[1]==4,'positive_volume':bool(min(vol)>0),'material_coverage':set(cd['material_tag'])==expected,'HDF5_exact':diff==0.,'independent_gradient':graderr<1e-9,'constitutive':cerr<1e-12,'mean_flux':jerr<1e-10,'work':werr<1e-10,'lifting':lift<1e-10,'PBC_field_pairs':perr<1e-10,'independent_raw_flux':rawerr<1e-9}
    return {'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'gradient_relative_error':graderr,'raw_flux_reconstruction_error':rawerr,'PBC_error':perr,'HDF5_difference':diff}

def run(root):
    rows={}
    for path in sorted(root.rglob('effective_tensor.json')):
        if '/regression2d/' in str(path).replace('\\','/'):continue
        data=read(path)
        if data['dimension']!=3:continue
        for load in ['x','y','z']:rows[str((path.parent/load).relative_to(root))]=check(path.parent/load,data)
    data={'status':'PASS' if rows and all(r['status']=='PASS' for r in rows.values()) else 'FAIL','load_count':len(rows),'loads':rows};write(root/'readback.json',data);print(data['status'],len(rows),flush=True)
    if data['status']!='PASS':raise RuntimeError('3D field readback failed')
if __name__=='__main__':run(Path(sys.argv[1]))
