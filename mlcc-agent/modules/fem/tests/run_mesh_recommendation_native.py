"""Explicit --execute regression through the real Adapter and science entry."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

MODULE = Path(__file__).resolve().parents[1]
BUNDLE = MODULE.parents[1]
CASES = {
    'electrostatics_2d': 'normal.json',
    'electrostatics_2d_quantities': 'quantities-si.json',
    **{name+suffix: name.replace('_2d', '')+('-quantities' if suffix else '')+'.json'
       for name in ('electrothermal_2d', 'ac_eqs_2d', 'electromagnetic_2d')
       for suffix in ('', '_quantities')},
}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def run_case(output, name, operation, filename, recommended, fine=False):
    case = output/name
    case.mkdir(parents=True, exist_ok=False)
    payload = case/'payload'
    for rel in ('src/mlcc/units.py', 'scientific_core', 'modules/fem'):
        source, target = BUNDLE/rel, payload/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'tests'))
        else:
            shutil.copy2(source, target)
    raw = json.loads((MODULE/'examples'/filename).read_text())
    raw['outputs']['field_images'] = False
    if fine:
        raw['mesh']['target_size_m'] = 1e-6
    extended = not operation.startswith('electrostatics')
    deployment = {'schema_version': 'fem.deployment.native.v1' if extended else 'fea.deployment.native.v1',
                  'transport': 'native_linux', 'python': sys.executable, 'linux_root': str(case),
                  'timeout_seconds': 240 if extended else 120, 'threads': 1, 'max_cells': recommended}
    if extended:
        deployment['profile'] = 'device_extended_v1'
    write(case/'deployment.json', deployment)
    env = dict(os.environ, MLCC_FEA_DEPLOYMENT=str(case/'deployment.json'),
               PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    request = {'schema_version': 'mlcc.adapter-request.v1', 'interface_version': '1.0',
               'module_id': 'fem', 'operation': operation, 'action': 'preflight',
               'input': raw, 'task_id': None, 'artifact_dir': None}
    command = [sys.executable, '-B', str(payload/'modules/fem/adapter.py')]
    def invoke(label):
        write(case/(label+'-request.json'), request)
        result = subprocess.run(command, input=json.dumps(request), capture_output=True,
                                text=True, env=env, timeout=280)
        (case/(label+'-stderr.log')).write_text(result.stderr)
        response = json.loads(result.stdout)
        write(case/(label+'-response.json'), response)
        return response
    start = time.monotonic()
    preflight = invoke('preflight')
    assert preflight.get('ready'), preflight
    artifacts = case/'artifacts'
    artifacts.mkdir()
    request.update(action='execute', task_id=name, artifact_dir=str(artifacts))
    result = invoke('execute')
    assert result.get('execution_status') == 'succeeded', result.get('errors')
    diagnostics = json.loads((artifacts/'diagnostics.json').read_text())
    advisory = diagnostics['cell_count_recommendation']
    assert advisory['actual_cells'] == result['results']['mesh_cells']
    assert not advisory['enforced']
    if fine:
        assert advisory['actual_cells'] > recommended, advisory
    if advisory['exceeded']:
        assert any('Actual mesh cells=' in w for w in result['warnings']), result['warnings']
    # Existing numerical checks retain their original statuses/tolerances.
    quality = result['quality']
    assert not any(row['status'] == 'failed' for row in quality['numerical']), quality
    summary = {'name': name, 'operation': operation, 'execution': 'succeeded',
               'mesh_advisory': advisory, 'numerical': quality['numerical'],
               'scientific': quality['scientific'], 'warnings': result['warnings'],
               'seconds': time.monotonic()-start}
    write(case/'summary.json', summary)
    print(json.dumps({k: summary[k] for k in ('name', 'mesh_advisory', 'seconds')}), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', action='append')
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    cases = [(op, op, filename, 1, False) for op, filename in CASES.items()]
    cases += [('electrostatics-above-old-cap', 'electrostatics_2d', 'normal.json', 50000, True),
              ('electrothermal-above-old-cap', 'electrothermal_2d', 'electrothermal.json', 150000, True),
              ('electromagnetic-above-old-cap', 'electromagnetic_2d', 'electromagnetic.json', 150000, True),
              ('large-recommendation', 'electrostatics_2d', 'normal.json', 2000000, False)]
    selected = set(args.case or [c[0] for c in cases])
    assert selected <= {c[0] for c in cases}
    report = {'cases': [], 'python': sys.executable}
    try:
        for name, op, filename, recommended, fine in cases:
            if name in selected:
                report['cases'].append(run_case(args.output, name, op, filename, recommended, fine))
    finally:
        write(args.output/'summary.json', report)


if __name__ == '__main__':
    main()
