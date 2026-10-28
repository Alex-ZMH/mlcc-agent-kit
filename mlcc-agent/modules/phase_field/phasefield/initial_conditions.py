"""Reproducible scalar P initial data; no change to model physics."""
import numpy as np

def initial_condition(config):
    kind=config['kind']
    if kind=='uniform':
        return lambda x:np.full(x.shape[1],config['value'])
    if kind=='wall':
        return lambda x:np.tanh((x[0]-config.get('center',0))/config.get('width',1.))
    if kind=='random':
        # Same finite cosine expansion at every resolution, exact Neumann compatibility.
        seed=config['seed']; amplitude=config.get('amplitude',.05); reference=config.get('reference',0.)
        dimension=config.get('dimension',2);modes=config.get('modes',4)
        rng=np.random.default_rng(seed); coefficients=rng.normal(size=(modes,)*dimension)
        coefficients/=np.sum(np.abs(coefficients))
        def evaluate(x):
            result=np.full(x.shape[1],reference)
            for indices in np.ndindex(coefficients.shape):
                i,j=indices[:2]
                term=amplitude*coefficients[indices]*np.cos(i*np.pi*(x[0]+8)/16)*np.cos(j*np.pi*x[1]/4)
                if dimension==3:term*=np.cos(indices[2]*np.pi*(x[2]+2)/4)
                result+=term
            return result
        return evaluate
    if kind=='nucleus':
        # A smooth, cosine-warped ellipse: locally elliptical, dP/dn=0 exactly on walls.
        cx,cy=config.get('center',[0.,2.]); rx,ry=config.get('radii',[2.8,1.1])
        def evaluate(x):
            kx,ky=np.pi/16,np.pi/4
            xx=(np.cos(kx*(x[0]+8))-np.cos(kx*(cx+8)))/(kx*rx*np.sin(kx*(cx+8)))
            yy=(np.cos(ky*x[1])-np.cos(ky*cy))/(ky*ry*np.sin(ky*cy))
            rho=xx**2+yy**2
            if x.shape[0]>=3 and config.get('three_dimensional',False):
                cz=config.get('zcenter',0.); rz=config.get('zradius',1.)
                kz=np.pi/4
                zz=(np.cos(kz*(x[2]+2))-np.cos(kz*(cz+2)))/(kz*rz*np.sin(kz*(cz+2)))
                rho+=zz**2
            return np.tanh((rho-1.)/.7)
        return evaluate
    raise ValueError(f'Unknown initial condition {kind}')
