"""Windows standard-library Adapter for the public MLCC JSON subprocess contract."""
from pathlib import Path
import math

from . import VERSION
from .common import (ModuleError, artifact_path, digest, file_hash, read_json, write_json)
from .deployment import Deployment
from .validation import validate_input, validate_result

LIMITATIONS = [
    'Linear isotropic lossless 2D ideal-electrode model; no AC, leakage, breakdown, nonlinear dielectric or multiphysics.',
    'Explicit extruded depth; no finite-width edge correction or external air domain.',
    'Sharp-tip Emax is diagnostic, not breakdown/safety evidence.',
    'Single run does not establish mesh convergence or material/device applicability.',
    'Host deployment configuration is not frozen in the current public queued snapshot; keep host binding fixed from submit to worker.',
]


def check(name, status, message):
    return {'id':name,'status':status,'message':message}


def provenance(payload=None, environment=None, deployment=None):
    return {'evidence_kind':'real_computation' if environment else 'none',
            'method':{'name':'2D linear isotropic electrostatics, ideal electrodes, P1 energy capacitance','version':VERSION},
            'backend':{'name':'DOLFINx','version':environment['versions']['fenics-dolfinx'] if environment else 'not_recorded'},
            'units':{'charge_total_C':'C','charge_per_unit_depth_C_per_m':'C/m',
                     'energy_total_J':'J','energy_per_unit_depth_J_per_m':'J/m',
                     'capacitance_energy_total_F':'F','capacitance_energy_per_unit_depth_F_per_m':'F/m',
                     'capacitance_raw_flux_total_F':'F','outer_displacement_flux_total_C':'C',
                     'electric_field_max_V_per_m':'V/m','potential_min_V':'V','potential_max_V':'V',
                     'out_of_plane_thickness_m':'m','body_height_m':'m'},
            'conditions':{'scientific_input':payload or {},'adapter_host':'Linux' if deployment and deployment.config.get('transport')=='native_linux' else 'Windows',
                          'scientific_host':'native Linux' if deployment and deployment.config.get('transport')=='native_linux' else 'WSL','element_degree':1,'mpi_ranks':1,
                          'deployment_sha256':deployment.fingerprint if deployment else None},
            'applicability':'Numerical execution of a bounded idealized model; actual material/device applicability not_checked.',
            'sources':[{'kind':'code_provenance','reference':'modules/fem/SOURCES.json',
                        'description':'Extracted geometry, weak form and sign conventions; module-owned implementation.'}] +
                      ([{'kind':'material_parameter','reference':payload['material']['source_reference'],
                         'description':'User-supplied parameter source, not independently verified'}] if payload else [])}


def diagnostic_artifacts(directory):
    items = []
    if directory is None:
        return items
    root = Path(directory)
    for relative in ('native/request.json','native/launch.json','native/response.json','native/stdout.log','native/stderr.log','input.original.json','input.canonical-si.json','unit_normalization.json'):
        path = root/relative
        if path.is_file() and not path.is_symlink() and path.stat().st_size:
            items.append({'path':'artifacts/'+relative,'media_type':'application/json' if path.suffix == '.json' else 'text/plain',
                          'description':'Native launch/diagnostics; not independent scientific validation'})
    return items


