"""Deterministic tensor view; off-diagonal signs and every component are retained."""
from copy import deepcopy
from .scaling import finite
from .vector_input import require
def matrix(value,d):
    require(isinstance(value,list) and len(value)==d and all(isinstance(row,list) and len(row)==d for row in value),'Full dimension-matched tensor required','INVALID_SCIENTIFIC_RESULT')
    return [[finite(x) for x in row] for row in value]
def result_view(p,response,context,refs):
    d=p['dimension'];names=['total_tangent_permittivity','background_permittivity','polarization_tangent_contribution','frozen_polarization_tensor']
    tensors={key:matrix(response[key],d) for key in names}
    physical=None
    if context:
        f=context['derived']['tensor_factor_F_per_m'];physical={key:[[finite(v*f) for v in row] for row in value] for key,value in tensors.items()}
    return {'schema_version':'phase_field.tangent-result.v1','operation':'dielectric_tangent_si' if context else 'dielectric_tangent',
            'dimension':d,'units':'SI' if context else 'dimensionless','response_class':response['response_class'],
            'tensor_units_nd':'dimensionless absolute D/E, not relative permittivity','tensors_dimensionless':tensors,
            'tensors_si':physical,'tensor_units_si':'F/m' if context else None,'relative_permittivity':None,
            'bias_field_dimensionless':deepcopy(response['bias_field']),
            'bias_field_si':[finite(v*context['derived']['factors']['electric_field']) for v in response['bias_field']] if context else None,
            'branch_id':response['branch_id'],'local_stability':deepcopy(response['stability_diagnostics']),
            'numerical_validation':response['validation_status'],'material_validation':'not_checked',
            'unit_mapping':context,'artifact_refs':refs}
