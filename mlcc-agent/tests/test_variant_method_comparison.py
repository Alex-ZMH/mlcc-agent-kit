from __future__ import annotations

from mlcc.defect_thermodynamics import compare_variant_method_records


def _method(*, elements: list[str], nbands: int, valence: int, method_set: str = "variant") -> dict:
    pseudopotentials = {
        element: {"source": f"/pp/{element}.upf", "filename": f"{element}.upf"}
        for element in elements
    }
    return {
        "schema": "mlcc.method.v1",
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "stage": "scf",
        "basis_type": "pw",
        "dft_functional": "PBE",
        "ks_solver": "cg",
        "nspin": 1,
        "lspinorb": False,
        "noncolin": False,
        "initial_moments_muB_by_element": {element: 0 for element in elements},
        "occupations": "fixed",
        "smearing_method": None,
        "mixing_type": "broyden",
        "relax_method": "cg",
        "symmetry": 0,
        "net_charge": 0,
        "nelec": 0,
        "nelec_delta": 0,
        "charge_convention": "positive q removes q electrons",
        "element_order": elements,
        "kpoints": [2, 2, 2],
        "kpoint_rule": "explicit_mesh",
        "parameters": {
            "ecutwfc_Ry": 100,
            "scf_thr": 1e-11,
            "scf_nmax": 200,
            "nbands": nbands,
            "smearing_sigma_Ry": None,
            "mixing_beta": 0.3,
            "force_thr_eV_per_A": None,
            "relax_nmax": None,
        },
        "pseudopotentials": pseudopotentials,
        "pseudopotential_ids": {element: f"{element}_PBE" for element in elements},
        "pseudopotential_treatment": {element: "scalar" for element in elements},
        "pseudopotential_metadata": {
            element: {
                "element": element,
                "functional": "PBE",
                "valence_electrons_per_atom": 4,
                "relativity": "scalar",
                "has_spin_orbit": False,
                "type": "ONCV_NC",
            }
            for element in elements
        },
        "electron_count": {"neutral_valence_electrons": valence},
        "method_set": method_set,
    }


def _configuration_method(*, elements: list[str], nbands: int, method_set: str) -> dict:
    native = _method(elements=elements, nbands=nbands, valence=16, method_set=method_set)
    return {
        "engine": native["engine"],
        "engine_version": native["abacus_version_target"],
        "basis_type": native["basis_type"],
        "science": {
            "dft_functional": native["dft_functional"],
            "nspin": native["nspin"],
            "initial_moments_muB_by_element": native["initial_moments_muB_by_element"],
            "occupations": native["occupations"],
            "smearing_method": native["smearing_method"],
            "mixing_type": native["mixing_type"],
            "relax_method": native["relax_method"],
            "symmetry": native["symmetry"],
        },
        "execution": {"device": "gpu", "ks_solver": native["ks_solver"]},
        "parameters": native["parameters"],
        "kpoints": native["kpoints"],
        "element_order": elements,
        "method_set": method_set,
        "pseudopotential_ids": native["pseudopotential_ids"],
        "pseudopotential_treatment": native["pseudopotential_treatment"],
        "pseudopotential_metadata": native["pseudopotential_metadata"],
    }


def test_configuration_record_uses_abacus_neutral_defaults_explicitly():
    host = _configuration_method(elements=["Ca", "O"], nbands=40, method_set="host-config")
    defect = _configuration_method(elements=["Ca", "O", "Ni"], nbands=52, method_set="defect-config")

    report = compare_variant_method_records(
        host,
        defect,
        host_elements={"Ca", "O"},
        defect_elements={"Ca", "O", "Ni"},
        record_kind="configuration",
    )

    assert report["passed"] is True
    assert report["common_physics"] is True
    assert report["record_kind"] == "configuration"
    assert report["composition_related_differences"]["element_set"]["defect_only"] == ["Ni"]


def test_variant_comparison_allows_new_element_and_records_composition_changes():
    host = _method(elements=["Ca", "O"], nbands=40, valence=16, method_set="host")
    defect = _method(elements=["Ca", "O", "Ni"], nbands=52, valence=34, method_set="defect")

    report = compare_variant_method_records(
        host,
        defect,
        host_elements={"Ca", "O"},
        defect_elements={"Ca", "O", "Ni"},
        record_kind="native",
    )

    assert report["passed"] is True
    assert report["new_elements"] == ["Ni"]
    assert report["removed_elements"] == []
    assert report["composition_related_differences"]["parameters"]["nbands"] == {
        "host": 40,
        "defect": 52,
    }
    assert report["composition_related_differences"]["electron_count"] == {
        "host": {
            "net_charge": 0,
            "nelec": 0,
            "nelec_delta": 0,
            "electron_count": {"neutral_valence_electrons": 16},
        },
        "defect": {
            "net_charge": 0,
            "nelec": 0,
            "nelec_delta": 0,
            "electron_count": {"neutral_valence_electrons": 34},
        },
    }
    assert report["resource_coverage"]["pseudopotentials"]["defect"]["Ni"] is True
    assert report["resource_records"]["pseudopotentials"]["defect"]["Ni"][
        "pseudopotential_metadata"
    ]["valence_electrons_per_atom"] == 4
    assert report["composition_related_differences"]["valence_electrons_per_atom"]["Ni"] == {
        "host": None,
        "defect": 4,
    }


