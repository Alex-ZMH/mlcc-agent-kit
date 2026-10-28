"""Physical nondimensionalization only; generic unit conversion belongs to mlcc.units."""
from copy import deepcopy
import math
from .common import ModuleError,digest


def finite(value,positive=False):
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or positive and value<=0:
        raise ModuleError('INVALID_SCALES','Finite '+('positive ' if positive else '')+'mapped quantity required')
    return value


def derive(scales,dimension):
    """Independent SI l,P0,T,f0; the coupling term fixes potential/field scales."""
    l,p,t,f=[finite(scales[k],True) for k in ('length','polarization','time','energy_density')]
    try:
        values={'length':l,'polarization':p,'time':t,'energy_density':f,
                'potential':f*l/p,'electric_field':f/p,'displacement':p,
                'epsilon':p*p/f,'g':f*l*l/(p*p),'energy':f*l**dimension,
                'polarization_gradient':p/l}
        coefficients={'alpha':-f/(p*p),'beta':f/p**4,'gamma':0.,'mobility':p*p/(f*t)}
        for v in values.values():finite(v,True);finite(1/v,True)
        for k in ('alpha','beta','mobility'):finite(abs(coefficients[k]),True)
    except (OverflowError,ZeroDivisionError) as e:raise ModuleError('INVALID_SCALES','Noninvertible/overflowed derived scales') from e
    return {'factors':values,'profile_coefficients_si':coefficients,
            'energy_unit':'J/m' if dimension==2 else 'J',
            'factor_units_si':{'length':'m','polarization':'C/m^2','time':'s','energy_density':'J/m^3',
                               'potential':'V','electric_field':'V/m','displacement':'C/m^2','epsilon':'F/m',
                               'g':'J*m^3/C^2','energy':'J/m' if dimension==2 else 'J','polarization_gradient':'C/m^3'},
            'coefficient_units':{'alpha':'J m/C^2','beta':'J m^5/C^4','gamma':'J m^9/C^6','mobility':'C^2/(J m s)'},
            'relations':'x=l*x_nd; P=P0*P_nd; t=T*t_nd; phi=f0*l/P0*phi_nd; E=f0/P0*E_nd; eps_nd=eps*f0/P0^2; g_nd=kappa*P0^2/(f0*l^2)',
            'profile_constraint':'alpha_nd=-1,beta_nd=1,gamma_nd=0,mobility_nd=1; derived coefficients are a constrained family, not material calibration'}


def to_dimensionless(si):
    """Consume numeric canonical SI, never a Quantity/audit wrapper, exactly once."""
    p=deepcopy(si);d=derive(p.pop('reference_scales'),p['dimension']);f=d['factors']
    p['units']='dimensionless';p['operation']=p['operation'].removesuffix('_si')
    p['g']=finite(p['g']/f['g'],True);p['epsilon']=finite(p['epsilon']/f['epsilon'],True)
    p['applied_E']=finite(p['applied_E']/f['electric_field'])
    for key in ('end','dt'):
        if 'evolution' in p:p['evolution'][key]=finite(p['evolution'][key]/f['time'],True)
    c=p['initial']
    for key in ('value','amplitude','reference'):
        if key in c:c[key]=finite(c[key]/f['polarization'])
    for key in ('width','wall_center','zcenter','zradius'):
        if key in c:c[key]=finite(c[key]/f['length'])
    for key in ('center','radii'):
        if key in c:c[key]=[finite(v/f['length']) for v in c[key]]
    d['physical_parameters_si']={'g':finite(p['g']*f['g'],True),'epsilon_absolute':finite(p['epsilon']*f['epsilon'],True),'applied_E':finite(p['applied_E']*f['electric_field'])}
    d['parameter_units_si']={'g':'J*m^3/C^2','epsilon_absolute':'F/m','applied_E':'V/m'}
    return p,d


def mapped_summary(nd,mapping):
    f=mapping['derived']['factors']
    def stats(x,factor):return {k:finite(v*factor) for k,v in x.items()}
    x=nd['wall']['centerline_unique_x']
    return {'dimension':nd['dimension'],'units':{'P':'C/m^2','phi':'V','E_magnitude':'V/m','coordinates':'m','time':'s','electric_enthalpy':mapping['derived']['energy_unit'],'P_gradient_rms':'C/m^3'},
            'fields':{**{k:stats(nd['fields'][k],f[scale]) for k,scale in [('P','polarization'),('phi','potential'),('E_magnitude','electric_field')]},
                      'P_gradient_rms':[finite(v*f['polarization_gradient']) for v in nd['fields']['P_gradient_rms']]},
            'completed_time':finite(nd['time']['completed']*f['time']),
            'electric_enthalpy':finite(nd['electric_enthalpy']*f['energy']),
            'centerline_unique_wall_x':None if x is None else finite(x*f['length']),
            'fixed_domain_m':[[finite(-8*f['length']),finite(8*f['length'])],[0.,finite(4*f['length'])]]+([[finite(-2*f['length']),finite(2*f['length'])]] if nd['dimension']==3 else []),
            'qc_domain':'dimensionless; no SI residual tolerance inferred',
            'material_calibration':'not_checked'}
