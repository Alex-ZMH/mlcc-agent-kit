"""Offline integration contracts. No SSH/Slurm/backend is contacted by tests."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mlcc import scale_tasks
from mlcc.scale_cli import main
from mlcc.site_runner import SiteConfig, SiteRunner
from mlcc.tasks import load_task, save_task


class ScaleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.site = {'ssh': {'alias': 'test-no-network'},
                     'workspace': {'local': str(self.root), 'remote_root': '/test/scale-workspace'},
                     'runner': {'selected': 'slurm', 'slurm': {}},
                     'scales': {'runtime_python': sys.executable, 'modules': {'fem': {
                         'adapter_python': sys.executable, 'deployment': {
                             'schema_version': 'fea.deployment.native.v1', 'transport': 'native_linux',
                             'python': '/missing/scientific-python', 'timeout_seconds': 90,
                             'threads': 1, 'max_cells': 50000}}}}}
        self.request = {'schema': 'mlcc.scale-task-request.v1', 'task_id': 'test-fem',
                        'resource_request': {'ntasks': 1, 'cpus_per_task': 1,
                                             'mem_mib': 512, 'time': '00:05:00'}}
        self.site_path, self.request_path = self.root/'site.json', self.root/'request.json'
        self.input = scale_tasks.COMPUTE_ROOT/'modules/fem/examples/quantities-mm.json'

    def create(self):
        self.site_path.write_text(json.dumps(self.site))
        self.request_path.write_text(json.dumps(self.request))
        return scale_tasks.create_scale_task(module_id='fem', operation='electrostatics_2d_quantities',
            input_path=self.input, site_path=self.site_path, request_path=self.request_path)

    def test_catalog_has_26_operations_and_preserves_native_contracts(self):
        result = scale_tasks.describe_scales()
        self.assertEqual(sum(len(m['operations']) for m in result['modules']), 26)
        self.assertEqual({m['id'] for m in result['modules']}, scale_tasks.MODULES)
        self.assertTrue(all(m['backend_availability'] == 'not_checked' for m in result['modules']))
        detail = scale_tasks.describe_scales('fem', 'electrostatics_2d_quantities')
        self.assertEqual(detail['input_schema']['type'], 'object')

    def test_runtime_source_and_numerical_protocol_assets_are_shipped(self):
        for path in ('modules/fem/SOURCES.json', 'modules/fem/EXTENDED_SOURCES.json',
                     'modules/phase_field/SOURCES.json', 'modules/phase_field/VECTOR_SOURCES.json',
                     'modules/phase_field/TANGENT_SOURCES.json', 'modules/rve/SOURCES.json',
                     'modules/rve/protocols/validation_protocol.json',
                     'modules/rve/protocols/numerical_protocol.json',
                     'modules/spice/SOURCES.json', 'modules/spice/UNITS_SOURCES.json',
                     'modules/spice/cases/validation.json'):
            self.assertIsInstance(json.loads((scale_tasks.COMPUTE_ROOT/path).read_text()), dict, path)

    def test_creation_is_offline_and_does_not_advance_runtime(self):
        with patch('subprocess.run', side_effect=AssertionError('Creation must not invoke any process')):
            task = self.create()
        self.assertIsNone(task['scheduler_job_id'])
        self.assertEqual(task['status'], 'defined')
        local = Path(task['local_workdir'])
        self.assertFalse((local/'payload/outputs').exists())
        self.assertEqual(task['scientific_input'], json.loads(self.input.read_text()))
        self.assertEqual(task['command'][1:3], ['-I', 'payload/run_scale.py'])
        # Namespaced runtime loading must not replace the platform's mlcc.
        import mlcc
        self.assertNotIn('/compute/', mlcc.__file__)

    def test_unknown_module_operation_and_invalid_input_rejected_before_staging(self):
        self.site_path.write_text(json.dumps(self.site)); self.request_path.write_text(json.dumps(self.request))
        bad = self.root/'bad.json'; bad.write_text('{}')
        for module, operation, input_path in [('dft', 'scf', self.input), ('fem', 'unknown', self.input),
                                              ('fem', 'electrostatics_2d_quantities', bad)]:
            with self.assertRaises(ValueError):
                scale_tasks.create_scale_task(module_id=module, operation=operation,
                    input_path=input_path, site_path=self.site_path, request_path=self.request_path)
        self.assertFalse((self.root/'tasks').exists())

    def test_duplicate_task_creation_does_not_overwrite_inputs(self):
        task = self.create()
        saved = Path(task['result_file']).parent/'scale-request.json'
        before = saved.read_bytes()
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual(before, saved.read_bytes())

    def test_bad_resources_or_path_refused_without_task(self):
        for value in ('../bad', 'a/b', ''):
            self.request['task_id'] = value
            with self.assertRaises(ValueError):
                self.create()
        self.request['task_id'] = 'test-fem'
        for key, value in [('ntasks', True), ('ntasks', 2), ('time', '00:01:00\n#SBATCH --x'), ('mem_mib', -1)]:
            old = copy.deepcopy(self.request)
            self.request['resource_request'][key] = value
            with self.assertRaises(ValueError):
                self.create()
            self.request = old
        self.assertFalse((self.root/'tasks').exists())

    def test_existing_site_runner_prepares_same_task_without_dft_rules(self):
        task_data = self.create()
        task = load_task(Path(task_data['local_workdir'])/'task.json')
        runner = SiteRunner(SiteConfig.from_mapping(self.site), execute=lambda *a, **k: self.fail('No SSH'))
        runner.prepare(task)
        script = (task.path.parent/'job.sbatch').read_text()
        self.assertIn('#SBATCH --time=00:05:00', script)
        self.assertIn('payload/run_scale.py', script)
        self.assertNotIn('wsl', script)
        self.assertIsNone(task.scheduler_job_id)

    def _blocked_execution(self):
        task_data = self.create()
        root = Path(task_data['local_workdir'])
        command = [sys.executable, '-I', str(root/'payload/run_scale.py'),
                   '--request', str(root/'scale-request.json'), '--response', str(root/'scale-response.json')]
        env = dict(os.environ, SLURM_JOB_ID='synthetic-test-job')
        process = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stderr)
        task = load_task(root/'task.json')
        task.set(scheduler_job_id=env['SLURM_JOB_ID'], scheduler_state='FAILED', exit_code='1:0')
        save_task(task)
        return root, command, env

    def test_real_protocol_failure_roundtrip_preserves_not_checked_and_original_units(self):
        root, _, _ = self._blocked_execution()
        delivery = scale_tasks.read_scale_result(root/'task.json')
        self.assertEqual(delivery['result']['execution']['status'], 'blocked')
        self.assertEqual(delivery['result']['provenance']['evidence_kind'], 'none')
        self.assertEqual(delivery['result']['quality']['scientific']['status'], 'not_checked')
        self.assertEqual(delivery['result']['input']['payload'], json.loads(self.input.read_text()))
        self.assertTrue(delivery['result']['errors'])

    def test_repeated_entry_and_result_reads_do_not_repeat_task_creation(self):
        root, command, env = self._blocked_execution()
        response = root/'scale-response.json'
        before = hashlib.sha256(response.read_bytes()).hexdigest()
        subprocess.run(command, cwd=root, env=env, capture_output=True, check=False)
        with patch('subprocess.run', side_effect=AssertionError('Result reads must stay offline')):
            scale_tasks.read_scale_result(root/'task.json')
            scale_tasks.read_scale_result(root/'task.json')
        self.assertEqual(before, hashlib.sha256(response.read_bytes()).hexdigest())
        self.assertEqual(len(list((root/'payload/outputs/tasks').iterdir())), 1)

    def test_repeated_entry_refuses_changed_scientific_input(self):
        root, command, env = self._blocked_execution()
        path = root/'scale-request.json'; request = json.loads(path.read_text())
        request['input']['material']['relative_permittivity'] = 123
        path.write_text(json.dumps(request))
        process = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('differs from the explicit scientific request', process.stderr)
        self.assertEqual(len(list((root/'payload/outputs/tasks').iterdir())), 1)

    def test_scale_continuation_never_claims_scientific_convergence(self):
        from mlcc.workflow import inspect_task
        root, _, _ = self._blocked_execution()
        task = load_task(root/'task.json')
        task.set(scheduler_state='COMPLETED', exit_code='0:0', collect_status='collected')
        save_task(task)
        decision = inspect_task(task)
        self.assertEqual(decision['action'], 'review_original_error')
        self.assertEqual(decision['quality']['scientific']['status'], 'not_checked')

    def test_command_line_catalog_is_the_same_registered_function(self):
        from contextlib import redirect_stdout
        from io import StringIO
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['describe-scale', '--module', 'spice', '--operation', 'ac_impedance']), 0)
        self.assertEqual(json.loads(output.getvalue())['module_id'], 'spice')

    def test_mismatched_saved_identity_is_not_accepted(self):
        root, _, _ = self._blocked_execution()
        path = root/'scale-response.json'; response = json.loads(path.read_text())
        for key in ('scheduler_job_id', 'platform_task_id', 'runtime_relative_dir'):
            changed = copy.deepcopy(response); changed[key] = 'unrelated'
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                scale_tasks.read_scale_result(root/'task.json')

    def test_native_entry_refuses_login_node_execution(self):
        task = self.create(); root = Path(task['local_workdir'])
        env = dict(os.environ); env.pop('SLURM_JOB_ID', None)
        result = subprocess.run([sys.executable, '-I', str(root/'payload/run_scale.py'),
            '--request', str(root/'scale-request.json'), '--response', str(root/'scale-response.json')],
            cwd=root, env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Slurm allocation', result.stderr)
        self.assertFalse((root/'payload/outputs').exists())


if __name__ == '__main__':
    unittest.main()
