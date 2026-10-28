"""SI field semantics and public unit-core invocation. No unit table or local fallback."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from .common import ROOT,ModuleError,dumps,loads,digest,read_json
from .validation import shape,validate_input
from .scaling import to_dimensionless,mapped_summary


def field_semantics(p):
    fields={f'/reference_scales/{k}':{'kind':kind} for k,kind in [('length','length'),('polarization','polarization'),('time','time'),('energy_density','energy_density')]}
    fields.update({'/g':{'kind':'gradient_coefficient'},'/epsilon':{'kind':'absolute_permittivity'},'/applied_E':{'kind':'electric_field'}})
    ic=p['initial']
    for k in ('value','amplitude','reference'):
        if k in ic:fields['/initial/'+k]={'kind':'polarization'}
    for k in ('width','wall_center','zcenter','zradius'):
        if k in ic:fields['/initial/'+k]={'kind':'length'}
    for k in ('center','radii'):
        if k in ic:
            for i in range(len(ic[k])):fields[f'/initial/{k}/{i}']={'kind':'length'}
    if p['operation']=='evolve_si':
        for k in ('end','dt'):fields['/evolution/'+k]={'kind':'time'}
    return fields


def unit_core(request):
    core=ROOT.parents[1]/'src/mlcc/units.py'
    if not core.is_file():raise ModuleError('UNIT_CORE_UNAVAILABLE','Public mlcc/units.py is required for SI input; no local fallback')
    try:
        p=subprocess.run([sys.executable,'-I',str(core)],input=dumps(request),capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=3,shell=False)
        response=loads(p.stdout)
    except (OSError,subprocess.TimeoutExpired,ValueError) as e:raise ModuleError('UNIT_CORE_UNAVAILABLE',str(e)) from e
    if not isinstance(response,dict) or response.get('schema_version')!='mlcc.units-response.v1' or response.get('core_version')!='1.0.0':
        raise ModuleError('UNIT_CORE_INCOMPATIBLE','Expected public units response v1 / core 1.0.0')
    if p.returncode or not response.get('ok'):
        raise ModuleError('INVALID_UNITS',str(response.get('errors','Public unit conversion failed')))
    if not isinstance(response.get('result'),dict):raise ModuleError('UNIT_CORE_INCOMPATIBLE','Public core result must be an object')
    return response['result']


def prepare_si(p,operation):
    if operation not in ('steady_si','evolve_si'):raise ModuleError('UNSUPPORTED_OPERATION','Use steady_si/evolve_si')
    shape(p,read_json(ROOT/'schemas'/f'{operation}.input.schema.json'))
    # A dedicated raw-only SI schema rejects normalized records and mixed/double conversion input.
    result=unit_core({'schema_version':'mlcc.units-request.v1','action':'normalize_fields','payload':p,'fields':field_semantics(p)})
    # Result extraction follows the public contract; no conversion is repeated by the solver.
    return finish_prepare(p,result)


def finish_prepare(original,normalization):
    # Exact public normalize_fields result, including original/normalized values and rules.
    if set(normalization)!={'payload','records','core_version'} or normalization['core_version']!='1.0.0':
        raise ModuleError('UNIT_CORE_INCOMPATIBLE','Invalid public normalization report')
    semantics=field_semantics(original);records=normalization['records'];expected=deepcopy(original)
    if set(records)!=set(semantics):raise ModuleError('UNIT_CORE_INCOMPATIBLE','Public unit audit fields do not match declared semantics')
    for pointer,spec in semantics.items():
        record=records[pointer];parts=pointer.lstrip('/').split('/');parent=expected
        for part in parts[:-1]:parent=parent[int(part)] if isinstance(parent,list) else parent[part]
        key=int(parts[-1]) if isinstance(parent,list) else parts[-1]
        if record.get('schema_version')!='mlcc.quantity.v1' or record.get('kind')!=spec['kind'] or record.get('conversion',{}).get('core_version')!='1.0.0' or record.get('original',{}).get('representation')!=parent[key]:
            raise ModuleError('UNIT_CORE_INCOMPATIBLE','Public quantity audit semantic/original mismatch: '+pointer)
        normalized=record.get('normalized',{})
        if not isinstance(normalized.get('unit'),str) or not normalized['unit']:
            raise ModuleError('UNIT_CORE_INCOMPATIBLE','Public canonical unit missing: '+pointer)
        from .scaling import finite
        parent[key]=finite(normalized.get('value'))
    canonical=normalization['payload']
    if canonical!=expected:raise ModuleError('UNIT_CORE_INCOMPATIBLE','Public normalizer changed an undeclared field or lost canonical/audit consistency')
    nd,derived=to_dimensionless(canonical);validate_input(nd)
    context={'schema_version':'phase_field.unit-mapping.v1','core_version':'1.0.0','original_input':deepcopy(original),
             'original_input_sha256':digest(original),'canonical_si':canonical,'normalization_report':normalization,
             'solver_dimensionless_input':nd,'solver_input_sha256':digest(nd),'derived':derived,
             'qc_domain':'dimensionless','material_calibration':'not_checked'}
    return nd,context


def si_result(nd,context):
    refs=nd['artifact_refs']
    return {'operation':context['original_input']['operation'],'dimension':nd['dimension'],'units':'SI','model_profile':nd['model_profile'],
            'unit_mapping':context,'results_si':mapped_summary(nd,context),'solver_dimensionless':nd,'artifact_refs':refs}
