"""Software mathematical reference for the BoltzTraP2 transport adapter.

This is the analytic isotropic-parabolic example from the fixed BoltzTraP2
26.3.1 source tree, not an ABACUS sample and not a material qualification
test.  Source: https://files.pythonhosted.org/packages/c4/4a/c488bce34a8486645405c114a1884d9bbb6563f56ff7eed7eee099977ad6/boltztrap2-26.3.1.tar.gz,
``examples/parabolic.py`` and ``BoltzTraP2/units.py``.  See G. K. H. Madsen
et al., *Comput. Phys. Commun.* 231 (2018) 140-145, "BoltzTraP2".
"""

from __future__ import annotations

import json

import numpy as np
from scipy.special import expit

from BoltzTraP2 import bandlib
from BoltzTraP2.units import BOLTZMANN, BOLTZMANN_SI, a0_SI, me_SI, qe_SI


def test_isotropic_parabolic_transport_reference(tmp_path, record_property) -> None:
    """Check the direct fermi-integral/Onsager call chain and SI units."""

    epsilon = np.linspace(0.0, 1.0, 20_001)  # Hartree, as in the example.
    mass = 1.0
    dos = (2.0 * mass) ** 1.5 * np.sqrt(epsilon) / (4.0 * np.pi**2)
    transport = np.sqrt(2.0 * mass) * epsilon**1.5 / (3.0 * np.pi**2)
    vvdos = np.zeros((3, 3, epsilon.size))
    for axis in range(3):
        vvdos[axis, axis] = transport

    temperature = np.array([300.0])
    chemical_potential = np.array([0.02])
    n, l0, l1, l2, _ = bandlib.fermiintegrals(
        epsilon, dos, vvdos, mur=chemical_potential, Tr=temperature, dosweight=2.0
    )
    sigma, seebeck, kappa, _ = bandlib.calc_Onsager_coefficients(
        l0, l1, l2, chemical_potential, temperature, 1.0
    )

    # Independent carrier integral: one a0^3 cell, two spin states.
    occupation = expit(-(epsilon - chemical_potential[0]) / (BOLTZMANN * temperature[0]))
    n_si = 2.0 * np.trapezoid(dos * occupation, epsilon) / a0_SI**3
    drude_sigma_over_tau = n_si * qe_SI**2 / me_SI
    sigma_scalar = np.trace(sigma[0, 0]) / 3.0
    seebeck_scalar = np.trace(seebeck[0, 0]) / 3.0
    kappa_scalar = np.trace(kappa[0, 0]) / 3.0
    sigma_relative_error = abs(sigma_scalar - drude_sigma_over_tau) / abs(
        drude_sigma_over_tau
    )
    lorenz = kappa_scalar / (sigma_scalar * temperature[0])
    sommerfeld = np.pi**2 / 3.0 * (BOLTZMANN_SI / qe_SI) ** 2
    lorenz_relative_error = abs(lorenz - sommerfeld) / abs(sommerfeld)
    evidence = {
        "evidence_kind": "software_mathematical_reference",
        "temperature_K": float(temperature[0]),
        "chemical_potential_Ha": float(chemical_potential[0]),
        "sigma_over_tau_actual_S_m_s": float(sigma_scalar),
        "sigma_over_tau_drude_reference_S_m_s": float(drude_sigma_over_tau),
        "sigma_over_tau_relative_error": float(sigma_relative_error),
        "seebeck_actual_V_K": float(seebeck_scalar),
        "lorenz_actual_W_ohm_K2": float(lorenz),
        "lorenz_sommerfeld_reference_W_ohm_K2": float(sommerfeld),
        "lorenz_relative_error": float(lorenz_relative_error),
    }
    evidence_path = tmp_path / "parabolic-reference.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    for key, value in evidence.items():
        record_property(key, value)
    record_property("evidence_file", str(evidence_path))

    # The analytic transport DOS is isotropic and includes no scattering time.
    np.testing.assert_allclose(sigma_scalar, drude_sigma_over_tau, rtol=0.01)
    assert seebeck_scalar < 0.0  # electron-like band convention
    np.testing.assert_allclose(lorenz, sommerfeld, rtol=0.01)

    # For a tensor, PF/tau is S.T @ (sigma/tau) @ S; this case is diagonal.
    pf_tau = seebeck[0, 0].T @ sigma[0, 0] @ seebeck[0, 0]
    np.testing.assert_allclose(pf_tau, np.diag(np.diag(pf_tau)), rtol=1.0e-10, atol=1.0e-30)
    assert n[0, 0] < 0.0  # BoltzTraP2's electron-count convention.
