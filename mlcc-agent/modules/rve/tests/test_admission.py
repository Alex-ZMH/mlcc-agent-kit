"""Stdlib regressions for zero-GB coverage and advisory cell recommendations."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE))
from rve_module.adapter_api import handle
from rve_module.common import ModuleError
from rve_module.contract import canonicalize, geometry
from rve_module.deployment import Deployment


def fixture(gb=0, shell=.04, pore=0, h=.017):
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
    return value


class AdmissionTests(unittest.TestCase):
    def test_zero_gb_material_coverage_with_shell_and_optional_pores(self):
        for pore in (0, .02, .05):
            with self.subTest(pore=pore):
                canonical, _ = canonicalize(fixture(pore=pore), 'homogenize_electrostatics_2d')
                expected = {str(100+i) for i in range(9)} | {str(200+i) for i in range(9)}
                if pore:
                    expected.add('9000')
                self.assertEqual(set(canonical['materials']), expected)

    def test_zero_gb_without_shell_has_only_grain_materials(self):
        canonical, _ = canonicalize(fixture(shell=0), 'homogenize_electrostatics_2d')
        self.assertEqual(set(canonical['materials']), {str(100+i) for i in range(9)})

    def test_zero_gb_rejects_a_spurious_gb_material(self):
        value = fixture()
        extra = deepcopy(value['materials'][0])
        extra['region_tag'] = '3000'
        value['materials'].append(extra)
        with self.assertRaises(ModuleError) as error:
            canonicalize(value, 'homogenize_electrostatics_2d')
        self.assertEqual(error.exception.code, 'INVALID_MATERIAL')

    def test_positive_gb_below_old_minimum_is_supported_if_resolved(self):
        canonical, _ = canonicalize(fixture(gb=.009, h=.0059), 'homogenize_electrostatics_2d')
        self.assertIn('3000', canonical['materials'])

    def test_invalid_width_and_underresolved_positive_width_still_fail(self):
        for gb, code in ((-.001, 'INVALID_GEOMETRY'), (.081, 'INVALID_GEOMETRY'),
                         (.001, 'UNDER_RESOLVED_GEOMETRY')):
            value = fixture(gb=gb)
            # Exercise the relational geometry contract independently of schema bounds.
            value['geometry']['physical_lengths'] = [1., 1.]
            with self.subTest(gb=gb), self.assertRaises(ModuleError) as error:
                geometry(value['geometry'], value['normalized_h'], 2)
            self.assertEqual(error.exception.code, code)

    def test_estimate_above_legacy_recommendation_does_not_block(self):
        deployment = Deployment({'max_cells_2d': 90000, 'max_cells_3d': 180000})
        self.assertEqual(deployment.budget({'normalized_h': .005}, 2), 160000)
        self.assertTrue(deployment.budget_warnings({'normalized_h': .005}, 2))
        self.assertGreater(deployment.budget({'normalized_h': .025}, 3), 180000)
        self.assertEqual(deployment.budget_warnings({'normalized_h': .1}, 2), [])

    def test_preflight_returns_ready_with_over_recommendation_warning(self):
        deployment = Deployment({'max_cells_2d': 1, 'max_cells_3d': 1})
        request = {'schema_version': 'mlcc.adapter-request.v1', 'interface_version': '1.0',
                   'module_id': 'rve', 'operation': 'homogenize_electrostatics_2d',
                   'action': 'preflight', 'input': fixture(h=.005),
                   'task_id': None, 'artifact_dir': None}
        # This verifies admission only; real backend/mesh/solve is a separate explicit run.
        with patch.object(Deployment, 'load', return_value=deployment), \
             patch.object(Deployment, 'probe', return_value={'ready': True}):
            response = handle(request)
        self.assertTrue(response['ready'], response)
        self.assertEqual(response['errors'], [])
        self.assertTrue(any('advisory only' in w for w in response['warnings']))

    def test_refinement_floor_removed_and_thin_positive_gb_resolved(self):
        value=fixture(gb=1/420,shell=0,h=.0015)
        canonical,_=canonicalize(value,'homogenize_electrostatics_2d')
        self.assertIn('3000',canonical['materials'])
        value=json.loads((MODULE/'examples/thermal-3d-layers.json').read_text())
        value['normalized_h']=.0249
        self.assertEqual(canonicalize(value,'homogenize_thermal_3d')[0]['normalized_h'],.0249)
        for h in (0,-1):
            value=fixture(h=h)
            with self.subTest(h=h),self.assertRaises(ModuleError):canonicalize(value,'homogenize_electrostatics_2d')

    def test_extreme_refinement_estimate_is_advisory_without_float_overflow(self):
        dep=Deployment({'max_cells_2d':90000,'max_cells_3d':180000})
        for dimension in (2,3):
            self.assertIsInstance(dep.budget({'normalized_h':1e-200},dimension),int)
            self.assertTrue(dep.budget_warnings({'normalized_h':1e-200},dimension))

    @unittest.skipUnless(sys.platform == 'linux', 'native Linux deployment validation')
    def test_native_deployment_accepts_recommendations_above_old_caps(self):
        config = {'schema_version': 'rve.deployment.native.v1', 'transport': 'native_linux',
                  'python': sys.executable, 'linux_root': str(MODULE.parents[1]),
                  'timeout_seconds': 240, 'threads': 1,
                  'max_cells_2d': 1000000, 'max_cells_3d': 2000000}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'deployment.json'
            path.write_text(json.dumps(config))
            with patch.dict(os.environ, {'MLCC_RVE_DEPLOYMENT': str(path)}):
                self.assertEqual(Deployment.load().config, config)


if __name__ == '__main__':
    unittest.main()
