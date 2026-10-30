import json
from pathlib import Path

from mlcc.method_tasks import inspect_site_nao_headers


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_inspect_nao_uses_registered_site_library_id(tmp_path):
    upf = tmp_path / "H.upf"
    upf.write_text(
        '<UPF version="2.0.1">\n'
        '<PP_HEADER element="H" pseudo_type="NC" functional="PBE" '
        'z_valence="1" relativistic="scalar" has_so="F" '
        'is_ultrasoft="F" is_paw="F"/>\n'
        '</UPF>\n',
        encoding="utf-8",
    )
    orbital = tmp_path / "H_gga.orb"
    orbital.write_text(
        "Element H\nEnergy Cutoff(Ry) 100\nRadius Cutoff(a.u.) 6\n"
        "Lmax 1\nNumber of s orbital -> 2\nNumber of p orbital -> 1\nSUMMARY END\n",
        encoding="utf-8",
    )
    readme = tmp_path / "readme.txt"
    readme.write_text(
        "NAOs MUST be used together with corresponding PSPs in apns-pseudopotentials-v1.\n",
        encoding="utf-8",
    )
    element_map = tmp_path / "element.json"
    _write_json(element_map, {"H": upf.name})
    library_id = "AIS381_efficiency_v1"
    library = {
        "name": "AIS381 efficiency",
        "version": "AIS381",
        "functional": "SLA PW PBX PBC",
        "pairing_source": str(readme),
        "pseudopotential_map": str(element_map),
    }
    method = tmp_path / "method.json"
    _write_json(method, {
        "basis_type": "lcao",
        "method_set": "registered-nao-test-v001",
        "element_order": ["H"],
        "science": {"dft_functional": "PBE"},
        "numerical_orbital_library_id": library_id,
        "numerical_orbital_ids": {"H": "AIS381_H_NAO_H_gga"},
        "pseudopotential_ids": {"H": "AIS381_H_PBE"},
    })
    site = tmp_path / "site.json"
    _write_json(site, {
        "ssh": {"alias": "local-test", "transport": "local"},
        "abacus": {
            "pseudopotential_files": {"AIS381_H_PBE": str(upf)},
            "numerical_orbital_files": {"AIS381_H_NAO_H_gga": str(orbital)},
            "numerical_orbital_libraries": {library_id: library},
        },
    })

    snapshot = inspect_site_nao_headers(method, site)

    assert snapshot["library_id"] == library_id
    assert snapshot["library"] == library["name"]
    assert snapshot["library_version"] == library["version"]
    assert snapshot["pairing_source"] == str(readme)
    assert snapshot["pseudopotential_map_path"] == str(element_map)
    assert snapshot["native_excerpts"]["H"]["functional"] == "SLA PW PBX PBC"

    legacy_method = json.loads(method.read_text(encoding="utf-8"))
    legacy_method.pop("numerical_orbital_library_id")
    legacy_method["numerical_orbital_library"] = library
    _write_json(method, legacy_method)
    legacy_snapshot = inspect_site_nao_headers(method, site)
    assert "library_id" not in legacy_snapshot
    assert legacy_snapshot["library"] == library["name"]
