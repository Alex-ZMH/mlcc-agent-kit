"""Stdlib regressions; no numerical solver is started by these tests."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE))
from device_fem.adapter_api import handle
from device_fem.common import ModuleError, cell_count_recommendation
from device_fem.deployment import Deployment
from device_fem.validation import validate_input

CASES = {
    'electrostatics_2d': 'normal.json',
    'electrostatics_2d_quantities': 'quantities-si.json',
    **{name+suffix: name.replace('_2d', '')+('-quantities' if suffix else '')+'.json'
       for name in ('electrothermal_2d', 'ac_eqs_2d', 'electromagnetic_2d')
       for suffix in ('', '_quantities')},
}


class MeshRecommendationTests(unittest.TestCase):
    def test_all_eight_operation_preflights_warn_instead_of_blocking(self):
        deployment = Deployment({'max_cells': 1})
        for operation, filename in CASES.items():
            payload = json.loads((MODULE/'examples'/filename).read_text())
            request = {'schema_version': 'mlcc.adapter-request.v1', 'interface_version': '1.0',
                       'module_id': 'fem', 'operation': operation, 'action': 'preflight',
                       'input': payload, 'task_id': None, 'artifact_dir': None}
            with self.subTest(operation=operation), \
                 patch.object(Deployment, 'load', return_value=deployment), \
                 patch.object(Deployment, 'probe', return_value={'ready': True, 'versions': {'fenics-dolfinx': '0.11.0'}}):
                result = handle(request)
                self.assertTrue(result.get('ready'), result)
                self.assertEqual(result['errors'], [])
                self.assertTrue(any('advisory only' in w for w in result['warnings']))

    def test_fine_mesh_estimate_above_old_50000_limit_is_allowed(self):
        payload = json.loads((MODULE/'examples/normal.json').read_text())
        payload['mesh']['target_size_m'] = 1e-6
        deployment = Deployment({'max_cells': 50000})
        self.assertGreater(deployment.check_resources(payload), 50000)
        self.assertTrue(deployment.resource_warnings(payload))

    def test_actual_count_recommendation_has_no_enforcement(self):
        for count, recommended in ((60000, 50000), (180000, 150000), (20, 1)):
            with self.subTest(count=count):
                value = cell_count_recommendation(count, recommended)
                self.assertTrue(value['exceeded'])
                self.assertFalse(value['enforced'])
        self.assertFalse(cell_count_recommendation(100, 100)['exceeded'])

    def test_geometric_and_material_checks_remain(self):
        for field in ('geometry', 'material'):
            payload = json.loads((MODULE/'examples/normal.json').read_text())
            if field == 'geometry':
                payload['geometry']['body_length_m'] *= 2
            else:
                payload['material']['relative_permittivity'] = 0
            with self.subTest(field=field), self.assertRaises(ModuleError):
                validate_input(payload)

    @unittest.skipUnless(sys.platform == 'linux', 'native deployment validation')
    def test_both_deployment_profiles_accept_large_recommendations(self):
        for extended in (False, True):
            value = {'schema_version': 'fem.deployment.native.v1' if extended else 'fea.deployment.native.v1',
                     'transport': 'native_linux', 'python': sys.executable,
                     'linux_root': str(MODULE.parents[1]), 'timeout_seconds': 90,
                     'threads': 1, 'max_cells': 2000000}
            if extended:
                value['profile'] = 'device_extended_v1'
            with self.subTest(extended=extended), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'deployment.json'
                path.write_text(json.dumps(value))
                with patch.dict(os.environ, {'MLCC_FEA_DEPLOYMENT': str(path)}):
                    self.assertEqual(Deployment.load(extended=extended).config, value)


if __name__ == '__main__':
    unittest.main()
