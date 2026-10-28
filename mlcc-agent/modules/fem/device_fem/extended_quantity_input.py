"""Typed inputs for device extensions, normalized by the one shared MLCC core.

No factors, temperature offsets, environment commands or scientific imports here.
"""
from copy import deepcopy
from .common import ROOT, ModuleError, read_json, validate_shape
from .validation import LENGTHS
from .quantity_input import invoke_core
from .extended_contract import OPERATIONS, validate_input as validate_si

OPERATIONS_QUANTITIES={name+'_quantities':name for name in OPERATIONS}


def schema_path(operation):
    if operation not in OPERATIONS_QUANTITIES:raise ModuleError('UNSUPPORTED_OPERATION','Unknown typed device operation')
    return ROOT/f'schemas/{OPERATIONS[OPERATIONS_QUANTITIES[operation]]}.quantities.input.schema.json'


def get(container,pointer):
    value=container
    for token in pointer.strip('/').split('/'):value=value[token]
    return value


def field_specs(payload,operation):
    """Bind field semantics/targets; conversions exist only in the public core."""
    base=OPERATIONS_QUANTITIES[operation];specs={};targets={}
    def add(raw,target,kind):
        specs[raw]={'kind':kind};targets[raw]=target
    for key in LENGTHS:add('/geometry/'+key.removesuffix('_m'),'/geometry/'+key,'length')
    add('/out_of_plane_thickness','/out_of_plane_thickness_m','length')
    add('/mesh/target_size','/mesh/target_size_m','length')
    add('/frequency','/frequency_Hz','frequency')
    for name in payload['materials']:
        add(f'/materials/{name}/sigma',f'/materials/{name}/sigma_S_m','electrical_conductivity')
    for raw,target,kind in [('ceramic_k','ceramic_k_W_per_m_K','thermal_conductivity'),('Ni_k','Ni_k_W_per_m_K','thermal_conductivity'),('ambient','ambient_K','temperature'),('convection_h','convection_h_W_per_m2_K','heat_transfer_coefficient')]:
        add('/thermal/'+raw,'/thermal/'+target,kind)
    if base=='electromagnetic_2d':
        for raw,target in [('bus_width','bus_width_m'),('feed_air','feed_air_m'),('bottom_air','bottom_air_m')]:add('/port/'+raw,'/port/'+target,'length')
        for component in ('real','imag'):add('/current/'+component,'/current/'+component+'_A_rms','current')
    else:
        for key in payload['potentials']:add('/potentials/'+key,'/potentials/'+key+'_V','electric_potential')
    for pointer in specs:
        source=get(payload,pointer)['source']
        if not source['kind'].strip() or source['kind']=='unspecified' or not source['reference'].strip():raise ModuleError('INVALID_UNITS','Explicit nonblank quantity source required at '+pointer)
    specs['/geometry/active_gap_count']={'kind':'count'};targets['/geometry/active_gap_count']='/geometry/active_gap_count'
    for name,material in payload['materials'].items():
        for key,kind in [('eps_r','relative_permittivity'),('tan_delta','dimensionless_parameter')]:
            path=f'/materials/{name}/{key}';specs[path]={'kind':kind,'source':{'kind':'parameter_reference','reference':material['source_reference']}};targets[path]=path
    if 'mu_r' in payload:
        specs['/mu_r']={'kind':'dimensionless_parameter','source':{'kind':'declared_model','reference':'fixed mu_r=1 in the supported 2D Maxwell model'}};targets['/mu_r']='/mu_r'
    return specs,targets


def prepare(payload,operation):
    validate_shape(payload,read_json(schema_path(operation)))
    specs,targets=field_specs(payload,operation)
    return {'schema_version':'mlcc.units-request.v1','action':'normalize_fields','payload':deepcopy(payload),'fields':specs},targets


def rename_fields(data,targets):
    """Rename normalized scalar paths to the unchanged, strictly typed SI contract."""
    si=deepcopy(data)
    for raw,target in targets.items():
        if raw==target:continue
        tokens=raw.strip('/').split('/');parent=si
        for token in tokens[:-1]:parent=parent[token]
        value=parent.pop(tokens[-1]);target_tokens=target.strip('/').split('/');parent=si
        for token in target_tokens[:-1]:parent=parent[token]
        parent[target_tokens[-1]]=value
    si['schema_version']='fem.'+si['analysis']+'-input.v1';si['units']='SI'
    if si['analysis']=='electromagnetic':si['current'].pop('convention')
    return si


