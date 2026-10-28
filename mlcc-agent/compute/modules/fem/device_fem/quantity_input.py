"""Windows-only explicit-quantity boundary. No unit factors or scientific imports."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys

from .common import ROOT, ModuleError, loads, read_json, validate_shape
from .validation import validate_input, LENGTHS

OPERATION = 'electrostatics_2d_quantities'
CORE_VERSION = '1.0.0'
SCHEMA = ROOT/'schemas/electrostatics.quantities.input.schema.json'


def prepare(payload):
    """Strict module schema and fixed field semantics; never mutate user input."""
    validate_shape(payload,read_json(SCHEMA))
    fields={}
    for name in LENGTHS:
        fields['/geometry/'+name.removesuffix('_m')]={'kind':'length'}
    fields['/out_of_plane_thickness']={'kind':'length'}
    fields['/mesh/target_size']={'kind':'length'}
    for name in ('terminal_a','terminal_b'):
        fields['/potentials/'+name]={'kind':'electric_potential'}
    for pointer in fields:
        value=payload
        for part in pointer.strip('/').split('/'): value=value[part]
        source=value['source']
        if not source['kind'].strip() or source['kind']=='unspecified' or not source['reference'].strip():
            raise ModuleError('INVALID_UNITS','Explicit nonblank quantity source required at '+pointer)
    fields['/geometry/active_gap_count']={'kind':'count'}
    fields['/material/relative_permittivity']={'kind':'relative_permittivity'}
    return {'schema_version':'mlcc.units-request.v1','action':'normalize_fields',
            'payload':deepcopy(payload),'fields':fields}


def invoke_core(request):
    core=ROOT.parents[1]/'mlcc/units.py'
    if not core.is_file():
        raise ModuleError('UNITS_CORE_UNAVAILABLE','Shared MLCC units core is missing; no local fallback')
    from .common import dumps
    try:
        p=subprocess.run([sys.executable,'-I',str(core)],input=dumps(request),
                         text=True,encoding='utf-8',capture_output=True,timeout=10,shell=False)
        if len(p.stdout.encode('utf-8'))>2*1024*1024:
            raise ValueError('Oversized core response')
        response=loads(p.stdout)
        if not isinstance(response,dict) or response.get('schema_version')!='mlcc.units-response.v1' or response.get('core_version')!=CORE_VERSION:
            raise ValueError('Unsupported shared core response/version')
        if p.returncode or response.get('ok') is not True:
            raise ModuleError('INVALID_UNITS',str(response.get('errors','Shared core rejected units')))
        return response['result']
    except ModuleError: raise
    except (OSError,subprocess.TimeoutExpired,ValueError,KeyError) as exc:
        raise ModuleError('UNITS_CORE_FAILED',str(exc)) from exc


def canonicalize(payload):
    """One shared-core call; return existing SI kernel input and auditable records."""
    request=prepare(payload)
    normalized=invoke_core(request)
    try:
        if set(normalized)!={'payload','records','core_version'} or normalized['core_version']!=CORE_VERSION:
            raise ValueError('Invalid batch normalization result')
        records=normalized['records']
        if set(records)!=set(request['fields']):
            raise ValueError('Incomplete quantity normalization records')
        data=normalized['payload']
        for pointer,spec in request['fields'].items():
            record=records[pointer]
            original=payload
            for part in pointer.strip('/').split('/'): original=original[part]
            expected_unit='m' if spec['kind']=='length' else 'V' if spec['kind']=='electric_potential' else '1'
            if record['normalized']['unit']!=expected_unit or record['original']['representation']!=original or record['conversion']['core_version']!=CORE_VERSION:
                raise ValueError('Quantity units/original/version disagree with field contract')
            value=data
            for part in pointer.strip('/').split('/'): value=value[part]
            if record['schema_version']!='mlcc.quantity.v1' or record['kind']!=spec['kind'] or record['normalized']['value']!=value:
                raise ValueError('Quantity record disagrees with canonical payload')
        si={'schema_version':'fea.electrostatics-input.v1','model':data['model'],'units':'SI',
            'geometry':{name:data['geometry'][name.removesuffix('_m')] for name in LENGTHS},
            'out_of_plane_thickness_m':data['out_of_plane_thickness'],
            'material':deepcopy(data['material']),
            'potentials':{name+'_V':data['potentials'][name] for name in ('terminal_a','terminal_b')},
            'mesh':{'target_size_m':data['mesh']['target_size']},'outputs':deepcopy(data['outputs'])}
        si['geometry']['active_gap_count']=data['geometry']['active_gap_count']
        validate_input(si)
        audit={'schema_version':'fem.unit-normalization.v1','core_version':CORE_VERSION,
               'input_schema':payload['schema_version'],'kernel_input_schema':si['schema_version'],
               'records':records,'rule':'Explicit field semantics -> shared units core -> validated SI kernel input; no WSL unit conversion'}
        return si,audit
    except ModuleError: raise
    except (ValueError,TypeError,KeyError) as exc:
        raise ModuleError('UNITS_CORE_FAILED',str(exc)) from exc
