"""Public architecture contracts; no backend or scheduler is invoked."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mlcc.capabilities import ROOT, describe
from mlcc.task_service import create_task
from mlcc.workflow import task_chain_snapshot
from mlcc.tasks import TaskRecord, save_task

class UnifiedArchitectureTests(unittest.TestCase):
    def test_six_peer_modules_discovered_without_scientific_imports(self):
        with patch('subprocess.run',side_effect=AssertionError('Discovery must be offline')):
            rows=describe()['modules']
        self.assertEqual({m['id'] for m in rows},{'dft','md','phase_field','rve','fem','spice'})
        self.assertFalse((ROOT/'compute/bootstrap.py').exists())
        self.assertFalse((ROOT/'src/mlcc/runtime.py').exists())
        self.assertFalse((ROOT/'src/mlcc/store.py').exists())

    def test_primary_cli_catalog_does_not_load_scientific_dependencies(self):
        import subprocess, sys
        code='from mlcc.cli import main;main(["list-capabilities"]);import sys;assert "numpy" not in sys.modules;assert "ase" not in sys.modules'
        process=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(len(json.loads(process.stdout)['modules']),6)

    def test_native_domain_factories_are_selected_without_rewriting_arguments(self):
        for module,provider,function in [('dft','abacus_tasks','create_abacus_task'),('md','lammps_tasks','create_lammps_task')]:
            class Factory: pass
            factory=Factory()
            arguments={'study_path':'explicit-study','model_path':'explicit-model'}
            setattr(factory,function,lambda **kw:kw)
            with patch('mlcc.task_service.importlib.import_module',return_value=factory) as load:
                self.assertEqual(create_task(module,'create',**arguments),arguments)
                load.assert_called_once_with('mlcc.'+provider)

    def test_unknown_operations_do_not_import_a_provider(self):
        with patch('mlcc.task_service.importlib.import_module',side_effect=AssertionError('Must refuse before import')):
            with self.assertRaises(ValueError):create_task('fem','not-an-operation')
            with self.assertRaises(ValueError):create_task('md','not-an-operation')

    def test_non_atomic_task_chain_has_no_required_atom_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'tasks'/'fem-independent';root.mkdir(parents=True)
            task=TaskRecord({'task_id':'fem-independent','module_id':'fem','operation':'electrostatics_2d',
                'engine':'dolfinx','execution_protocol':'mlcc.adapter.v1','status':'defined',
                'scheduler_job_id':None},root/'task.json')
            save_task(task)
            before=task.path.read_bytes()
            row=task_chain_snapshot([task.path])[0]
            self.assertIsNone(row['model_id']);self.assertIsNone(row['model_path'])
            self.assertEqual(row['module_id'],'fem')
            self.assertEqual(before,task.path.read_bytes())

    def test_saved_bridge_results_stay_readable(self):
        from mlcc.legacy_scale_results import read_scale_result
        # Optional local historical evidence; not a condition for source-only installation.
        history=ROOT.parents[1]/'server-scale-validation/tasks/fem-quantity-01/task.json'
        if not history.exists(): self.skipTest('Historical bridge evidence not part of this checkout')
        before=history.read_bytes()
        result=read_scale_result(history)
        self.assertEqual(result['result']['execution']['status'],'succeeded')
        self.assertEqual(before,history.read_bytes())

if __name__=='__main__':unittest.main()