# Canonical spellings/field semantics only; no factors, aliases or offsets.
# These units are asserted against the shared catalog before normalization.
KIND_UNITS={'length':'m','frequency':'Hz','electric_potential':'V','current':'A',
            'electrical_conductivity':'S/m','thermal_conductivity':'W/(m K)',
            'heat_transfer_coefficient':'W/(m^2 K)','temperature':'K',
            'relative_permittivity':'1','dimensionless_parameter':'1','count':'1'}
KIND_DIMENSIONS={kind:('dimensionless' if unit=='1' else kind) for kind,unit in KIND_UNITS.items()}


def canonicalize(payload,operation):
    from .common import dumps
    from .quantity_input import CORE_VERSION
    request,targets=prepare(payload,operation)
    catalog=invoke_core({'schema_version':'mlcc.units-request.v1','action':'catalog'})
    try:
        kinds=catalog['kinds']
        if not isinstance(catalog.get('catalog_version'),str) or not catalog['catalog_version'].strip():raise ValueError('Shared units catalog version is required for audit')
        for spec in request['fields'].values():
            kind=spec['kind']
            if kinds[kind]['canonical_unit']!=KIND_UNITS[kind] or kinds[kind]['dimension']!=KIND_DIMENSIONS[kind]:raise ValueError('Shared catalog semantics do not match field contract: '+kind)
            if catalog['units'][KIND_UNITS[kind]]['dimension']!=KIND_DIMENSIONS[kind]:raise ValueError('Missing/incompatible canonical unit: '+kind)
    except (KeyError,TypeError,ValueError) as exc:
        raise ModuleError('UNITS_CORE_UNAVAILABLE',str(exc)) from exc
    batch=invoke_core(request)
    try:
        if not isinstance(batch,dict) or set(batch)!={'payload','records','core_version'} or batch['core_version']!=CORE_VERSION or set(batch['records'])!=set(request['fields']):raise ValueError('Incomplete/shared batch normalization result')
        expected=deepcopy(payload)
        for pointer,spec in request['fields'].items():
            record=batch['records'][pointer];kind=spec['kind']
            if record['schema_version']!='mlcc.quantity.v1' or record['kind']!=kind or record['dimension']!=kinds[kind]['dimension'] or record['normalized']['unit']!=KIND_UNITS[kind] or record['conversion']['core_version']!=CORE_VERSION:
                raise ValueError('Quantity record semantic/unit/version mismatch: '+pointer)
            # The core resolves typography/aliases; FEM does not implement a
            # second spelling normalizer or a conversion table.
            if catalog['units'][record['conversion']['unit_key']]['dimension']!=KIND_DIMENSIONS[kind]:
                raise ValueError('Actual input unit missing/incompatible in shared catalog: '+pointer)
            if dumps(record['original']['representation'])!=dumps(get(payload,pointer)):
                raise ValueError('Shared core did not preserve original quantity: '+pointer)
            if isinstance(get(payload,pointer),dict) and record['original']['source']!=get(payload,pointer)['source']:
                raise ValueError('Shared core changed quantity source: '+pointer)
            parent=expected;tokens=pointer.strip('/').split('/')
            for token in tokens[:-1]:parent=parent[token]
            parent[tokens[-1]]=record['normalized']['value']
        if dumps(batch['payload'])!=dumps(expected):raise ValueError('Shared core changed undeclared fields')
        si=rename_fields(batch['payload'],targets)
        validate_si(si,OPERATIONS_QUANTITIES[operation])
        audit={'schema_version':'fem.extended-quantity-normalization.v1','core_version':CORE_VERSION,
               'catalog_version':catalog['catalog_version'],'input_schema':payload['schema_version'],
               'kernel_input_schema':si['schema_version'],'kernel_operation':OPERATIONS_QUANTITIES[operation],
               'field_targets':targets,'records':batch['records'],
               'rule':'All dimensional input quantities -> unique shared normalize_fields -> existing SI validator/kernel; peak/RMS is unchanged physical convention.'}
        return si,audit
    except ModuleError:raise
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        raise ModuleError('UNITS_CORE_FAILED',str(exc)) from exc
