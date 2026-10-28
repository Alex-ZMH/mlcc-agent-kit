"""Deterministic vector result scaling; generic unit conversion remains in shared UNIT."""
from copy import deepcopy
from .common import ModuleError
from .scaling import finite

def mapped_history(history, context, dimension):
    f=context['derived']['factors']; rows=[]
    factors={
        't':f['time'],'E_applied':f['electric_field'],'mean_E':f['electric_field'],
        'mean_P':f['polarization'],'P_rms':f['polarization'],
        'E_depolarization_rms':f['electric_field'],'bound_charge_rms':f['polarization_gradient'],
        'gradient_by_spatial_axis_rms':f['polarization_gradient'],
        'enthalpy':f['energy'],'bulk':f['energy'],'gradient':f['energy'],'electric_enthalpy':f['energy'],
        'wall_position':f['length'],'wall_delta':f['length'],
        'wall_excess_energy':f['energy']/f['length']**(dimension-1),
        'profile_exact_RMS':f['polarization'],'min_polarization_magnitude':f['polarization'],
        'potential_BC_error':f['potential'],
        'raw_boundary_D_flux':f['polarization']*f['length']**(dimension-1)}
    for row in history:
        result={}
        for key,value in row.items():
            if key.startswith('Gauss_'):continue
            factor=factors.get(key,1.)
            result[key]=None if value is None else [finite(x*factor) for x in value] if isinstance(value,list) else finite(value*factor)
        rows.append(result)
    return rows

def result_view(payload, metrics, history, logs, context, refs):
    steady=payload['operation']=='vector_steady'
    reduced={'final':metrics['final'],'resources':metrics['resources'],'mesh_id':metrics['mesh_id'],
             'time':{'completed':history[-1]['t'],
                     'accepted_steps':sum(bool(r['accepted']) and not r.get('steady',False) for r in logs),
                     'rejected_steps':sum(not r['accepted'] for r in logs),'stationary_solved':steady}}
    si=None
    if context:
        d=payload['dimension']; f=context['derived']['factors']
        si={'final':mapped_history([history[-1]],context,d)[0],
            'units':{'coordinates':'m','P':'C/m^2','phi':'V','E':'V/m','D':'C/m^2','rho_bound':'C/m^3',
                     'time':'s','energy':context['derived']['energy_unit'],'wall_excess_energy':'J/m^2',
                     'raw_boundary_D_flux':'C/m' if d==2 else 'C'},
            'qc_domain':'dimensionless; tolerances are not converted into material acceptance',
            'material_calibration':'not_checked'}
    return {'schema_version':'phase_field.vector-result.v1',
            'operation':context['original_input']['operation'] if context else payload['operation'],
            'dimension':payload['dimension'],'model_profile':payload['model_profile'],
            'units':'SI' if context else 'dimensionless','solver_dimensionless':reduced,
            'results_si':si,'unit_mapping':context,'artifact_refs':refs}
