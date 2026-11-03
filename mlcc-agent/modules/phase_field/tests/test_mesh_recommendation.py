"""Stdlib admission regressions; backend probes here are explicitly mocked."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE))
from phasefield.adapter_api import handle
from phasefield.common import ModuleError
from phasefield.deployment import Deployment
from phasefield.resources import actual_report, estimate, planning_report
from phasefield.vector_input import prepare as vector_prepare
from phasefield.tangent_input import prepare as tangent_prepare
from phasefield.validation import validate_input

CASES={
    'steady':'steady_2d.json','evolve':'evolve_2d.json',
    'steady_si':'steady_si_2d.json','evolve_si':'evolve_si_2d.json',
    'vector_steady':'vector-uniform-2d.json','vector_evolve':'vector-uniform-2d.json',
    'vector_steady_si':'vector-uniform-2d-si.json','vector_evolve_si':'vector-uniform-2d-si.json',
    'dielectric_tangent':'tangent-cross-2d.json','dielectric_tangent_si':'tangent-cross-2d-si.json',
}


def example(operation):
    p=json.loads((MODULE/'examples'/CASES[operation]).read_text(encoding='utf-8'))
    p['operation']=operation
    return p


class MeshRecommendationTests(unittest.TestCase):
    def test_all_ten_operations_warn_without_resource_rejection(self):
        dep=Deployment({'max_cells':1,'max_work':1,'max_history_bytes':1})
        for op in CASES:
            request={'schema_version':'mlcc.adapter-request.v1','interface_version':'1.0',
                     'module_id':'phase_field','operation':op,'action':'preflight',
                     'input':example(op),'task_id':None,'artifact_dir':None}
            with self.subTest(operation=op), patch.object(Deployment,'load',return_value=dep), \
                 patch.object(Deployment,'probe',return_value={'ready':True}):
                response=handle(request)
                self.assertTrue(response.get('ready'),response)
                self.assertEqual(response['errors'],[])
                self.assertTrue(any('advisory only' in x for x in response['warnings']),response)

    def test_scalar_all_axes_above_legacy_limits(self):
        for op in ('steady','evolve'):
            p=example(op);p['dimension']=3;p['mesh']={'nx':49,'ny':13,'nz':13}
            self.assertEqual(validate_input(p,op),p)
            report=planning_report(p,{'max_cells':6000,'max_work':1,'max_history_bytes':1})
            self.assertFalse(report['enforced'])
            self.assertTrue({'axis_cells[0]','axis_cells[1]','axis_cells[2]','cells','work','history_bytes'}<=set(report['exceeded']))

    def test_vector_dofs_and_per_axis_counts_have_no_cap(self):
        for op in ('vector_steady','vector_evolve','vector_steady_si','vector_evolve_si'):
            p=example(op);p['cells']=[25001,1]
            reduced,context=vector_prepare(p,op)
            self.assertGreater(estimate(reduced,context)['dofs'],25000)

    def test_tangent_dofs_and_per_axis_counts_have_no_cap(self):
        for op in ('dielectric_tangent','dielectric_tangent_si'):
            p=example(op);p['cells']=[129,16]
            reduced,context=tangent_prepare(p,op)
            report=planning_report(reduced,{'max_cells':1,'max_work':1,'max_history_bytes':1},context)
            self.assertGreater(report['estimates']['dofs'],3300)
            self.assertIn('dense_stability_matrix_bytes',report['estimates'])
            self.assertTrue({'dofs','axis_cells[0]'}<=set(report['exceeded']))

    def test_actual_mesh_report_never_enforces_count(self):
        p=example('dielectric_tangent');p['cells']=[129,16]
        report=actual_report(p,6000,4128,6630)
        self.assertFalse(report['enforced'])
        self.assertIn('dofs',report['exceeded'])
        self.assertIn('axis_cells[0]',report['exceeded'])
        with self.assertRaises(ModuleError):actual_report(p,6000,0,0)

    def test_physical_and_resolution_guards_remain(self):
        p=example('vector_steady');p['parameters']['g']=0
        with self.assertRaises(ModuleError):vector_prepare(p,'vector_steady')
        p=example('vector_steady');p['initial_condition']={'kind':'wall_180','width_factor':1.}
        with self.assertRaises(ModuleError):vector_prepare(p,'vector_steady')
        p=example('dielectric_tangent');p['parameters']['c']=.1
        with self.assertRaises(ModuleError):tangent_prepare(p,'dielectric_tangent')


if __name__=='__main__':unittest.main()
