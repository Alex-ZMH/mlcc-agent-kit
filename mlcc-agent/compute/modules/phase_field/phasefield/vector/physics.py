"""Synthetic dimensionless tetragonal LGD. No BaTiO3 material calibration."""
from dataclasses import dataclass,asdict
import itertools,math
import numpy as np
@dataclass(frozen=True)
class Parameters:
    a:float=-.5
    b:float=.25
    c:float=1.5
    g:float=.5
    epsilon:float=1.
    mobility:float=1.
    def __post_init__(self):
        if any(isinstance(v,bool) or not math.isfinite(v) for v in asdict(self).values()):raise ValueError('finite numeric parameters required')
        if not(self.a<0 and self.b>0 and self.c>2*self.b and self.g>0 and self.epsilon>0 and self.mobility>0):raise ValueError('axis minima/coercive quartic require a<0,b>0,c>2b,g/epsilon/mobility>0')
    @property
    def Ps(self):return math.sqrt(-self.a/(2*self.b))
    @property
    def delta(self):return math.sqrt(self.g/abs(self.a))
    def as_dict(self):return asdict(self)
def bulk(P,p):return p.a*np.sum(P*P,axis=-1)+p.b*np.sum(P**4,axis=-1)+p.c*sum(P[...,i]**2*P[...,j]**2 for i in range(P.shape[-1]) for j in range(i))
def gradient(P,p):return 2*p.a*P+4*p.b*P**3+2*p.c*P*(np.sum(P*P,axis=-1,keepdims=True)-P*P)
def hessian(P,p):
    P=np.asarray(P);D=len(P);H=4*p.c*np.outer(P,P)
    np.fill_diagonal(H,2*p.a+12*p.b*P**2+2*p.c*(P@P-P**2));return H
def stationary(D,p):
    rows=[]
    for k in range(D+1):
        amp=np.sqrt(-p.a/(2*p.b+p.c*(k-1))) if k else 0
        for axes in itertools.combinations(range(D),k):
            for signs in itertools.product([-1,1],repeat=k):
                P=np.zeros(D);P[list(axes)]=amp*np.array(signs);ev=np.linalg.eigvalsh(hessian(P,p))
                rows.append({'P':P.tolist(),'active_components':k,'energy':float(bulk(P,p)),'gradient_norm':float(np.linalg.norm(gradient(P,p))),'Hessian_eigenvalues':ev.tolist(),'strict_minimum':bool(min(ev)>1e-10)})
    return rows
def wall_states(D,kind):
    left=np.zeros(D);right=np.zeros(D);n=np.zeros(D)
    if kind=='180':left[0]=-1;right[0]=1;n[1]=1
    elif kind in ['90xy','90xz']:
        axis=1 if kind=='90xy' else 2
        if axis>=D:raise ValueError('xz wall needs 3 polarization components')
        left[0]=1;right[axis]=1;n[0]=n[axis]=1/np.sqrt(2)
    else:raise ValueError('unknown wall')
    return left,right,n
def frame(n):
    n=np.array(n,float);n/=np.linalg.norm(n)
    if len(n)==2:return np.column_stack([n,[-n[1],n[0]]])
    t=np.eye(3)[np.argmin(abs(n))];t-=n*(n@t);t/=np.linalg.norm(t);return np.column_stack([n,t,np.cross(n,t)])
def wall_profile(s,D,kind,p,width=1.):
    l,r,_=wall_states(D,kind);v=np.tanh(np.asarray(s)/(p.delta*width));return p.Ps*((l+r)/2+v[...,None]*(r-l)/2)
def rk4(P0,times,field,p,hmax=1e-4):
    """Independent explicit ODE reference, not FEM/BE/Newton implementation."""
    P=np.array(P0,float);out=[P.copy()];t=float(times[0])
    fun=lambda t,x:-p.mobility*(gradient(x,p)-np.asarray(field(t)))
    for end in times[1:]:
        steps=max(1,int(np.ceil((end-t)/hmax)));h=(end-t)/steps
        for _ in range(steps):
            k1=fun(t,P);k2=fun(t+h/2,P+h*k1/2);k3=fun(t+h/2,P+h*k2/2);k4=fun(t+h,P+h*k3);P+=h*(k1+2*k2+2*k3+k4)/6;t+=h
        out.append(P.copy())
    return np.array(out)
