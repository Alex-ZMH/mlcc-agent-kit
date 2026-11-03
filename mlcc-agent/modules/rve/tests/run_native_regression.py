"""Explicit real RVE regression. Run in the selected scientific Python with --execute.

Stages isolated payloads and calls the real public Adapter, native science entry,
Gmsh, FEM and independent field readback. Never submits a scheduler job.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

MODULE = Path(__file__).resolve().parents[1]
BUNDLE = MODULE.parents[1]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def fixture(gb=0, shell=.04, pore=0, h=.017, uniform=False):
    value = json.loads((MODULE/'examples/electrostatics-2d-polycrystal.json').read_text())
    value['geometry'].update(normalized_gb_width=gb, normalized_shell=shell, pore_fraction=pore)
    value['normalized_h'] = h
    value['materials'] = [m for m in value['materials']
                          if (m['region_tag'] != '3000' or gb > 0)
                          and (not m['region_tag'].startswith('20') or shell > 0)]
    if pore:
        material = deepcopy(value['materials'][0])
        material['region_tag'] = '9000'
        material['scalar']['value'] = 1
        value['materials'].append(material)
    if uniform:
        for material in value['materials']:
            material['scalar']['value'] = 7
            material['scalar']['source'] = {'kind': 'synthetic_test',
                'reference': 'Uniform epsilon_r=7 exact tensor fixture across all grain identities'}
    return value


def run_case(output, name, raw, operation, recommended, expected_uniform=False):
    case = output/name
    case.mkdir(parents=True, exist_ok=False)
    payload = case/'payload'
    for rel in ('src/mlcc/units.py', 'scientific_core', 'modules/rve'):
        source, target = BUNDLE/rel, payload/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'tests'))
        else:
            shutil.copy2(source, target)
    artifacts = case/'artifacts'
    artifacts.mkdir()
    deployment = {'schema_version': 'rve.deployment.native.v1', 'transport': 'native_linux',
                  'python': sys.executable, 'linux_root': str(case), 'timeout_seconds': 240,
                  'threads': 1, 'max_cells_2d': recommended, 'max_cells_3d': recommended}
    write(case/'deployment.json', deployment)
    env = dict(os.environ, MLCC_RVE_DEPLOYMENT=str(case/'deployment.json'),
               PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
               MKL_NUM_THREADS='1')
    request = {'schema_version': 'mlcc.adapter-request.v1', 'interface_version': '1.0',
               'module_id': 'rve', 'operation': operation, 'action': 'preflight',
               'input': raw, 'task_id': None, 'artifact_dir': None}
    write(case/'preflight-request.json', request)
    command = [sys.executable, '-I', '-B', str(payload/'modules/rve/adapter.py')]
    start = time.monotonic()
    def invoke(req, label, timeout):
        result = subprocess.run(command, input=json.dumps(req), capture_output=True,
                                text=True, env=env, timeout=timeout)
        (case/(label+'-stderr.log')).write_text(result.stderr)
        response = json.loads(result.stdout)
        write(case/(label+'-response.json'), response)
        return response
    preflight = invoke(request, 'preflight', 30)
    if not preflight.get('ready'):
        raise RuntimeError(f'{name} preflight failed: {preflight}')
    request.update(action='execute', task_id=name, artifact_dir=str(artifacts))
    write(case/'execute-request.json', request)
    response = invoke(request, 'execute', 270)
    if response.get('execution_status') != 'succeeded':
        raise RuntimeError(f'{name} execution failed: {response.get("errors")}')
    effective = json.loads((artifacts/'effective_material.json').read_text())
    diagnostics = json.loads((artifacts/'diagnostics.json').read_text())
    readback = json.loads((artifacts/'readback.json').read_text())
    if set(effective['region_mapping']) != {m['region_tag'] for m in raw['materials']}:
        raise AssertionError('Result region/material coverage drift')
    if raw['geometry']['kind'] == 'polycrystal' and raw['geometry']['normalized_gb_width'] == 0:
        if '3000' in effective['region_mapping']:
            raise AssertionError('Spurious grain-boundary region')
    if not all(row['status'] == 'PASS' and all(v is True for v in row['checks'].values())
               for row in readback.values()):
        raise AssertionError('Independent field readback failed')
    if expected_uniform:
        import numpy as np
        eps0 = 8.8541878128e-12
        error = float(np.max(np.abs(np.array(effective['tensor'])/eps0 - np.eye(len(effective['tensor']))*7)))
        # Reuse the existing analytical tensor protocol tolerance.
        protocol = json.loads((MODULE/'protocols/numerical_protocol.json').read_text())
        tolerance = protocol['analytic_tensor']
        if error > tolerance:
            raise AssertionError(f'Uniform tensor error {error}')
    else:
        error = None
    summary = {'name': name, 'operation': operation, 'execution_status': 'succeeded',
               'cells': response['results']['cells'], 'tensor': effective['tensor'],
               'regions': sorted(effective['region_mapping']),
               'mesh_advisory': diagnostics['mesh']['cell_count_recommendation'],
               'verification': diagnostics['verification'], 'readback': readback,
               'uniform_tensor_absolute_error_in_epsilon_r': error,
               'preflight_warnings': preflight['warnings'], 'warnings': response['warnings'],
               'seconds': time.monotonic()-start,
               'material_calibration': 'not_checked', 'mesh_convergence': 'not_checked',
               'statistical_representativity': 'not_checked'}
    write(case/'summary.json', summary)
    print(json.dumps({k: summary[k] for k in ('name', 'cells', 'seconds', 'mesh_advisory')}) , flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage1-input', type=Path)
    parser.add_argument('--case', action='append')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = [
        ('zero-gb-shell-pore0', fixture(), 'homogenize_electrostatics_2d', 1, False),
        ('zero-gb-shell-pore2', fixture(pore=.02), 'homogenize_electrostatics_2d', 1, False),
        ('zero-gb-shell-pore5', fixture(pore=.05), 'homogenize_electrostatics_2d', 1, False),
        ('zero-gb-no-shell-uniform', fixture(shell=0, uniform=True), 'homogenize_electrostatics_2d', 1, True),
        ('zero-gb-no-shell-pore2', fixture(shell=0, pore=.02), 'homogenize_electrostatics_2d', 1, False),
        ('thin-positive-gb', fixture(gb=.009, h=.0059), 'homogenize_electrostatics_2d', 90000, False),
        ('positive-gb-regression', fixture(gb=.04), 'homogenize_electrostatics_2d', 90000, False),
        ('three-dimensional-soft-count', json.loads((MODULE/'examples/thermal-3d-layers.json').read_text()), 'homogenize_thermal_3d', 1, False),
        ('above-old-deployment-cap', fixture(), 'homogenize_electrostatics_2d', 2000000, False),
    ]
    thermal = fixture(pore=.02)
    thermal['schema_version'] = 'rve.thermal-2d-input.v1'
    for material in thermal['materials']:
        material['scalar']['unit'] = 'W/(m K)'
        material['scalar']['source'] = {'kind': 'synthetic_test',
            'reference': 'Explicit synthetic conductivity fixture for zero-GB thermal regression'}
    cases.append(('zero-gb-thermal-2d', thermal, 'homogenize_thermal_2d', 1, False))
    cases.append(('three-dimensional-electrostatic',
                  json.loads((MODULE/'examples/electrostatics-3d-layers.json').read_text()),
                  'homogenize_electrostatics_3d', 2000000, False))
    fine2d=fixture(shell=0,uniform=True,h=.0029)
    fine2d['geometry']={k:v for k,v in fine2d['geometry'].items() if k in ('kind','physical_lengths','pore_fraction')}
    fine2d['geometry']['kind']='homogeneous'
    fine2d['materials']=[fine2d['materials'][0]];fine2d['materials'][0]['region_tag']='10'
    cases.append(('below-old-h-floor-2d',fine2d,'homogenize_electrostatics_2d',90000,True))
    fine3d=json.loads((MODULE/'examples/electrostatics-3d-layers.json').read_text())
    fine3d['geometry']={k:v for k,v in fine3d['geometry'].items() if k in ('kind','physical_lengths','pore_fraction')}
    fine3d['geometry']['kind']='homogeneous';fine3d['materials']=[fine3d['materials'][0]]
    fine3d['materials'][0]['scalar']['value']=7;fine3d['normalized_h']=.0249
    cases.append(('below-old-h-floor-3d',fine3d,'homogenize_electrostatics_3d',180000,True))
    if args.stage1_input:
        cases.append(('stage1-zero-gb-h005', json.loads(args.stage1_input.read_text()),
                      'homogenize_electrostatics_2d', 90000, False))
    selected = set(args.case or [c[0] for c in cases])
    unknown = selected - {c[0] for c in cases}
    if unknown:
        parser.error(f'Unknown cases: {sorted(unknown)}')
    report = {'cases': [], 'python': sys.executable, 'source_bundle': str(BUNDLE)}
    try:
        for name, raw, operation, recommended, uniform in cases:
            if name in selected:
                report['cases'].append(run_case(output, name, raw, operation, recommended, uniform))
    finally:
        write(output/'summary.json', report)


if __name__ == '__main__':
    main()
