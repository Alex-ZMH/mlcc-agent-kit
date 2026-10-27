"""Verify installed study/continuation/delivery functions against saved real tasks."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-root', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    bundle = args.bundle_root.resolve()
    workspace = ROOT / 'workspace'
    env = dict(os.environ, PYTHONPATH=str(bundle / 'src'))
    task_paths = [workspace / 'tasks' / f'h1-ni-{case}-v001/task.json'
                  for case in ['scf', 'relax', 'post-relax']]
    before = {path: path.read_text(encoding='utf-8') for path in task_paths}
    commands = []

    def run(name, arguments):
        command = [sys.executable, '-m', 'mlcc.cli', *map(str, arguments)]
        result = subprocess.run(command, env=env, cwd=ROOT, text=True,
                                encoding='utf-8', capture_output=True)
        (report_dir / f'{name}.stdout.json').write_text(result.stdout, encoding='utf-8')
        (report_dir / f'{name}.stderr.txt').write_text(result.stderr, encoding='utf-8')
        commands.append({'command': command, 'exit_code': result.returncode,
                         'stdout': str(report_dir / f'{name}.stdout.json'),
                         'stderr': str(report_dir / f'{name}.stderr.txt')})
        if result.returncode:
            raise RuntimeError(result.stderr)
        return json.loads(result.stdout)

    czo = run('czo-study', ['study-plan', '--study', workspace / 'configs/cases/cazro3-firing-v002.json'])
    bto = run('bto-study', ['study-plan', '--study', workspace / 'configs/cases/batio3-firing-v002.json'])
    assert czo['static_reference_conditions']['target_external_pressure_Pa'] == 101325
    assert bto['static_reference_conditions']['target_external_pressure_Pa'] is None
    assert czo['static_reference_conditions']['applied_external_pressure_Pa'] is None
    assert czo['temperature_points'][0]['temperature_K'] == 773.15
    assert bto['temperature_points'][0]['temperature_K'] == 1373.15
    plans, delivered = [], []
    for task_path in task_paths:
        task_id = task_path.parent.name
        plans.append(run(task_id + '-resume', ['resume-plan', '--task', task_path,
                     '--site', workspace / 'configs/site.v100.json']))
        delivered.append(run(task_id + '-delivery', ['deliver-result', '--task', task_path,
                         '--study', workspace / 'configs/cases/ni-engineering-v001.json',
                         '--conditions', workspace / 'configs/cases/ni-static-conditions-v001.json']))
    assert all(plan['action'] == 'completed' for plan in plans)
    assert [plan['scheduler_job_id'] for plan in plans] == ['32', '33', '34']
    assert all(result['validity_domain'] == 'engineering_fixture_only' for result in delivered)
    assert all(result['design_assessment'] == 'not_assessed' for result in delivered)
    assert all(path.read_text(encoding='utf-8') == text for path, text in before.items())
    sys.path.insert(0, str(bundle / 'src'))
    from mlcc.workflow import task_chain_snapshot
    chain = task_chain_snapshot(task_paths)
    assert all(row['model_exists'] and row['method_exists'] and row['result_exists'] for row in chain)
    (report_dir / 'ni-chain.json').write_text(json.dumps(chain, indent=2) + '\n', encoding='utf-8')
    report = {'passed': True, 'bundle_root': str(bundle), 'commands': commands,
              'historical_tasks_unchanged': True, 'new_numerical_jobs': [],
              'scope': 'study_conditions_read_only_continuation_and_saved_ABACUS_result_delivery',
              'production_qualification': False, 'source_job_ids': ['32', '33', '34']}
    (report_dir / 'acceptance.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'report': str(report_dir / 'acceptance.json')}))


if __name__ == '__main__':
    main()
