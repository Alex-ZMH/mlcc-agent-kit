"""Independent stored-field integration, constitutive/PBC and HDF5 round-trip."""
from pathlib import Path
import json,sys
import numpy as np
import h5py,pyvista as pv
from .fem_common import write

def read(path):return json.loads(path.read_text())
def hdf5(path,g):
    with h5py.File(path) as f:
        group=f['Mesh'][next(iter(f['Mesh']))];coords=group['geometry'][()];top=group['topology'][()]
        L=max(np.ptp(coords[:,0]),np.ptp(coords[:,1]));keys={tuple(np.round(x[:2]/L,10)):i for i,x in enumerate(coords)}
        if len(keys)!=len(coords):raise ValueError('coordinate mapping ambiguous')
        perm=np.array([keys[tuple(np.round(x[:2]/L,10))] for x in g.points]);lookup={tuple(sorted(t)):i for i,t in enumerate(top)}
        cp=np.array([lookup[tuple(sorted(perm[t]))] for t in g.cells.reshape(-1,4)[:,1:]])
        if len(set(perm))!=len(perm) or len(set(cp))!=len(cp):raise ValueError('nonbijective file mapping')
        err=0.
        for name in list(g.point_data)+[s for s in g.cell_data if s!='material_tag']:
            x=g.point_data[name] if name in g.point_data else g.cell_data[name];y=f['Function'][name]['0'][()][perm if name in g.point_data else cp]
            err=max(err,float(np.max(abs(x.reshape(-1)-y.reshape(-1)))))
        return err

