"""Input-only ABACUS qualification checks using the observed UPF headers."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from mlcc.method_inputs import parse_upf_header, qualify_method_inputs, read_upf_header
from mlcc.modeling import ModelArtifacts


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "workspace" / "reports" / "p2" / "cazro3-upf-inventory-v001.json"


def _observed_headers(tmp_path: Path) -> tuple[dict[str, dict], dict[str, str]]:
    """Materialize only the real observed PP_HEADER strings from the audit report."""

    report = json.loads(INVENTORY.read_text(encoding="utf-8"))
    headers = {}
    paths = {}
    for element, record in report["upf_headers"].items():
        source = tmp_path / f"{element}.upf"
        source.write_text(f'<UPF version="2.0.1">\n{record["raw_header"]}\n</UPF>\n', encoding="utf-8")
        headers[element] = read_upf_header(source)
        paths[element] = str(source)
    return headers, paths


def _model() -> ModelArtifacts:
    symbols = ["Ca"] * 4 + ["Zr"] * 4 + ["O"] * 12
    atoms = Atoms(
        symbols=symbols,
        cell=np.diag([5.58, 5.76, 8.01]),
        pbc=True,
        positions=np.zeros((len(symbols), 3)),
    )
    return ModelArtifacts(
        model_id="cazro3-pnma-pristine",
        version="v001",
        atoms=atoms,
        metadata={"fixture": False},
        artifact_dir=Path("."),
    )


def _config() -> dict:
    return {
        "engine": "abacus",
        "engine_version": "3.10.1",
        "basis_type": "pw",
        "element_order": ["Ca", "Zr", "O"],
        "net_charge": 0,
        "compatibility_reference": "ABACUS 3.10.1 average-j compatibility review",
        "pseudopotential_treatment": {"Ca": "abacus_3.10.1_average_j", "Zr": "scalar", "O": "scalar"},
        "pseudopotential_metadata": {
            "Ca": {
                "element": "Ca",
                "functional": "PBE",
                "valence_electrons_per_atom": 10,
                "relativity": "full",
                "has_spin_orbit": True,
                "type": "ONCV_NC",
                "qualification": "input_compatibility_only",
            },
            "Zr": {
                "element": "Zr",
                "functional": "PBE",
                "valence_electrons_per_atom": 12,
                "relativity": "scalar",
                "has_spin_orbit": False,
                "type": "ONCV_NC",
                "qualification": "input_compatibility_only",
            },
            "O": {
                "element": "O",
                "functional": "PBE",
                "valence_electrons_per_atom": 6,
                "relativity": "scalar",
                "has_spin_orbit": False,
                "type": "ONCV_NC",
                "qualification": "input_compatibility_only",
            },
        },
        "science": {
            "suffix": "CZOInputCheck",
            "dft_functional": "PBE",
            "nspin": 1,
            "initial_moments_muB_by_element": {"Ca": 0.0, "Zr": 0.0, "O": 0.0},
            "occupations": "fixed",
            "smearing_method": None,
            "mixing_type": "broyden",
            "relax_method": "cg",
            "symmetry": 0,
            "lspinorb": False,
            "noncolin": False,
        },
        "execution": {"device": "cpu", "ks_solver": "cg"},
        "parameters": {
            "ecutwfc_Ry": 100.0,
            "scf_thr": 1e-4,
            "scf_nmax": 100,
            "nbands": 88,
            "smearing_sigma_Ry": None,
            "mixing_beta": 0.3,
            "force_thr_eV_per_A": None,
            "relax_nmax": None,
        },
        "kpoints": [2, 2, 2],
    }


def test_parse_real_observed_upf_headers_and_preserves_raw_header(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    assert set(headers) == {"Ca", "Zr", "O"}
    assert headers["Ca"]["element"] == "Ca"
    assert headers["Ca"]["functional"] == "PBE"
    assert headers["Ca"]["z_valence"] == pytest.approx(10.0)
    assert headers["Ca"]["relativistic"] == "full"
    assert headers["Ca"]["has_so"] is True
    assert headers["Zr"]["has_so"] is False
    assert headers["O"]["element"] == "O"
    assert headers["O"]["raw_header"].startswith("<PP_HEADER")
    assert headers["O"]["source_path"] == paths["O"]


def test_parse_upf_header_accepts_native_root_header_fragment(tmp_path):
    report = json.loads(INVENTORY.read_text(encoding="utf-8"))
    raw = report["upf_headers"]["O"]["raw_header"]
    parsed = parse_upf_header(f'<UPF version="2.0.1">{raw}</UPF>', "fragment-O.upf")
    assert parsed["upf_version"] == "2.0.1"
    assert parsed["element"] == "O"
    assert parsed["is_ultrasoft"] is False
    assert parsed["is_paw"] is False


def test_parse_upf_header_does_not_guess_non_pbe_functional():
    raw = '<PP_HEADER element="X" pseudo_type="NC" relativistic="scalar" is_ultrasoft="F" is_paw="F" has_so="F" functional="PBEsol" z_valence="4"/>'
    parsed = parse_upf_header(f'<UPF version="2.0.1">{raw}</UPF>', "x.upf")
    assert parsed["functional"] == "PBEsol"
    assert parsed["functional_is_pbe"] is False


def test_native_upf_pbe_token_passes_full_method_qualification(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    for element, header in list(headers.items()):
        raw = header["raw_header"].replace('functional="PBE"', 'functional="SLA PW PBX PBC"')
        headers[element] = parse_upf_header(
            f'<UPF version="2.0.1">{raw}</UPF>',
            paths[element],
        )

    report = qualify_method_inputs(_model(), _config(), headers, paths)

    assert report["input_qualified"] is True
    assert report["checks"]["pbe_functional"]["passed"] is True
    assert all(header["functional"] == "SLA PW PBX PBC" for header in headers.values())
    assert all(header["functional_normalized"] == "PBE" for header in headers.values())


@pytest.mark.parametrize(
    "text,match",
    [
        ('<UPF version="1.0"><PP_HEADER/></UPF>', "2.x"),
        ('<UPF version="2.0.1"></UPF>', "PP_HEADER"),
        ('<ROOT version="2.0.1"></ROOT>', "UPF"),
    ],
)
def test_parse_upf_header_rejects_invalid_native_header(text, match):
    with pytest.raises(ValueError, match=match):
        parse_upf_header(text, "bad.upf")


def test_cazro3_input_contract_passes_with_explicit_average_j_policy(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    report = qualify_method_inputs(_model(), _config(), headers, paths)
    assert report["input_qualified"] is True
    assert report["passed"] is True
    assert report["production_qualification"] is False
    assert report["electron_count"]["neutral_valence_electrons"] == pytest.approx(160.0)
    assert report["issues"] == []


def test_missing_net_charge_is_an_original_input_problem(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    del config["net_charge"]
    report = qualify_method_inputs(_model(), config, headers, paths)
    assert report["input_qualified"] is False
    assert any("net_charge" in item for item in report["issues"])


@pytest.mark.parametrize("charge,target,delta", [(2, 158.0, -2), (-2, 162.0, 2)])
def test_charged_scf_contract_separates_neutral_and_target_electrons(tmp_path, charge, target, delta):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    config["net_charge"] = charge
    report = qualify_method_inputs(_model(), config, headers, paths)
    assert report["input_qualified"] is True
    assert report["scientific_qualification"] is False
    assert report["production_qualification"] is False
    assert report["electron_count"]["neutral_valence_electrons"] == pytest.approx(160.0)
    assert report["electron_count"]["target_electrons"] == pytest.approx(target)
    assert report["electron_count"]["net_charge"] == charge
    assert report["electron_count"]["nelec"] == 0
    assert report["electron_count"]["nelec_delta"] == delta


@pytest.mark.parametrize(
    "mutator,match",
    [
        (lambda config: config.update(net_charge=1), "even target electron count"),
        (lambda config: config.update(net_charge=1.5), "explicit integer"),
        (lambda config: config.update(net_charge=161), "target electron count must be positive"),
    ],
)
def test_charged_scf_rejects_odd_fractional_or_nonpositive_target(tmp_path, mutator, match):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    mutator(config)
    report = qualify_method_inputs(_model(), config, headers, paths)
    assert report["input_qualified"] is False
    assert any(match in item for item in report["issues"])


def test_nested_charge_copy_must_match_canonical_top_level_value(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    config["net_charge"] = 2
    config["science"]["net_charge"] = -2
    report = qualify_method_inputs(_model(), config, headers, paths)
    assert report["input_qualified"] is False
    assert any("disagrees with top-level net_charge" in item for item in report["issues"])


def test_charged_scf_rejects_relax_stage_and_spin_smearing(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    config["net_charge"] = 2
    config["stage"] = "relax"
    config["science"].update(occupations="smearing", smearing_method="gauss")
    config["parameters"].update(smearing_sigma_Ry=0.01, force_thr_eV_per_A=0.02, relax_nmax=20)
    report = qualify_method_inputs(_model(), config, headers, paths)
    assert report["input_qualified"] is False
    assert any("fixed-cell scf only" in item for item in report["issues"])
    assert any("fixed occupations" in item for item in report["issues"])


def test_ca_requires_explicit_average_j_or_a_compatible_scalar_header(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    config["pseudopotential_treatment"]["Ca"] = "scalar"
    report = qualify_method_inputs(_model(), config, headers, paths)
    assert report["input_qualified"] is False
    assert any("scalar treatment for Ca" in item for item in report["issues"])


@pytest.mark.parametrize("relativistic", ["full", "mystery"])
def test_scalar_policy_requires_scalar_relativistic_header(tmp_path, relativistic):
    headers, paths = _observed_headers(tmp_path)
    headers["O"] = {**headers["O"], "relativistic": relativistic}
    report = qualify_method_inputs(_model(), _config(), headers, paths)
    assert report["input_qualified"] is False
    assert any("scalar treatment for O" in item for item in report["issues"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("element", "CaX"),
        ("functional", "PBEsol"),
        ("valence_electrons_per_atom", 11),
        ("relativity", "scalar"),
        ("has_spin_orbit", False),
        ("type", "USPP"),
    ],
)
def test_pseudopotential_metadata_must_match_native_headers(tmp_path, field, value):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    config["pseudopotential_metadata"]["Ca"][field] = value
    report = qualify_method_inputs(_model(), config, headers, paths)
    assert report["input_qualified"] is False
    assert any("pseudopotential_metadata" in item for item in report["issues"])


def test_pseudopotential_metadata_is_required(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    del config["pseudopotential_metadata"]
    report = qualify_method_inputs(_model(), config, headers, paths)
    assert report["input_qualified"] is False
    assert any("pseudopotential_metadata" in item for item in report["issues"])


@pytest.mark.parametrize(
    "field,value",
    [("device", "not-a-device"), ("ks_solver", "not-a-solver")],
)
def test_execution_rejects_unknown_values(tmp_path, field, value):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    config["execution"][field] = value
    report = qualify_method_inputs(_model(), config, headers, paths)
    assert report["input_qualified"] is False
    assert any("ABACUS execution validation failed" in item for item in report["issues"])


def test_staged_pseudopotential_filenames_must_be_distinct(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    duplicate_paths = dict(paths)
    duplicate_paths["O"] = str(tmp_path / "other" / "Ca.upf")
    duplicate_headers = {**headers, "O": {**headers["O"], "source_path": duplicate_paths["O"]}}
    report = qualify_method_inputs(_model(), _config(), duplicate_headers, duplicate_paths)
    assert report["input_qualified"] is False
    assert report["checks"]["distinct_staged_UPF_filenames"]["passed"] is False
    assert any("distinct filenames" in item for item in report["issues"])


def test_average_j_requires_nonempty_compatibility_reference(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    config["compatibility_reference"] = ""
    report = qualify_method_inputs(_model(), config, headers, paths)
    assert report["input_qualified"] is False
    assert any("compatibility_reference" in item for item in report["issues"])


def test_nspin2_smearing_checks_total_capacity_and_nominal_empty_band(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    config["science"].update(
        nspin=2,
        occupations="smearing",
        smearing_method="gauss",
        initial_moments_muB_by_element={"Ca": 0.6, "Zr": 0.0, "O": 0.0},
    )
    config["parameters"]["nbands"] = 81
    config["parameters"]["smearing_sigma_Ry"] = 0.01
    report = qualify_method_inputs(_model(), config, headers, paths)
    assert report["input_qualified"] is True
    assert "per-spin final occupations" in report["electron_count"]["occupation_capacity_note"]

    config["parameters"]["nbands"] = 80
    rejected = qualify_method_inputs(_model(), config, headers, paths)
    assert rejected["input_qualified"] is False
    assert any("nspin=2 smearing" in item for item in rejected["issues"])


def test_nspin2_fixed_is_not_supported_by_the_current_writer(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    config["science"].update(nspin=2, initial_moments_muB_by_element={"Ca": 0.6, "Zr": 0.0, "O": 0.0})
    report = qualify_method_inputs(_model(), config, headers, paths)
    assert report["input_qualified"] is False
    assert any("nspin=2 fixed occupations" in item for item in report["issues"])


def test_flags_must_be_explicit_false_and_paths_must_match(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    config["science"]["noncolin"] = True
    wrong_paths = dict(paths)
    wrong_paths["O"] = str(tmp_path / "other-O.upf")
    report = qualify_method_inputs(_model(), config, headers, wrong_paths)
    assert report["input_qualified"] is False
    assert any("noncolin" in item for item in report["issues"])
    assert any("source_path" in item for item in report["issues"])


def test_method_and_execution_domain_validation_are_reported(tmp_path):
    headers, paths = _observed_headers(tmp_path)
    config = _config()
    config["science"]["mixing_type"] = ""
    config["execution"]["device"] = ""
    report = qualify_method_inputs(_model(), config, headers, paths)
    assert report["input_qualified"] is False
    assert any("ABACUS method validation failed" in item for item in report["issues"])
    assert any("ABACUS execution validation failed" in item for item in report["issues"])

