"""New LCAO section-boundary checks; no material calculation or old tests."""
from pathlib import Path

import pytest

from mlcc.berry import _read_stru_contract


STRU = """ATOMIC_SPECIES
Ca 40.078 Ca.upf upf201
Zr 91.224 Zr_ONCV_PBE-1.0.upf upf201
O 15.999 O.upf upf201

NUMERICAL_ORBITAL
Ca_gga_10au_100Ry_4s2p1d.orb
Zr_gga_10au_100Ry_4s2p2d1f.orb
O_gga_6au_100Ry_2s2p1d.orb

LATTICE_CONSTANT
1.0
LATTICE_VECTORS
1 0 0
0 1 0
0 0 1
ATOMIC_POSITIONS
Direct
Ca
0
1
0 0 0 m 1 1 1
Zr
0
1
0.5 0.5 0.5 m 1 1 1
O
0
1
0.5 0 0 m 1 1 1
"""


def test_lcao_orbital_section_is_not_a_species_row(tmp_path: Path):
    path = tmp_path / "STRU"
    path.write_text(STRU)
    record = _read_stru_contract(path)
    assert record["species"] == ["Ca", "Zr", "O"]
    assert record["pseudo"] == {"Ca": "Ca.upf", "Zr": "Zr_ONCV_PBE-1.0.upf", "O": "O.upf"}
    assert [item["element"] for item in record["records"]] == ["Ca", "Zr", "O"]


def test_lcao_malformed_species_keeps_original_error(tmp_path: Path):
    path = tmp_path / "STRU"
    path.write_text(STRU.replace("Ca 40.078 Ca.upf upf201", "Ca 40.078"))
    with pytest.raises(ValueError, match="invalid ATOMIC_SPECIES row"):
        _read_stru_contract(path)
