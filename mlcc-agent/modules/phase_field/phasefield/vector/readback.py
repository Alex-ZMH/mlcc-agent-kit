"""Independent saved simplex/shape-function/constitutive/energy residual checks."""
from pathlib import Path
import json,sys,math,xml.etree.ElementTree as ET
import numpy as np
import pyvista as pv
import h5py,basix
from .kernel import write
def read(p):return json.loads(p.read_text())
def check(path):
    path=Path(path);cfg=read(path/'config.json');hist=read(path/'history.json');logs=read(path/'nonlinear.json');metric=read(path/'metrics.json');z=np.load(path/'fields.npz');grid=pv.read(path/'fields.vtu');D=cfg['dimension'];p=cfg['parameters'];x=grid.points[:,:D];cells=grid.cells.reshape(-1,D+2)[:,1:];P=grid.point_data['P'][:,:D];phi=grid.point_data['phi'];N=len(x)
    assert np.array_equal(P,z['P']) and np.array_equal(phi,z['phi']) and np.array_equal(cells,z['cells']) and np.allclose(grid.points,z['coordinates'],atol=1e-14)
    assert z['P_history'].shape==(len(hist),N,D) and z['phi_history'].shape==(len(hist),N) and np.array_equal(z['P_history'][-1],P) and np.array_equal(z['phi_history'][-1],phi) and np.all(np.diff(z['times'])>=0)
    assert np.isfinite(P).all() and np.isfinite(phi).all() and set(grid.celltypes)=={5 if D==2 else 10}
    M=np.concatenate([np.ones((len(cells),D+1,1)),x[cells]],axis=2);det=np.abs(np.linalg.det(M));vol=det/math.factorial(D);inv=np.linalg.inv(M);gradN=np.swapaxes(inv[:,1:,:],1,2);cp=np.einsum('cij,cjd->cid',inv,P[cells]);gradP=cp[:,1:,:];cf=np.einsum('cij,cj->ci',inv,phi[cells]);E=-cf[:,1:];charge=-np.trace(gradP,axis1=1,axis2=2)
    assert np.min(vol)>0
    errors={};checks={}
    def test(name,err,limit):errors[name]=float(err);checks[name]=bool(err<limit)
    test('E_from_gradient',np.max(abs(E-grid.cell_data['E'][:,:D])),1e-9);test('rho_from_vector_divergence',np.max(abs(charge-grid.cell_data['rho_bound'])),1e-9);test('D_constitutive',np.max(abs(p['epsilon']*E+P[cells].mean(axis=1)-grid.cell_data['D_cell_mean'][:,:D])),1e-8)
    quad,weights=basix.make_quadrature(basix.CellType.triangle if D==2 else basix.CellType.tetrahedron,6);B=np.column_stack([1-quad.sum(axis=1),quad]);PQ=np.einsum('qn,cnd->cqd',B,P[cells]);QX=np.einsum('qn,cnd->cqd',B,x[cells]);sq=np.sum(PQ*PQ,axis=-1);bulk=p['a']*sq+p['b']*np.sum(PQ**4,axis=-1)+p['c']*sum(PQ[...,i]**2*PQ[...,j]**2 for i in range(D) for j in range(i));Fbulk=float(np.sum(det[:,None]*weights*bulk));Fgrad=float(np.sum(vol*p['g']/2*np.sum(gradP**2,axis=(1,2))));Felec=float(np.sum(vol*(-p['epsilon']/2*np.sum(E*E,axis=1)-np.sum(P[cells].mean(axis=1)*E,axis=1))));volume=sum(vol)
    test('volume',abs(volume-np.prod(np.array(cfg['geometry_hi'])-cfg['geometry_lo']))/volume,1e-10)
    test('independent_enthalpy',abs(Fbulk+Fgrad+Felec-hist[-1]['enthalpy'])/max(1,abs(hist[-1]['enthalpy'])),1e-9)
    # Independent continuous MMS forcing (NumPy derivatives, not UFL residual reuse).
    def grad_bulk(A):return 2*p['a']*A+4*p['b']*A**3+2*p['c']*A*(np.sum(A*A,axis=-1,keepdims=True)-A*A)
    rho=np.zeros(PQ.shape[:2]);source=np.zeros_like(PQ);t=hist[-1]['t'];decay=np.exp(-t)
    if cfg['mms']:
        offset=np.array([.2+.03*i for i in range(D)])
        if cfg['mms']=='affine':
            blob=np.stack([.04*np.sum(QX*np.array([j+i+1 for j in range(D)]),axis=-1)/D*decay for i in range(D)],axis=-1);exact=offset+blob;gp=np.tile(.04*decay*np.array([(-1)**j for j in range(D)]),(*PQ.shape[:2],1));rho[:]=.04*D*decay;lap=np.zeros_like(blob)
        else:
            ks=np.pi*(np.ones((D,D))+np.eye(D));theta=np.einsum('cqd,id->cqi',QX,ks);blob=.08*np.sin(theta)*decay;exact=offset+blob;gp=np.repeat((.07*np.pi*np.cos(np.pi*np.sum(QX,axis=-1))*decay)[...,None],D,axis=-1);lap=-blob*np.sum(ks*ks,axis=1);rho=.07*D*np.pi**2*np.sin(np.pi*np.sum(QX,axis=-1))*decay+.16*np.pi*decay*np.sum(np.cos(theta),axis=-1)
        source=-blob/p['mobility']+grad_bulk(exact)-p['g']*lap+gp
    rq=np.zeros(N);rp=np.zeros((N,D));flux=p['epsilon']*(-E)-P[cells].mean(axis=1)
    for a in range(D+1):np.add.at(rq,cells[:,a],vol*np.sum(gradN[:,a,:]*flux,axis=1)-np.sum(det[:,None]*weights*B[:,a]*rho,axis=1))
    accepted=[r for r in logs if r['accepted']];last=accepted[-1] if accepted else None;steady=bool(last and last.get('steady'))
    if last and not steady:
        oldP=z['P_history'][-2];oldQ=np.einsum('qn,cnd->cqd',B,oldP[cells]);mass=(PQ-oldQ)/(p['mobility']*last['dt'])
    else:mass=np.zeros_like(PQ)
    force=mass+grad_bulk(PQ)-E[:,None,:]-source
    for a in range(D+1):np.add.at(rp,cells[:,a],np.sum((det[:,None]*weights*B[:,a])[...,None]*force,axis=1)+p['g']*vol[:,None]*np.einsum('csd,cs->cd',gradP,gradN[:,a,:]))
    qcoords=x@np.array(cfg['frame']);bd=np.any(np.isclose(qcoords,cfg['geometry_lo'])|np.isclose(qcoords,cfg['geometry_hi']),axis=1);freeP=~(bd if cfg['mms'] else np.isclose(qcoords[:,0],cfg['geometry_lo'][0])|np.isclose(qcoords[:,0],cfg['geometry_hi'][0]) if cfg['kind'].startswith('wall') else np.zeros(N,bool))
    test('independent_Gauss_residual',np.linalg.norm(rq[~bd]),1e-8)
    if last:test('independent_TDGL_residual',np.linalg.norm(rp[freeP]),1e-8)
    # Reopen HDF5 via actual XDMF references and compare nodal fields by coordinates.
    xml=ET.parse(path/'fields.xdmf');h5=h5py.File(path/'fields.h5','r');geometry=xml.find('.//Geometry/DataItem').text.split(':',1)[1];hx=h5[geometry][:];hx=np.pad(hx,((0,0),(0,3-hx.shape[1])));lookup={tuple(np.round(v,11)):i for i,v in enumerate(grid.points)};index=np.array([lookup[tuple(np.round(v,11))] for v in hx]);hdferror=0.
    for attr in xml.findall('.//Attribute'):
        name=attr.attrib['Name']
        if name not in ['phi',*['P'+'xyz'[i] for i in range(D)]]:continue
        values=h5[attr.find('DataItem').text.split(':',1)[1]][:].reshape(-1);hdferror=max(hdferror,float(max(abs(values-grid.point_data[name][index]))))
    h5.close();test('HDF5_nodal_readback',hdferror,1e-12)
    checks['state_shapes_and_real_simplexes']=True
    return {'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'errors':errors,'dimension':D,'z_derivative_Pz_rms':float(np.sqrt(np.sum(vol*gradP[:,2,2]**2)/volume)) if D==3 else None,'note':'independent P1 shape-function gradients, numpy quadrature and residuals; raw CG1/DG0 flux is not H(div)-conservative'}
def run(root):
    root=Path(root);rows={}
    for p in sorted(root.rglob('fields.npz')):
        if 'legacy' in str(p):continue
        try:rows[str(p.parent.relative_to(root))]=check(p.parent)
        except Exception as exc:rows[str(p.parent.relative_to(root))]={'status':'FAIL','error':repr(exc)}
    result={'status':'PASS' if rows and all(r['status']=='PASS' for r in rows.values()) else 'FAIL','cases':len(rows),'results':rows};write(root/'readback.json',result);print('readback',result['status'],len(rows),flush=True)
    if result['status']!='PASS':raise RuntimeError('independent field/residual verification failed')
    return result
if __name__=='__main__':run(Path(sys.argv[1]))
