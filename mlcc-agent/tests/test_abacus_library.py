"""Read-only tests for the site-managed ABACUS resource catalog."""

from __future__ import annotations

import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

from mlcc.abacus_library import PERIODIC_TABLE, describe_abacus_resources
from mlcc.upf_headers import parse_upf_header


_PBE_HEADER = (
    '<PP_HEADER element="O" pseudo_type="NC" relativistic="scalar" '
    'is_ultrasoft="F" is_paw="F" has_so="F" functional="PBE" z_valence="6"/>'
)


def test_native_bh_reference_header_keeps_core_valence_boundary():
    parser = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/resources/build_abacus_catalog.py"))["_f_electrons"]
    configuration = """<PP_INPUTFILE>
Bh107.00   10    8       4      both
1 0 2.00
2 0 2.00
2 1 6.00
3 0 2.00
3 1 6.00
3 2 10.00
4 0 2.00
4 1 6.00
4 2 10.00
4 3 14.00
5 0 2.00
5 1 6.00
5 2 10.00
5 3 14.00
6 0 2.00
6 1 6.00
6 2 5.00
7 0 2.00
</PP_INPUTFILE>"""
    result = parser(configuration, Path("Bh-5spdf.upf"))

    assert result["evidence"]["element"] == "Bh"
    assert result["evidence"]["atomic_number"] == 107
    assert (result["nc"], result["nv"]) == (10, 8)
    assert [(row["n"], row["treatment"]) for row in result["f_rows"]] == [(4, "core"), (5, "valence")]
    assert result["evidence"]["header"][0] == "Bh107.00"


def _pseudopotential(element: str, *, compatible: bool = True, f_treatment: str = "unknown") -> dict:
    return {
        "id": f"{element}_ONCV_PBE",
        "path": f"/private/v100/{element}.upf",
        "source_url": "https://example.invalid/provider",
        "license": "provider-license",
        "family": "ONCV",
        "version": "1.0",
        "header": {
            "source_path": f"/private/v100/{element}.upf",
            "element": element,
            "functional": "PBE",
            "functional_normalized": "PBE",
            "z_valence": 6,
            "native_excerpts": ["/private/v100/native.txt"],
        },
        "f_electrons": {
            "treatment": f_treatment,
            "evidence": "provider release notes",
            "source": "https://example.invalid/provider-notes",
        },
        "input_compatible": compatible,
        "issues": [],
    }


def _catalog(tmp_path: Path) -> Path:
    records = []
    for number, symbol in enumerate(PERIODIC_TABLE, start=1):
        records.append(
            {
                "symbol": symbol,
                "atomic_number": number,
                "status": "missing",
                "preferred_pseudopotential_id": None,
                "pseudopotentials": [],
                "orbitals": [],
                "issues": [],
            }
        )
    records[7]["status"] = "available"
    records[7]["preferred_pseudopotential_id"] = "O_ONCV_PBE"
    records[7]["pseudopotentials"] = [_pseudopotential("O")]
    records[68]["status"] = "header_compatible"
    records[68]["preferred_pseudopotential_id"] = "Tm_ONCV_PBE"
    records[68]["pseudopotentials"] = [_pseudopotential("Tm", f_treatment="core")]
    records[0]["status"] = "available"  # no resource: must not remain available
    catalog = tmp_path / "abacus-library.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "mlcc.abacus-library.v1",
                "version": "2026.10",
                "sources": [{"provider": "fixture", "source_url": "https://example.invalid/provider"}],
                "elements": records,
            }
        ),
        encoding="utf-8",
    )
    site = tmp_path / "site.json"
    site.write_text(json.dumps({"abacus": {"resource_catalog": catalog.name}}), encoding="utf-8")
    return site


def test_summary_contains_all_118_elements_in_atomic_order(tmp_path):
    result = describe_abacus_resources(_catalog(tmp_path))

    assert result["schema"] == "mlcc.abacus-resource-summary.v1"
    assert result["default_engine"] == "abacus"
    assert len(result["elements"]) == 118
    assert [record["symbol"] for record in result["elements"]] == list(PERIODIC_TABLE)
    assert [record["atomic_number"] for record in result["elements"]] == list(range(1, 119))
    assert result["elements"][7]["status"] == "available"
    assert result["elements"][7]["preferred_pseudopotential_id"] == "O_ONCV_PBE"


def test_missing_or_inconsistent_element_is_never_reported_available(tmp_path):
    result = describe_abacus_resources(_catalog(tmp_path))

    hydrogen = result["elements"][0]
    carbon = result["elements"][5]
    assert hydrogen["status"] == "missing"
    assert carbon["status"] == "missing"


def test_selected_metadata_preserves_native_science_and_removes_private_paths(tmp_path):
    site = _catalog(tmp_path)
    catalog_path = tmp_path / "abacus-library.json"
    catalog = json.loads(catalog_path.read_text())
    catalog["elements"][68]["orbitals"] = [{
        "id": "Tm_NAO", "library_id": "AIS381_efficiency_v1",
        "pairing_source": "/private/v100/readme.txt",
        "pseudopotential_map": "/private/v100/element.json",
    }]
    catalog["sources"][0]["element_map"] = "/private/v100/element.json"
    catalog_path.write_text(json.dumps(catalog))
    result = describe_abacus_resources(site, elements=["O", "Tm"])
    selected = result["selected"]

    assert [record["symbol"] for record in selected] == ["O", "Tm"]
    assert selected[0]["pseudopotentials"][0]["header"]["element"] == "O"
    assert "source_path" not in selected[0]["pseudopotentials"][0]["header"]
    assert "native_excerpts" not in selected[0]["pseudopotentials"][0]["header"]
    assert selected[1]["pseudopotentials"][0]["f_electrons"] == {
        "treatment": "core",
        "evidence": "provider release notes",
        "source": "https://example.invalid/provider-notes",
    }
    assert selected[1]["orbitals"][0]["library_id"] == "AIS381_efficiency_v1"
    serialized = json.dumps(result)
    assert "/private/v100" not in serialized


@pytest.mark.parametrize(
    "functional,normalized",
    [("PBE", "PBE"), ("SLA PW PBX PBC", "PBE")],
)
def test_native_pbe_functional_spellings_are_normalized_without_losing_raw_value(functional, normalized):
    text = _PBE_HEADER.replace('functional="PBE"', f'functional="{functional}"')
    parsed = parse_upf_header(f'<UPF version="2.0.1">{text}</UPF>', "O.upf")

    assert parsed["functional"] == functional
    assert parsed["functional_normalized"] == normalized
    assert parsed["functional_is_pbe"] is True


def test_library_module_does_not_import_numpy_or_ase(tmp_path):
    source_root = Path(__file__).resolve().parents[1] / "src"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import mlcc.abacus_library; assert 'numpy' not in sys.modules; assert 'ase' not in sys.modules",
        ],
        cwd=tmp_path,
        env={"PYTHONPATH": str(source_root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
