"""Independent NumPy simplex residuals and sensitivity verification from raw files.

No tangent/solver imports, no UFL or assembled Jacobian is reused.
"""
from pathlib import Path
import json,math,itertools,sys,xml.etree.ElementTree as ET
import numpy as np
import basix,pyvista as pv,h5py
def check(path):
    path=Path(path);cfg=json.loads((path/'config.json').read_text());z=np.load(path/'fields.npz');grid=pv.read(path/'fields.vtu');D=cfg['dimension'];p={'a':-.5,'b':.25,'c':1.5,'g':.5,'epsilon':1.,**cfg['parameters']};P=z['P'];psi=z['psi'];phi=z['phi'];x=z['coordinates'][:,:D];cells=z['cells'];N=len(x);maps=z['maps'];constrained=z['constrained'];bias=z['bias'];checks={};errors={}
    def test(name,value,limit):errors[name]=float(value);checks[name]=bool(np.isfinite(value) and value<limit)
    assert np.array_equal(P,grid.point_data['P'][:,:D]) and np.array_equal(phi,grid.point_data['phi']) and np.array_equal(cells,grid.cells.reshape(-1,D+2)[:,1:]) and np.array_equal(z['coordinates'],grid.points)
    checks['real_simplexes_and_shape']=bool(set(grid.celltypes)=={5 if D==2 else 10} and P.shape==(N,D) and len(maps)==D+1)
    facets={}
    for c in cells:
        for f in itertools.combinations(c,D):
            key=tuple(sorted(f));facets[key]=facets.get(key,0)+1
    bd=np.unique([i for f,k in facets.items() if k==1 for i in f]);Pbd=np.array([],int)
    if cfg['kind'].startswith('wall'):
        normal=np.eye(D)[1] if cfg['kind']=='wall_180' else (np.eye(D)[0]+np.eye(D)[1 if cfg['kind']=='wall_90xy' else 2])/np.sqrt(2);q=x@normal;Pbd=np.flatnonzero(np.isclose(q,min(q))|np.isclose(q,max(q)))
    expected=np.unique(np.concatenate([maps[D][bd],*[m[Pbd] for m in maps[:D]]]))
    checks['constraint_indices_match_physical_boundary']=np.array_equal(expected,np.sort(constrained));test('lifting_boundary',max(abs(phi[bd]+x[bd]@bias)),1e-10);test('psi_boundary',max(abs(psi[bd])),1e-10);test('physical_phi_reconstruction',max(abs(phi-psi+x@bias)),1e-10)
    M=np.concatenate([np.ones((len(cells),D+1,1)),x[cells]],axis=2);det=np.abs(np.linalg.det(M));vol=det/math.factorial(D);inv=np.linalg.inv(M);gradN=np.swapaxes(inv[:,1:,:],1,2);gradP=np.einsum('cai,caj->cij',gradN,P[cells]);gradpsi=np.einsum('cai,ca->ci',gradN,psi[cells]);E=bias-gradpsi;volume=vol.sum();test('volume',abs(volume-float(z['mass_volume'])),1e-10);test('E_readback',np.max(abs(E-grid.cell_data['E'][:,:D])),1e-9);test('D_constitutive_readback',np.max(abs(p['epsilon']*E+P[cells].mean(axis=1)-grid.cell_data['D'][:,:D])),1e-9)
    pts,w=basix.make_quadrature(basix.CellType.triangle if D==2 else basix.CellType.tetrahedron,6);B=np.column_stack([1-pts.sum(axis=1),pts]);PQ=np.einsum('qa,cai->cqi',B,P[cells]);force=2*p['a']*PQ+4*p['b']*PQ**3+2*p['c']*PQ*(np.sum(PQ**2,axis=-1,keepdims=True)-PQ**2)-E[:,None,:]
    def residual(force,GP,dfield,PN):
        rp=np.zeros((N,D));rq=np.zeros(N)
        for a in range(D+1):
            np.add.at(rp,cells[:,a],np.sum((det[:,None]*w*B[:,a])[...,None]*force,axis=1)+p['g']*vol[:,None]*np.einsum('cij,ci->cj',GP,gradN[:,a,:]))
            np.add.at(rq,cells[:,a],vol*np.sum(gradN[:,a,:]*(-p['epsilon']*dfield-PN[cells].mean(axis=1)),axis=1))
        return np.linalg.norm(np.delete(rp,Pbd,axis=0)),np.linalg.norm(np.delete(rq,bd))
    rp,rq=residual(force,gradP,E,P);test('independent_static_P_residual',rp,1e-9);test('independent_static_Gauss_residual',rq,1e-9)
    meanP=np.sum(vol[:,None]*P[cells].mean(axis=1),axis=0)/volume;meanE=np.sum(vol[:,None]*E,axis=0)/volume;test('actual_mean_E',max(abs(meanE-bias)),1e-10)
    if (path/'tensor.json').exists():
        result=json.loads((path/'tensor.json').read_text())
        if 'mean_polarization' in result:test('mean_P',np.max(abs(meanP-result['mean_polarization'])),1e-10);test('mean_D',np.max(abs(p['epsilon']*meanE+meanP-result['mean_displacement'])),1e-10)
    if 'sensitivities' in z:
        H=np.zeros((*PQ.shape[:2],D,D))
        for i in range(D):
            H[...,i,i]=2*p['a']+12*p['b']*PQ[...,i]**2+2*p['c']*(np.sum(PQ**2,axis=-1)-PQ[...,i]**2)
            for j in range(D):
                if j!=i:H[...,i,j]=4*p['c']*PQ[...,i]*PQ[...,j]
        tensor=np.zeros((D,D));bg=tensor.copy();pol=tensor.copy();maxrp=maxrq=0.
        for j,s in enumerate(z['sensitivities']):
            SP=np.column_stack([s[m] for m in maps[:D]]);SPQ=np.einsum('qa,cai->cqi',B,SP[cells]);GSP=np.einsum('cai,caj->cij',gradN,SP[cells]);dE=np.eye(D)[j]-np.einsum('cai,ca->ci',gradN,s[maps[D]][cells]);rP,rQ=residual(np.einsum('cqij,cqj->cqi',H,SPQ)-dE[:,None,:],GSP,dE,SP);maxrp=max(maxrp,rP);maxrq=max(maxrq,rQ)
            pol[:,j]=np.sum(vol[:,None]*SP[cells].mean(axis=1),axis=0)/volume;bg[:,j]=p['epsilon']*np.sum(vol[:,None]*dE,axis=0)/volume;tensor[:,j]=pol[:,j]+bg[:,j]
            test(f'physical_potential_sensitivity_boundary_{j}',np.max(abs(s[maps[D]][bd])),1e-10);test(f'VTU_phi_sensitivity_{j}',np.max(abs(grid.point_data[f'dphi_dE{j}']-(s[maps[D]]-x[:,j]))),1e-10);test(f'VTU_E_sensitivity_{j}',np.max(abs(grid.cell_data[f'dE_dE{j}'][:,:D]-dE)),1e-9)
        test('independent_sensitivity_P_residual',maxrp,1e-8);test('independent_sensitivity_Gauss_residual',maxrq,1e-8);test('independent_total_tensor',np.max(abs(tensor-result['total_tangent_permittivity'])),1e-8);test('independent_background_tensor',np.max(abs(bg-result['background_permittivity'])),1e-8);test('independent_polarization_tensor',np.max(abs(pol-result['polarization_tangent_contribution'])),1e-8)
    if (path/'frozen_sensitivities.npz').exists():
        frozen=np.load(path/'frozen_sensitivities.npz')['sensitivities'];test('frozen_P_sensitivity',np.max(abs(frozen[:,maps[:D]])),1e-10)
        for j,s in enumerate(frozen):
            dE=np.eye(D)[j]-np.einsum('cai,ca->ci',gradN,s[maps[D]][cells]);background=p['epsilon']*np.sum(vol[:,None]*dE,axis=0)/volume;test(f'frozen_background_{j}',np.max(abs(background-p['epsilon']*np.eye(D)[j])),1e-10)
    xml=ET.parse(path/'fields.xdmf');h5=h5py.File(path/'fields.h5');hx=h5[xml.find('.//Geometry/DataItem').text.split(':',1)[1]][:];hx=np.pad(hx,((0,0),(0,3-hx.shape[1])));lookup={tuple(np.round(v,10)):i for i,v in enumerate(grid.points)};idx=np.array([lookup[tuple(np.round(v,10))] for v in hx]);herror=0.
    for attr in xml.findall('.//Attribute'):
        name=attr.attrib['Name']
        if name in ['phi',*['P'+'xyz'[i] for i in range(D)]]:vals=h5[attr.find('DataItem').text.split(':',1)[1]][:].reshape(-1);herror=max(herror,float(np.max(abs(vals-grid.point_data[name][idx]))))
    h5.close();test('HDF5_node_correspondence',herror,1e-12)
    return {'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'errors':errors,'dimension':D}
def run(root):
    root=Path(root);rows={}
    for p in sorted(root.rglob('fields.npz')):
        try:rows[p.parent.relative_to(root).as_posix()]=check(p.parent)
        except Exception as exc:rows[p.parent.relative_to(root).as_posix()]={'status':'FAIL','error':repr(exc)}
    result={'status':'PASS' if rows and all(r['status']=='PASS' for r in rows.values()) else 'FAIL','cases':len(rows),'results':rows};(root/'readback.json').write_text(json.dumps(result,indent=2));print('Independent readback',result['status'],len(rows),flush=True)
    if result['status']!='PASS':raise RuntimeError('readback/residual failure')
    return result
if __name__=='__main__':run(sys.argv[1])
