"""Windows Adapter for extended device operations; deterministic, stdlib only."""
from pathlib import Path
import re
from . import VERSION
from .common import ROOT, ModuleError, digest, artifact_path, file_hash, read_json, write_json
from .deployment import Deployment
from .extended_contract import OPERATIONS, NUMERICAL_CHECKS, PHYSICAL_CHECKS, canonicalize, validate_result, evaluate_checks
from .adapter_api import check, diagnostic_artifacts
from .extended_quantity_input import OPERATIONS_QUANTITIES, canonicalize as canonicalize_quantities
SUPPORTED_OPERATIONS=set(OPERATIONS)|set(OPERATIONS_QUANTITIES)

LIMITATIONS=[
 '2D linear passive model; explicit depth, no 3D packaging/radiation or actual material calibration.',
 'One-way steady heat, no temperature feedback, transient, thermomechanics or magnetic hysteresis.',
 'Raw gradient flux and port differences are diagnostics; single task does not establish convergence.',
 'EM uses specified closed guide and mu_r=1; port R/L are not commercial ESR/ESL or an accepted SRF.',
 'Host binding must remain fixed between submit and worker; timeout does not prove WSL solver termination.',
]


def provenance(payload=None,environment=None,deployment=None):
    return {'evidence_kind':'real_computation' if environment else 'none',
      'method':{'name':'2D '+(payload['analysis'] if payload else 'device extension')+', P1 serial, one-way steady heat','version':VERSION},
      'backend':{'name':'DOLFINx','version':environment['versions']['fenics-dolfinx'] if environment else 'not_recorded'},
      'units':{'frequency_Hz':'Hz','out_of_plane_thickness_m':'m','electrical.loss_total_W':'W','electrical.loss_ceramic_W':'W','electrical.loss_metal_W':'W',
               'electrical.electric_field_max_V_per_m':'V/m','electrical.capacitance_F':'F','electrical.electric_energy_J':'J','electrical.magnetic_energy_J':'J',
               'electrical.magnetic_inductance_H':'H','electrical.admittance_S':'S','electrical.impedance_ohm':'ohm',
               'thermal.maximum_temperature_K':'K','thermal.mean_temperature_K':'K','thermal.maximum_rise_K':'K','thermal.mean_rise_K':'K',
               'thermal.hotspot_thermal_resistance_K_per_W':'K/W','thermal.mean_thermal_resistance_K_per_W':'K/W','thermal.source_power_W':'W','thermal.outward_power_W':'W','thermal.raw_outward_power_W':'W'},
      'conditions':{'scientific_input':payload or {},'adapter_host':'Linux' if deployment and deployment.config.get('transport')=='native_linux' else 'Windows','scientific_host':'native Linux' if deployment and deployment.config.get('transport')=='native_linux' else 'WSL','mpi_ranks':1,
                    'complex_pairs':'[real, imaginary]; RMS exp(+j omega t) for AC/EM',
                    'deployment_sha256':deployment.fingerprint if deployment else None,
                    'normalization_report':'artifacts/unit_normalization.json'},
      'applicability':'Bounded numerical model; material, ports and actual device applicability not_checked.',
      'sources':[{'kind':'code_provenance','reference':'modules/fem/EXTENDED_SOURCES.json','description':'Reviewed electrothermal, AC-EQS and Maxwell experiment kernels extracted into module.'}]+
                ([{'kind':'material_parameter','reference':m['source_reference'],'description':'Declared '+name+' coefficients; not independently calibrated'} for name,m in payload['materials'].items()] if payload else [])}