def check(folder,prop):
    r=read(folder/'metrics.json');g=pv.read(folder/'fields.vtu');pts=g.points[:,:2];cells=g.cells.reshape(-1,4)[:,1:];v=g.point_data;cd=g.cell_data;physics=r['physics'];L=np.ptp(pts[:,0]);G=np.array(r['load_G'])
    un='potential_V' if physics=='electrostatics' else 'temperature_deviation_K';fn='E_V_m' if physics=='electrostatics' else 'negative_grad_T_K_m';jn='D_C_m2' if physics=='electrostatics' else 'heat_flux_W_m2'
    xy=pts[cells];a=xy[:,1]-xy[:,0];b=xy[:,2]-xy[:,0];ar=abs(a[:,0]*b[:,1]-a[:,1]*b[:,0])/2
    means=ar@cd[jn][:,:2]/L**2;meanf=ar@cd[fn][:,:2]/L**2;micro=float(ar@cd['local_field_flux_work']/L**2)
    C=np.array([[cd[f'constitutive_{i}{j}'] for j in range(2)] for i in range(2)]).transpose(2,0,1)
    constit=np.einsum('cij,cj->ci',C,cd[fn][:,:2]);crel=float(np.linalg.norm(constit-cd[jn][:,:2])/max(np.linalg.norm(constit),1e-30))
    # Recompute triangle gradients from saved point values, independent of UFL.
    M=np.concatenate([np.ones((len(cells),3,1)),xy],axis=2);coeff=np.linalg.solve(M,v[un][cells][...,None])[...,0];grad=-coeff[:,1:]
    graderr=float(np.linalg.norm(grad-cd[fn][:,:2])/max(np.linalg.norm(grad),1e-30))
    energyrel=abs(micro-r['micro_work_density'])/max(abs(micro),1e-30);jerr=float(np.linalg.norm(means-r['mean_flux'])/max(np.linalg.norm(means),1e-30))
    fluct=v['periodic_fluctuation'];uerr=float(max(abs(v[un]+pts@G-fluct))/(L*np.linalg.norm(G)))
    npz=np.load(folder/'periodic_constraints.npz');savedxy=npz['coordinates_m'][:,:2]
    lookup={tuple(np.round(x/L,10)):i for i,x in enumerate(pts)};order=np.array([lookup[tuple(np.round(x/L,10))] for x in savedxy]);pairs=npz['slave_master']
    pairerr=float(max(abs(fluct[order[pairs[:,0]]]-fluct[order[pairs[:,1]]]))/(L*np.linalg.norm(G))) if len(pairs) else 0.
    # Raw face flux from actual saved cell J and geometry, with no FE integration reuse.
    edges={}
    for i,t in enumerate(cells):
        for x,y in zip(t,np.roll(t,-1)):edges.setdefault(tuple(sorted((int(x),int(y)))),[]).append(i)
    raw=np.zeros(5);boundary_pairs={}
    for (x,y),adj in edges.items():
        if len(adj)>2:raise ValueError('nonmanifold edge')
        if len(adj)!=1:continue
        a,b=pts[[x,y]];mid=(a+b)/2;normal=np.array([b[1]-a[1],a[0]-b[0]])
        centroid=pts[cells[adj[0]]].mean(axis=0)
        if normal@(mid-centroid)<0:normal=-normal
        tag=4
        for axis,val,index in [(0,0,0),(0,L,1),(1,0,2),(1,L,3)]:
            if abs(mid[axis]-val)<L*1e-8:tag=index
        raw[tag]+=normal@cd[jn][adj[0],:2]
        if tag<4:
            axis=1 if tag<2 else 0;key=(tag//2,tuple(sorted(np.round(pts[[x,y],axis]/L,9))))
            boundary_pairs.setdefault(key,[]).append((tag,adj[0],normal))
    rawerr=float(np.linalg.norm(raw-r['raw_boundary_flux'])/max(np.linalg.norm(means)*L,1e-30))
    coefficient_pair_error=0.;flux_num=0.;flux_den=0.
    for entries in boundary_pairs.values():
        if len(entries)!=2:raise ValueError('stored periodic boundary segment mismatch')
        (_,i,ni),(_,j,nj)=entries;length=np.linalg.norm(ni)
        coefficient_pair_error=max(coefficient_pair_error,float(np.linalg.norm(C[i]-C[j])/max(np.linalg.norm(C[i]),1e-30)))
        fi=ni@cd[jn][i,:2]/length;fj=nj@cd[jn][j,:2]/length
        flux_num+=(fi+fj)**2*length;flux_den+=(fi**2+fj**2)*length
    raw_point_antiperiodic=float(np.sqrt(flux_num/max(flux_den,1e-30)))
    expected=set(map(int,prop['materials']))
    if r['void_mode']=='insulating_cavity':expected.remove(9000)
    checks={'HDF5_exact':hdf5(folder/'fields.h5',g)==0.,'positive_cells':bool(min(ar)>0),'region_coverage':set(cd['material_tag'])==expected,
      'constitutive_identity':crel<1e-12,'stored_gradient':graderr<1e-9,'average_flux':jerr<1e-11,'energy_integral':energyrel<1e-11,
      'potential_lifting':uerr<1e-10,'PBC_saved_pairs':pairerr<1e-10,'independent_raw_boundary_flux':rawerr<1e-10}
    return {'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'gradient_relative_error':graderr,'constitutive_error':crel,'independent_raw_flux_error':rawerr,'PBC_saved_pair_error':pairerr,
        'raw_boundary_pointwise_flux_antiperiodicity_L2':raw_point_antiperiodic,'periodic_material_coefficient_trace_jump':coefficient_pair_error,
        'coefficient_trace_note':'A periodic cell boundary may itself be a phase interface (e.g. laminate). Opposite coefficient traces may then differ; fluctuation and normal flux, not coefficients, obey periodic/antiperiodic constraints.',
        'raw_pointwise_flux_claim':'diagnostic, not exactly H(div) conforming; no pointwise conservation PASS asserted'}

def run(root):
    rows={}
    for p in sorted(root.rglob('effective_tensor.json')):
        data=read(p)
        for name in ['x','y']:rows[str((p.parent/name).relative_to(root))]=check(p.parent/name,data)
    result={'status':'PASS' if rows and all(r['status']=='PASS' for r in rows.values()) else 'FAIL','load_field_count':len(rows),'loads':rows}
    write(root/'readback.json',result);print('readback',result['status'],len(rows),flush=True)
    if result['status']!='PASS':raise RuntimeError('stored-field verification failed')
if __name__=='__main__':run(Path(sys.argv[1]))