def normalize(native, payload, directory, deployment):
    if not isinstance(native,dict) or native.get('schema_version') != 'fea.science-result.v1' or native.get('status') != 'succeeded':
        raise ModuleError('INVALID_SCIENTIFIC_RESULT','Scientific entry did not return a successful typed result')
    if native.get('input_sha256') != digest(payload):
        raise ModuleError('INVALID_SCIENTIFIC_RESULT','Native result belongs to another scientific input')
    try:
        results = native['results']
        validate_result(results,payload)
        env = native['environment']
        if env['versions']['fenics-dolfinx'] != '0.11.0' or not env['ready']:
            raise ValueError('Unsupported or missing backend version')
        diag = native['diagnostics']
        if type(diag['solver']['converged_reason']) is not int or diag['solver']['converged_reason'] <= 0:
            raise ValueError('Solver did not converge')
        if not math.isfinite(diag['solver']['assembled_residual_norm']):
            raise ValueError('Invalid residual diagnostic')
        if not diag['mesh']['semantic_audit']['valid'] or diag['mesh']['cells'] != results['mesh_cells']:
            raise ValueError('Mesh evidence inconsistent with result')
        refs, descriptors, hashes = set(), [], {}
        for item in native['artifacts']:
            reference = item['path']
            if reference in refs:
                raise ValueError('Duplicate native artifact')
            path = artifact_path(directory,reference)
            if file_hash(path) != item['sha256']:
                raise ValueError('Native artifact changed or has incorrect hash')
            refs.add(reference)
            hashes[reference] = item['sha256']
            descriptors.append({k:item[k] for k in ('path','media_type','description')})
        required = {results[k] for k in ('field_artifact','mesh_artifact','diagnostics_artifact')}
        required |= {'artifacts/fields/manifest.json','artifacts/mesh/semantic_regions.json',
                     'artifacts/mesh/mesh_report.json','artifacts/metrics.json',
                     'artifacts/input.normalized.json','artifacts/method_environment.json'}
        if required-refs:
            raise ValueError('Missing required native evidence: '+str(sorted(required-refs)))
        if read_json(artifact_path(directory,'artifacts/metrics.json')) != results:
            raise ValueError('Native metrics file disagrees with structured result')
        if read_json(artifact_path(directory,'artifacts/diagnostics.json')) != diag:
            raise ValueError('Native diagnostics file disagrees with response')
        if not isinstance(native['warnings'],list) or any(not isinstance(w,str) for w in native['warnings']):
            raise ValueError('Invalid native warning list')
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        raise ModuleError('INVALID_SCIENTIFIC_RESULT',str(exc)) from exc
    qc = {'numerical':[
        check('mesh_semantics','passed','Nonempty CERAMIC/A/B/outer; exact exterior coverage, no overlaps/internal mislabeled facets.'),
        check('mesh_geometry','passed','Finite coordinates and nondegenerate P1 triangles; shape metrics recorded, shape threshold not assessed.'),
        check('linear_solver','passed',f'PETSc reason={diag["solver"]["converged_reason"]}; finite assembled residual {diag["solver"]["assembled_residual_norm"]:.6g}.'),
        check('field_finiteness','passed','Native finite arrays and VTU round-trip; Windows verifies file hashes, typed results and normalization.'),
        check('depth_units','passed','Explicit t and consistent total/per-depth Q/U/C. Model uses full stack; no extra layer multiplier.'),
        check('residual_acceptance','not_checked','Assembled residual recorded; no approved residual acceptance threshold.'),
        check('mesh_shape_acceptance','not_checked','Minimum normalized triangle shape recorded; no approved quality threshold.'),
        check('charge_balance','not_checked',f'Measured terminal relative imbalance={results["charge_balance_relative"]:.9g}; no approved product tolerance.'),
        check('capacitance_consistency','not_checked',f'Measured raw-flux/energy relative difference={results["capacitance_methods_relative"]:.9g}; no approved product tolerance.'),
        check('mesh_convergence','not_checked','A single run does not compare independently refined meshes.'),
        check('analytic_reference','not_checked','Analytical qualification is separate harness evidence, not automatically attached to this run.')],
        'scientific':[
        check('model_applicability','not_checked','No scientific owner sign-off on actual device/use conditions.'),
        check('material_provenance','not_checked','Parameter source retained; material validity at operating conditions is not independently verified.'),
        check('independent_device_reference','not_checked','No measured device reference supplied.') ]}
    write_json(Path(directory)/'quality.json',qc)
    write_json(Path(directory)/'artifact_hashes.json',hashes)
    descriptors += [{'path':'artifacts/quality.json','media_type':'application/json','description':'Deterministic checks with unassessed items explicitly not_checked'},
                    {'path':'artifacts/artifact_hashes.json','media_type':'application/json','description':'Windows-verified native evidence hashes'}]
    return {'schema_version':'mlcc.adapter-result.v1','execution_status':'succeeded',
            'provenance':provenance(payload,env,deployment),'results':results,'quality':qc,
            'errors':[],'warnings':native['warnings'],'limitations':LIMITATIONS,
            'artifacts':descriptors+[a for a in diagnostic_artifacts(directory) if a['path'] not in refs]}