def normalize(native,payload,directory,deployment):
    try:
        if not isinstance(native,dict) or native.get('schema_version')!='fea.science-result.v1' or native.get('status')!='succeeded' or native.get('input_sha256')!=digest(payload):raise ValueError('Invalid native identity/status/digest')
        results=native['results']; validate_result(results,payload)
        env=native['environment']; diag=native['diagnostics']
        if not env['ready'] or env['versions']['fenics-dolfinx']!='0.11.0':raise ValueError('Unreviewed scientific environment')
        if diag['analysis']!=payload['analysis'] or diag['mesh_cells']!=results['mesh_cells']:raise ValueError('Mesh/model diagnostics mismatch')
        if any(type(v) is not bool for v in diag['checks'].values()):raise ValueError('Quality checks must be booleans')
        if diag['checks']!=evaluate_checks(payload,diag):raise ValueError('Quality flags disagree with measured diagnostic values')
        refs=set(); descriptors=[]; hashes={}
        for item in native['artifacts']:
            reference=item['path']
            if reference in refs:raise ValueError('Duplicate native artifact')
            path=artifact_path(directory,reference)
            if file_hash(path)!=item['sha256']:raise ValueError('Native evidence hash mismatch')
            refs.add(reference);hashes[reference]=item['sha256'];descriptors.append({k:item[k] for k in ('path','media_type','description')})
        required={results['mesh_artifact'],results['diagnostics_artifact'],*results['field_artifacts'],
                  'artifacts/metrics.json','artifacts/input.normalized.json','artifacts/method_environment.json',
                  'artifacts/input.original.json','artifacts/input.canonical-si.json','artifacts/unit_normalization.json'}
        if payload['thermal']['enabled']:required.add('artifacts/solution/cell_transfer.npz')
        if required-refs:raise ValueError('Missing required fields/audit/transfer artifacts: '+str(required-refs))
        for name,expected in (('metrics.json',results),('diagnostics.json',diag),('input.normalized.json',payload),('input.canonical-si.json',payload)):
            if read_json(artifact_path(directory,'artifacts/'+name))!=expected:raise ValueError('Artifact content mismatch: '+name)
        electric=diag['electrical']; key='loss_power_W' if payload['analysis']=='electrothermal' else 'volume_power_W' if payload['analysis']=='ac_eqs' else 'volume_loss_W'
        if electric[key]!=results['electrical']['loss_total_W']:raise ValueError('Loss diagnostics disagree with result')
        if results['thermal']['enabled'] and diag['thermal']['Tmax_K']!=results['thermal']['maximum_temperature_K']:raise ValueError('Temperature diagnostics disagree')
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        raise ModuleError('INVALID_SCIENTIFIC_RESULT',str(exc)) from exc
    qc={'numerical':[],'scientific':[]}
    for name in NUMERICAL_CHECKS:
        if name in diag['checks']:
            qc['numerical'].append(check(name,'passed' if diag['checks'][name] else 'failed','Per-task measured check; tolerance basis is recorded in diagnostics and EXTENDED_ACCEPTANCE.md, not a product validation.'))
        elif name in ('source_transfer','thermal_balance') and not payload['thermal']['enabled']:
            qc['numerical'].append(check(name,'not_applicable','Thermal solve explicitly disabled.'))
        else:
            qc['numerical'].append(check(name,'not_checked','No independent per-task acceptance for '+name+'; raw diagnostics/experiment reference are separate evidence.'))
    for name in PHYSICAL_CHECKS:qc['scientific'].append(check(name,'not_checked','Actual device/material/model signoff not supplied; synthetic examples are not calibration.'))
    write_json(Path(directory)/'quality.json',qc); write_json(Path(directory)/'artifact_hashes.json',hashes)
    descriptors += [{'path':'artifacts/quality.json','media_type':'application/json','description':'Per-task checks; unassessed scientific items not_checked'},
                    {'path':'artifacts/artifact_hashes.json','media_type':'application/json','description':'Windows-verified native evidence hashes'}]
    return {'schema_version':'mlcc.adapter-result.v1','execution_status':'succeeded','provenance':provenance(payload,env,deployment),
            'results':results,'quality':qc,'errors':[],'warnings':native['warnings'],'limitations':LIMITATIONS,
            'artifacts':descriptors+[a for a in diagnostic_artifacts(directory) if a['path'] not in refs]}


def handle(request):
    preflight=isinstance(request,dict) and request.get('action')=='preflight'
    payload=None;directory=None;deployment=None
    try:
        keys={'schema_version','interface_version','action','module_id','operation','input','task_id','artifact_dir'}
        if not isinstance(request,dict) or set(request)!=keys or request['schema_version']!='mlcc.adapter-request.v1' or request['interface_version']!='1.0' or request['module_id']!='fem' or request['operation'] not in SUPPORTED_OPERATIONS or request['action'] not in ('preflight','execute'):
            raise ModuleError('INVALID_REQUEST','Invalid extended FEM request')
        operation=request['operation']
        kernel_operation=OPERATIONS_QUANTITIES.get(operation,operation)
        if operation in OPERATIONS_QUANTITIES:
            payload,audit=canonicalize_quantities(request['input'],operation)
        else:
            payload,audit=canonicalize(request['input'],operation)
        if preflight and (request['task_id'] is not None or request['artifact_dir'] is not None):raise ModuleError('INVALID_REQUEST','Preflight must not own task/artifact paths')
        deployment=Deployment.load(extended=True); estimate=deployment.check_resources(payload)
        if preflight:
            env=deployment.probe()
            return {'schema_version':'mlcc.adapter-preflight.v1','ready':True,'errors':[],'warnings':LIMITATIONS,
                    'checks':[check('scientific_input','passed','Scientific input/physical constraints and shared-core unit normalization validated.'),check('resource_budget','passed',f'Estimate={estimate}; actual mesh capped at {deployment.config["max_cells"]}'),check('backend_environment','passed','DOLFINx '+env['versions']['fenics-dolfinx'])]}
        if not isinstance(request['task_id'],str) or not re.fullmatch(r'task-[0-9a-f]{32}',request['task_id']):raise ModuleError('INVALID_REQUEST','Runtime-owned task required')
        directory=Path(request['artifact_dir'])
        if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():raise ModuleError('INVALID_REQUEST','Runtime-owned existing artifact directory required')
        write_json(directory/'input.original.json',request['input']);write_json(directory/'input.canonical-si.json',payload);write_json(directory/'unit_normalization.json',audit)
        native=deployment.execute(payload,directory,request['task_id'],operation=kernel_operation)
        return normalize(native,payload,directory,deployment)
    except Exception as exc:
        code=getattr(exc,'code','ADAPTER_ERROR')
        if preflight:return {'schema_version':'mlcc.adapter-preflight.v1','ready':False,'errors':[{'code':code,'message':str(exc)}],'warnings':[],'checks':[]}
        return {'schema_version':'mlcc.adapter-result.v1','execution_status':'failed' if code in ('SCIENTIFIC_STATE_UNKNOWN','SCIENTIFIC_EXECUTION_FAILED','SCIENTIFIC_LAUNCH_FAILED','INVALID_SCIENTIFIC_RESULT','ADAPTER_ERROR') else 'blocked',
                'provenance':provenance(payload),'results':{},'quality':{'numerical':[],'scientific':[]},'errors':[{'code':code,'message':str(exc)}],'warnings':[],
                'limitations':LIMITATIONS+(['WSL scientific process state UNKNOWN; no retry permitted.'] if code=='SCIENTIFIC_STATE_UNKNOWN' else []),'artifacts':diagnostic_artifacts(directory)}