def test_variant_comparison_rejects_changed_common_pseudopotential():
    host = _method(elements=["Ca", "O"], nbands=40, valence=16)
    defect = _method(elements=["Ca", "O", "Ni"], nbands=52, valence=34)
    defect["pseudopotential_ids"]["O"] = "O_OTHER_PBE"

    report = compare_variant_method_records(
        host,
        defect,
        host_elements={"Ca", "O"},
        defect_elements={"Ca", "O", "Ni"},
        record_kind="native",
    )

    assert report["passed"] is False
    assert any(item["reason"] == "common_pseudopotential_mismatch" for item in report["mismatches"])


def test_variant_comparison_rejects_unrecognised_physical_field():
    host = _method(elements=["Ca", "O"], nbands=40, valence=16)
    defect = _method(elements=["Ca", "O", "Ni"], nbands=52, valence=34)
    defect["dft_plus_u"] = {"Ti": 4.0}

    report = compare_variant_method_records(
        host,
        defect,
        host_elements={"Ca", "O"},
        defect_elements={"Ca", "O", "Ni"},
        record_kind="native",
    )

    assert report["passed"] is False
    assert report["common_physics"] is False
    assert "defect_method.dft_plus_u" in report["unsupported"]


def test_variant_comparison_requires_resources_for_added_element():
    host = _method(elements=["Ca", "O"], nbands=40, valence=16)
    defect = _method(elements=["Ca", "O", "Ni"], nbands=52, valence=34)
    defect["pseudopotentials"].pop("Ni")
    defect["pseudopotential_ids"].pop("Ni")
    defect["pseudopotential_treatment"].pop("Ni")
    defect["pseudopotential_metadata"].pop("Ni")

    report = compare_variant_method_records(
        host,
        defect,
        host_elements={"Ca", "O"},
        defect_elements={"Ca", "O", "Ni"},
        record_kind="native",
    )

    assert report["passed"] is False
    assert "defect pseudopotential.pseudopotential_ids.Ni" in report["missing"]
    assert report["resource_coverage"]["pseudopotentials"]["defect"]["Ni"] is False


def test_variant_comparison_rejects_manual_electron_override_and_empty_parameters():
    host = _method(elements=["Ca", "O"], nbands=40, valence=16)
    defect = _method(elements=["Ca", "O", "Ni"], nbands=52, valence=34)
    defect["nelec"] = 34
    report = compare_variant_method_records(host, defect, host_elements={"Ca", "O"},
        defect_elements={"Ca", "O", "Ni"}, record_kind="native")
    assert not report["passed"] and not report["common_physics"]
    assert any(item["field"] == "defect.nelec" for item in report["mismatches"])
    defect["nelec"] = 0
    host["parameters"] = defect["parameters"] = {}
    report = compare_variant_method_records(host, defect, host_elements={"Ca", "O"},
        defect_elements={"Ca", "O", "Ni"}, record_kind="native")
    assert not report["passed"] and not report["common_physics"]
    assert "common parameter host.scf_thr" in report["missing"]


def test_lcao_common_orbital_identity_cannot_change():
    host = _method(elements=["Ca", "O"], nbands=40, valence=16)
    defect = _method(elements=["Ca", "O", "Ni"], nbands=52, valence=34)
    for method in (host, defect):
        method["basis_type"] = "lcao"
        method["numerical_orbitals"] = {e: {"source": f"/orb/{e}.orb", "filename": f"{e}.orb"} for e in method["element_order"]}
        method["numerical_orbital_ids"] = {e: f"{e}_NAO" for e in method["element_order"]}
    defect["numerical_orbital_ids"]["O"] = "O_OTHER_NAO"
    report = compare_variant_method_records(host, defect, host_elements={"Ca", "O"},
        defect_elements={"Ca", "O", "Ni"}, record_kind="native")
    assert not report["passed"] and not report["common_element_numerical_orbitals"]
    assert any(item["field"] == "numerical_orbital_ids.O" for item in report["mismatches"])