def handle(request):
    preflight = isinstance(request,dict) and request.get('action') == 'preflight'
    payload, deployment, directory = None, None, None
    unit_audit = None
    try:
        keys = {'schema_version','interface_version','action','module_id','operation','input','task_id','artifact_dir'}
        if not isinstance(request,dict) or set(request) != keys or request['schema_version'] != 'mlcc.adapter-request.v1' or request['interface_version'] != '1.0':
            raise ModuleError('INVALID_REQUEST','Invalid public Adapter request envelope')
        if request['operation'] in ('electrothermal_2d','ac_eqs_2d','electromagnetic_2d','electrothermal_2d_quantities','ac_eqs_2d_quantities','electromagnetic_2d_quantities'):
            from .extended_adapter import handle as handle_extended
            return handle_extended(request)
        if request['module_id'] != 'fem' or request['operation'] not in ('electrostatics_2d','electrostatics_2d_quantities') or request['action'] not in ('preflight','execute'):
            raise ModuleError('UNSUPPORTED_OPERATION','Only FEM electrostatics SI/explicit-quantity operations are implemented')
        if request['operation'] == 'electrostatics_2d_quantities':
            from .quantity_input import canonicalize
            payload, unit_audit = canonicalize(request['input'])
        else:
            payload = validate_input(request['input'])
        if preflight and (request['task_id'] is not None or request['artifact_dir'] is not None):
            raise ModuleError('INVALID_REQUEST','Preflight must not have a task/artifact directory')
        deployment = Deployment.load()
        estimate = deployment.check_resources(payload)
        if preflight:
            env = deployment.probe()
            return {'schema_version':'mlcc.adapter-preflight.v1','ready':True,'errors':[],
                    'warnings':['Idealized 2D electrostatics only; scientific applicability remains not_checked.'],
                    'checks':[check('scientific_input','passed','Validated SI geometry/material/potentials/depth; shared core '+unit_audit['core_version']+' normalized explicit quantities.' if unit_audit else 'Explicit SI geometry/material/potentials/depth are valid.'),
                              check('resource_budget','passed',f'Planning estimate={estimate}, host max_cells={deployment.config["max_cells"]}; actual mesh is checked again.'),
                              check('backend_environment','passed',f'DOLFINx {env["versions"]["fenics-dolfinx"]}; deployment_sha256={deployment.fingerprint}') ]}
        import re
        if not isinstance(request['task_id'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}',request['task_id']):
            raise ModuleError('INVALID_REQUEST','A runtime-owned task ID is required')
        directory = Path(request['artifact_dir'])
        if not directory.is_absolute() or directory.is_symlink():
            raise ModuleError('INVALID_REQUEST','A runtime-owned absolute artifact directory is required')
        if unit_audit is not None:
            write_json(directory/'input.original.json',request['input'])
            write_json(directory/'input.canonical-si.json',payload)
            write_json(directory/'unit_normalization.json',unit_audit)
        native = deployment.execute(payload,directory,request['task_id'])
        result = normalize(native,payload,directory,deployment)
        if unit_audit is not None:
            result['provenance']['conditions']['input_normalization'] = {
                'core_version':unit_audit['core_version'],
                'original_input_artifact':'artifacts/input.original.json',
                'canonical_si_artifact':'artifacts/input.canonical-si.json',
                'report_artifact':'artifacts/unit_normalization.json'}
        return result
    except Exception as exc:
        code = getattr(exc,'code','ADAPTER_ERROR')
        if preflight:
            return {'schema_version':'mlcc.adapter-preflight.v1','ready':False,
                    'errors':[{'code':code,'message':str(exc)}],'warnings':[],'checks':[]}
        # Do not render unvalidated input into provenance on early input failure.
        safe_payload = payload if isinstance(payload,dict) and 'material' in payload else None
        return {'schema_version':'mlcc.adapter-result.v1',
                'execution_status':'blocked' if code in ('DEPLOYMENT_NOT_CONFIGURED','INVALID_DEPLOYMENT','BACKEND_UNAVAILABLE','RESOURCE_LIMIT','INVALID_INPUT','INVALID_GEOMETRY','INVALID_MATERIAL','INVALID_POTENTIALS','INVALID_REQUEST','UNSUPPORTED_OPERATION','TASK_ALREADY_STARTED','INVALID_UNITS','UNITS_CORE_UNAVAILABLE','UNITS_CORE_FAILED') else 'failed',
                'provenance':provenance(safe_payload), 'results':{},
                'quality':{'numerical':[],'scientific':[]},'errors':[{'code':code,'message':str(exc)}],
                'warnings':[], 'limitations':LIMITATIONS+(['Scientific process state is unknown; timeout/interruption does NOT prove Linux solver termination.'] if code == 'SCIENTIFIC_STATE_UNKNOWN' else []),
                'artifacts':diagnostic_artifacts(directory)}


