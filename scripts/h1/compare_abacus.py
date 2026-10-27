"""Accept the three-job Ni wiring loop; keep production qualification separate."""
import argparse
import json
from pathlib import Path
import re
import sys

import numpy as np
from ase.io import read

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / 'workspace'
sys.path.insert(0, str(ROOT / 'mlcc-agent/src'))
from mlcc.abacus import _read_stru


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    method = json.loads((WORKSPACE / 'configs/h1-abacus-method-v001.json').read_text())
    results, paths, jobs, runtimes = {}, {}, {}, {}
    for case in ['scf', 'relax', 'post-relax']:
        path = WORKSPACE / f'tasks/h1-ni-{case}-v001'
        task = json.loads((path / 'task.json').read_text())
        result = json.loads((path / 'result.json').read_text())
        assert task['scheduler_state'] == 'COMPLETED' and task['exit_code'] == '0:0'
        assert task['method_set'] == method['method_set']
        atom_map = json.loads((path / 'STRU.atom-map.json').read_text())
        native_input = _read_stru(path / 'STRU', atom_map)
        saved_input = read(path / 'input.extxyz')
        assert native_input.arrays['atom_id'].tolist() == saved_input.arrays['atom_id'].tolist()
        assert native_input.get_chemical_symbols() == saved_input.get_chemical_symbols()
        np.testing.assert_allclose(native_input.cell, saved_input.cell, rtol=0, atol=2e-8)
        np.testing.assert_allclose(native_input.positions, saved_input.positions, rtol=0, atol=2e-8)
        results[case], paths[case], jobs[case] = result, path, task['scheduler_job_id']
        runtimes[case] = task['resources']['RunTime']
    base, relax, post = (results[name] for name in ['scf', 'relax', 'post-relax'])
    atoms = read(paths['scf'] / 'input.extxyz')
    relax_input = read(paths['relax'] / 'input.extxyz')
    relaxed = read(paths['relax'] / 'final.extxyz')
    post_input = read(paths['post-relax'] / 'input.extxyz')
    assert relaxed.get_chemical_symbols() == atoms.get_chemical_symbols()
    assert relaxed.arrays['atom_id'].tolist() == atoms.arrays['atom_id'].tolist()
    assert all(r['atom_ids'] == atoms.arrays['atom_id'].tolist() for r in results.values())
    for actual, expected in [(relax_input, atoms), (post_input, relaxed)]:
        assert actual.get_chemical_symbols() == expected.get_chemical_symbols()
        assert actual.arrays['atom_id'].tolist() == expected.arrays['atom_id'].tolist()
        np.testing.assert_allclose(actual.cell, expected.cell, rtol=0, atol=2e-8)
        np.testing.assert_allclose(actual.positions, expected.positions, rtol=0, atol=2e-8)
    np.testing.assert_allclose(relaxed.cell, atoms.cell, rtol=0, atol=2e-8)
    thresholds = method['predeclared_engineering_thresholds']
    checks = {
        'all_electronic_converged': all(r['electronic_converged'] is True for r in results.values()),
        'ionic_converged': relax['ionic_converged'] is True,
        'relax_max_force': relax['max_force_eV_per_A'] < thresholds['relax_max_force_eV_per_A'],
        'post_max_force': post['max_force_eV_per_A'] < thresholds['post_relax_max_force_eV_per_A'],
        'relaxation_lowers_same_method_energy': relax['energy_eV'] < base['energy_eV'],
        'source_atom_mapping_and_exact_relax_to_scf_lineage': True,
        'native_STRU_matches_recorded_inputs': True,
    }
    vasp_dir = WORKSPACE / 'tasks/h0-ni-cutoff500-v004'
    vasp = json.loads((vasp_dir / 'result.json').read_text())
    assert vasp['atom_ids'] == base['atom_ids']
    vasp_input = read(vasp_dir / 'POSCAR')
    np.testing.assert_allclose(vasp_input.cell, atoms.cell, rtol=0, atol=1e-10)
    np.testing.assert_allclose(vasp_input.positions, atoms.positions, rtol=0, atol=1e-10)
    vasp_total_mag = float(re.findall(r'number of electron\s+[\d.]+\s+magnetization\s+([\d.+-]+)', (vasp_dir / 'OUTCAR').read_text())[-1])
    vasp_relax_dir = WORKSPACE / 'tasks/h0-ni-relax-v005'
    vasp_relaxed = read(vasp_relax_dir / 'CONTCAR')
    delta = relaxed.get_scaled_positions() - vasp_relaxed.get_scaled_positions()
    delta -= np.rint(delta)
    cross = {
        'same_initial_geometry': True,
        'absolute_total_energies_compared': False,
        'max_force_component_difference_eV_per_A': float(np.max(np.abs(np.array(base['forces_eV_per_A'])-vasp['forces_eV_per_A']))),
        'abacus_total_magnetization_muB': base['total_magnetization_muB'],
        'vasp_total_magnetization_muB': vasp_total_mag,
        'vasp_magnetization_source': str(vasp_dir / 'OUTCAR'),
        'independent_relaxation_max_periodic_atom_distance_A': float(np.linalg.norm(delta @ atoms.cell.array,axis=1).max()),
        'abacus_printed_stress_GPa': base['stress_GPa'],
        'vasp_compression_positive_stress_GPa': vasp['stress_vasp_compression_positive_GPa'],
        'stress_sign_calibration': 'pending_ABACUS_finite_strain_test',
        'production_equivalence_claim': False,
        'reason': 'PAW 10e versus ONCV 18e; cutoff and finite-strain calibration remain pending.',
    }
    report = {
        'scope': 'Ni_fixed_cell_three_job_engineering_loop_only',
        'method_set': method['method_set'], 'passed': all(checks.values()), 'checks': checks,
        'thresholds': {k: thresholds[k] for k in ['relax_max_force_eV_per_A','post_relax_max_force_eV_per_A']},
        'relax_max_force_eV_per_A': relax['max_force_eV_per_A'],
        'post_max_force_eV_per_A': post['max_force_eV_per_A'],
        'relax_energy_change_eV': relax['energy_eV']-base['energy_eV'],
        'post_minus_relax_energy_eV': post['energy_eV']-relax['energy_eV'],
        'energy_definition': 'ABACUS finite-smearing E_KohnSham, same method only',
        'cross_engine': cross, 'job_ids': jobs, 'runtimes': runtimes,
        'result_files': {k:str(v/'result.json') for k,v in paths.items()},
        'production_qualification': False, 'production_engine_switch': False,
        'remaining': ['100_vs_120_Ry_cutoff', 'finite_strain_stress_calibration', 'production_material_method_and_capability_qualification'],
    }
    args.report.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'passed': report['passed'], 'checks': checks, 'report':str(args.report)}))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
