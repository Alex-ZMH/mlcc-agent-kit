"""Contract tests for the independent LAMMPS multi-replica NEB path.

The output fixtures in this file are deliberately synthetic log/dump text. They
exercise the native parser and file contract only; the tiny neutral three-element
model is likewise a mathematical fixture, not scientific evidence or a physical
vacancy barrier and not a replacement for the v100 Slurm acceptance run.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from mlcc.lammps_neb import (
    NEB_RESULT_SCHEMA,
    parse_lammps_neb_outputs,
    prepare_lammps_neb,
    validate_neb_protocol,
)
from mlcc.modeling import ModelArtifacts, write_model_artifacts
from mlcc.neb_tasks import create_lammps_neb_task


FIXTURE_MODEL_ID = "czo-neb-math-fixture"
FIXTURE_FINAL_MODEL_ID = "czo-neb-math-fixture-final"
FIXTURE_ATOM_IDS = [2, 7, 13]
FIXTURE_SYMBOLS = ["Ca", "Zr", "O"]
FIXTURE_CELL = [
    [4.0, 0.4, 0.2],
    [0.0, 4.5, 0.3],
    [0.0, 0.0, 5.0],
]
FIXTURE_POSITIONS = [
    [0.4, 0.5, 0.6],
    [1.7, 2.0, 1.2],
    [3.6, 1.1, 2.4],
]


def _models(tmp_path: Path) -> tuple[ModelArtifacts, ModelArtifacts]:
    initial_atoms = Atoms(
        symbols=FIXTURE_SYMBOLS,
        positions=FIXTURE_POSITIONS,
        cell=FIXTURE_CELL,
        pbc=True,
    )
    initial_atoms.new_array("atom_id", np.asarray(FIXTURE_ATOM_IDS, dtype=np.int64))
    initial = write_model_artifacts(
        initial_atoms,
        tmp_path / "initial-model",
        model_id=FIXTURE_MODEL_ID,
        version="v001",
        fixture=True,
        fixture_purpose="lammps_neb_math_contract",
        phase_requested="fixture_phase",
        source_path="lammps-neb-test-fixture",
        source_version="fixture-v001",
        material="CZO-NEB-test-fixture",
    )
    # Deliberately reorder the endpoint so the writer must bind by stable atom
    # ID rather than by position in the Atoms array.
    final_atoms = initial.atoms[::-1]
    moved_index = next(
        index for index, atom_id in enumerate(final_atoms.arrays["atom_id"]) if int(atom_id) == 13
    )
    # Keep the endpoint deliberately unwrapped (x=4.20 A for this cell) so
    # interpolation must use the persisted raw final position rather than
    # silently wrapping it before adding the explicit image shift.
    final_atoms.positions[moved_index] += np.asarray([0.60, 0.0, 0.0])
    final = write_model_artifacts(
        final_atoms,
        tmp_path / "final-model",
        model_id=FIXTURE_FINAL_MODEL_ID,
        version="v001",
        fixture=True,
        fixture_purpose="lammps_neb_math_contract",
        phase_requested="fixture_phase",
        source_path="lammps-neb-test-fixture-final",
        source_version="fixture-v001",
        material="CZO-NEB-test-fixture",
    )
    return initial, final


def _potential(tmp_path: Path) -> dict:
    model_file = tmp_path / "czo-deepmd.pb"
    model_file.write_text("engineering fixture potential\n", encoding="utf-8")
    return {
        "potential_id": "czo-deepmd-frozen",
        "version": "v001",
        "source": "self-contained neutral CZO NEB math fixture",
        "license": "engineering-fixture",
        "fixture": True,
        "production_qualification": False,
        "units": "metal",
        "atom_style": "atomic",
        "elements": ["Ca", "Zr", "O"],
        "element_order": ["Ca", "Zr", "O"],
        "model_ids": [FIXTURE_MODEL_ID],
        "pair_style": "deepmd czo-deepmd.pb",
        "pair_coeff": ["* * czo-deepmd.pb Ca Zr O"],
        "files": [{"local_path": str(model_file), "filename": "czo-deepmd.pb"}],
    }


def _protocol(*, images: int = 3, output_every: int = 2) -> dict:
    return {
        "schema": "mlcc.lammps-neb-protocol.v1",
        "kind": "neb",
        "purpose": "vacancy_migration",
        "path_provenance": {
            "mode": "neb_path",
            "path_id": "czo-neb-math-engineering-fixture",
            "host_model": f"{FIXTURE_MODEL_ID}/v001",
            "vacancy_parent_atom_id": 2,
            "migrating_atom_id": 13,
            "source_parent_site_id": 13,
            "target_parent_site_id": 2,
            "target_parent_image": [0, 0, 0],
            "endpoint_preparation_source": "explicit-test-endpoints",
        },
        "endpoint_minimization": {
            "min_style": "cg",
            "etol": 0.0,
            "ftol_eV_per_angstrom": 0.05,
            "max_iterations": 200,
            "max_evaluations": 1000,
        },
        "images": images,
        "ranks_per_image": 2,
        "min_style": "quickmin",
        "timestep_ps": 0.001,
        "etol": 0.0,
        "ftol_eV_per_angstrom": 0.05,
        "max_iterations": 6,
        "climb_iterations": 4,
        "output_every": output_every,
        "spring_eV_per_angstrom2": 1.0,
        "neb_atom_ids": list(FIXTURE_ATOM_IDS),
        "endpoint_policy": "fixed",
        "final_image_shifts": [
            {"atom_id": atom_id, "image": [0, 0, 0]} for atom_id in FIXTURE_ATOM_IDS
        ],
    }


def _prepare(tmp_path: Path) -> tuple[Path, dict, ModelArtifacts, ModelArtifacts]:
    initial, final = _models(tmp_path)
    directory = tmp_path / "neb"
    prepared = prepare_lammps_neb(
        initial,
        final,
        directory,
        potential=_potential(tmp_path),
        protocol=_protocol(),
    )
    return directory, prepared, initial, final


def _data_atom_ids(path: Path) -> list[int]:
    """Read only the atom-ID column from a small LAMMPS ``Atoms`` section."""

    rows: list[int] = []
    in_atoms = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("Atoms"):
            in_atoms = True
            continue
        if not in_atoms or not stripped:
            continue
        first = stripped.split()[0]
        if first in {"Velocities", "Bonds", "Angles", "Dihedrals", "Impropers"}:
            break
        if first.lstrip("+-").isdigit():
            rows.append(int(first))
    return rows


def test_validate_neb_protocol_rejects_unsupported_minimizer_and_invalid_stride() -> None:
    protocol = _protocol()
    protocol["min_style"] = "cg"
    with pytest.raises(ValueError, match="min_style"):
        validate_neb_protocol(protocol)

    protocol = _protocol()
    protocol["output_every"] = 4
    with pytest.raises(ValueError, match="output_every"):
        validate_neb_protocol(protocol)

    protocol = _protocol()
    protocol["min_style"] = "neb/spin"
    with pytest.raises(ValueError, match="min_style"):
        validate_neb_protocol(protocol)

    protocol = _protocol()
    protocol["endpoint_minimization"] = {
        "min_style": "cg",
        "etol": 0.0,
        "ftol_eV": 0.05,
        "max_iterations": 200,
        "max_evaluations": 1000,
    }
    with pytest.raises(ValueError, match="ftol_eV_per_angstrom"):
        validate_neb_protocol(protocol)

    protocol = _protocol()
    protocol["ftol"] = protocol.pop("ftol_eV_per_angstrom")
    with pytest.raises(ValueError, match="ftol_eV_per_angstrom"):
        validate_neb_protocol(protocol)


def test_validate_neb_protocol_requires_schema_provenance_and_endpoint_minimization() -> None:
    for field in ("schema", "path_provenance", "endpoint_minimization"):
        protocol = _protocol()
        protocol.pop(field)
        with pytest.raises(ValueError):
            validate_neb_protocol(protocol)


def test_prepare_binds_reordered_endpoint_ids_and_writes_explicit_image_inputs(tmp_path: Path) -> None:
    directory, prepared, initial, _ = _prepare(tmp_path)
    assert prepared["schema"] == "mlcc.lammps-neb-input.v1"
    assert prepared["production_qualification"] is False
    assert (directory / "model.data").is_file()
    assert (directory / "atom-map.json").is_file()
    assert (directory / "neb-input.json").is_file()
    assert all("final.coords" not in str(item) for item in prepared.get("files", []))
    assert all("final.coords" not in str(item) for item in prepared.get("transfer_paths", []))
    assert all("final.coords" not in str(item) for item in prepared.get("collect_paths", []))
    assert all("endpoint-start.lammpstrj" not in str(item) for item in prepared.get("collect_paths", []))
    image_data_paths = [directory / "images" / f"image-{index}" / "model.data" for index in range(3)]
    image_map_paths = [directory / "images" / f"image-{index}" / "atom-map.json" for index in range(3)]
    assert all(path.is_file() for path in image_data_paths)
    assert all(path.is_file() for path in image_map_paths)
    assert not any("final.coords" in str(path) for path in directory.rglob("*"))

    atom_map = json.loads((directory / "atom-map.json").read_text(encoding="utf-8"))
    native_ids = {int(item["source_atom_id"]): int(item["lammps_id"]) for item in atom_map["atoms"]}
    input_text = (directory / "in.lammps").read_text(encoding="utf-8")
    assert "variable replica world 0 1 2" in input_text
    assert f"group neb_atoms id {' '.join(str(native_ids[atom_id]) for atom_id in initial.atom_ids)}" in input_text
    assert "read_data images/image-${replica}/model.data" in input_text
    assert "min_style cg" in input_text
    assert "min_style quickmin" in input_text
    assert "min_modify norm two" in input_text
    assert "thermo_modify norm no" in input_text
    assert "fix neb neb_atoms neb 1 parallel neigh" in input_text
    assert "neb 0 0.05 6 4 2 none verbosity verbose" in input_text
    assert "partition yes 1 minimize 0 0.05 200 1000" in input_text
    assert "partition yes 3 minimize 0 0.05 200 1000" in input_text
    assert "endpoint-final.lammpstrj" in input_text
    assert "endpoint-start.lammpstrj" not in input_text
    assert "reset_timestep 0" in input_text
    assert "write_dump all custom images/image-${replica}/final.lammpstrj id type xu yu zu fx fy fz" in input_text
    assert "final.coords" not in input_text
    assert "neb/spin" not in input_text
    minimization_index = input_text.index("minimize")
    endpoint_dump_index = input_text.index("partition yes 1 write_dump")
    reset_index = input_text.index("reset_timestep 0")
    fix_index = input_text.index("fix neb neb_atoms neb")
    neb_index = input_text.index("\nneb ")
    assert minimization_index < endpoint_dump_index < reset_index < fix_index < neb_index
    expected_native_ids = sorted(native_ids.values())
    for image_data_path, image_map_path in zip(image_data_paths, image_map_paths):
        assert _data_atom_ids(image_data_path) == expected_native_ids
        assert json.loads(image_map_path.read_text(encoding="utf-8")) == atom_map

    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    assert method["model_id"] == initial.model_id
    assert all(
        "endpoint-start.lammpstrj" not in str(value)
        for value in method["files"].get("endpoint_dumps", {}).values()
    )
    assert method["protocol"]["endpoint_minimization"] == {
        "min_style": "cg",
        "etol": 0.0,
        "ftol_eV_per_angstrom": 0.05,
        "max_iterations": 200,
        "max_evaluations": 1000,
    }
    displacements = {int(item["source_atom_id"]): item for item in method["endpoint_displacements"]}
    assert set(displacements) == set(initial.atom_ids)
    assert displacements[13]["final_source_position_angstrom"][0] > float(initial.atoms.cell[0, 0])
    assert displacements[13]["selected_displacement_angstrom"][0] == pytest.approx(0.60)

    image_records = json.loads((directory / "neb-input.json").read_text(encoding="utf-8"))["image_records"]
    assert [record["fraction"] for record in image_records] == [0.0, 0.5, 1.0]
    for record in image_records:
        assert {int(item["source_atom_id"]) for item in record["atom_displacements"]} == set(initial.atom_ids)
    final_record = {
        int(item["source_atom_id"]): item
        for item in image_records[-1]["atom_displacements"]
    }
    assert final_record[13]["image_position_angstrom"][0] == pytest.approx(
        displacements[13]["selected_final_position_angstrom"][0]
    )


def test_prepare_rejects_unknown_neb_atom_id_and_missing_shift(tmp_path: Path) -> None:
    initial, final = _models(tmp_path)
    protocol = _protocol()
    protocol["neb_atom_ids"] = [999]
    with pytest.raises(ValueError, match="unknown"):
        prepare_lammps_neb(
            initial,
            final,
            tmp_path / "bad-neb-id",
            potential=_potential(tmp_path),
            protocol=protocol,
        )

    protocol = _protocol()
    protocol["final_image_shifts"] = protocol["final_image_shifts"][:-1]
    with pytest.raises(ValueError, match="cover every endpoint"):
        prepare_lammps_neb(
            initial,
            final,
            tmp_path / "bad-shifts",
            potential=_potential(tmp_path),
            protocol=protocol,
        )


def test_neb_task_records_explicit_mpi_partition_without_submitting(tmp_path: Path) -> None:
    initial, final = _models(tmp_path)
    potential = _potential(tmp_path)
    protocol = _protocol()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    study = {
        "study_id": "czo-vacancy-neb-study-v001",
        "case_id": "czo_vacancy_neb",
        "case_role": "engineering_fixture",
        "model": {
            "model_id": initial.model_id,
            "version": initial.version,
            "path": str(initial.artifact_dir.resolve()),
        },
    }
    site = {
        "ssh": {"alias": "v100"},
        "workspace": {"local": str(workspace), "remote_root": "/home/v100/projects/mlcc"},
        "runner": {"selected": "slurm"},
        "lammps": {
            "binary": "/home/v100/projects/mlcc/.venv-lammps/bin/lmp",
            "version": "LAMMPS (22 Jul 2025 - Update 4)",
            "environment_script": "/home/v100/projects/mlcc/lammps-env.sh",
            "launch_prefix": ["mpirun", "-np", "6"],
            "launch_arguments": [],
        },
    }
    request = {
        "task_id": "czo-vacancy-neb-v001",
        "required_results": [],
        "resource_request": {
            "nodes": 1,
            "partition": "cpu",
            "ntasks": 6,
            "cpus_per_task": 1,
            "mem_mib": 4096,
            "time": "00:10:00",
        },
    }
    paths = {
        "study": tmp_path / "study.json",
        "potential": tmp_path / "potential.json",
        "protocol": tmp_path / "protocol.json",
        "site": tmp_path / "site.json",
        "request": tmp_path / "request.json",
    }
    paths["study"].write_text(json.dumps(study, indent=2) + "\n", encoding="utf-8")
    paths["potential"].write_text(json.dumps(potential, indent=2) + "\n", encoding="utf-8")
    paths["protocol"].write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
    paths["site"].write_text(json.dumps(site, indent=2) + "\n", encoding="utf-8")
    paths["request"].write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")

    task = create_lammps_neb_task(
        study_path=paths["study"],
        model_path=initial.artifact_dir,
        final_model_path=final.artifact_dir,
        potential_path=paths["potential"],
        protocol_path=paths["protocol"],
        site_path=paths["site"],
        request_path=paths["request"],
    )
    assert task["status"] == "defined"
    assert task["scheduler_job_id"] is None
    assert task["resource_request"]["ntasks"] == 6
    assert task["command"][:4] == ["mpirun", "-np", "6", "/home/v100/projects/mlcc/.venv-lammps/bin/lmp"]
    assert "-partition" in task["command"]
    assert "3x2" in task["command"]
    for image_index in range(3):
        assert f"images/image-{image_index}/model.data" in task["transfer_paths"]
        assert f"images/image-{image_index}/atom-map.json" in task["transfer_paths"]
    assert task["production_qualification"] is False


def _dump_text(atom_map: dict, *, step: int = 10) -> str:
    lx, ly, lz, xy, xz, yz = [float(value) for value in atom_map["lammps_prism"]]
    xlo_bound = min(0.0, xy, xz, xy + xz)
    xhi_bound = lx + max(0.0, xy, xz, xy + xz)
    ylo_bound = min(0.0, yz)
    yhi_bound = ly + max(0.0, yz)
    rows = []
    for item in atom_map["atoms"]:
        atom_id = int(item["lammps_id"])
        atom_type = int(item["type"])
        rows.append(f"{atom_id} {atom_type} 0.0 0.0 0.0 0.0 0.0 0.0")
    return "\n".join(
        [
            "ITEM: TIMESTEP",
            str(step),
            "ITEM: NUMBER OF ATOMS",
            str(len(rows)),
            "ITEM: BOX BOUNDS xy xz yz pp pp pp",
            f"{xlo_bound:.16g} {xhi_bound:.16g} {xy:.16g}",
            f"{ylo_bound:.16g} {yhi_bound:.16g} {xz:.16g}",
            f"0.0 {lz:.16g} {yz:.16g}",
            "ITEM: ATOMS id type xu yu zu fx fy fz",
            *rows,
            "",
        ]
    )


def _master_log(*, images: int = 3) -> str:
    header = "Step MaxReplicaForce MaxAtomForce GradV0 GradV1 GradVc EBF EBR RDT " + " ".join(
        f"RD{index} PE{index}" for index in range(1, images + 1)
    )
    energies = [0.0, 0.4, 0.45]
    row = "6 0.0001 0.0001 0.1 0.2 0.3 0.40 -0.05 1.0 " + " ".join(
        f"{(index - 1) / (images - 1):.6g} {energies[index - 1]:.6g}" for index in range(1, images + 1)
    )
    for index in range(1, images + 1):
        header += f" pathangle{index} angletangrad{index} anglegrad{index} gradV{index} RepForce{index} MaxAtomForce{index}"
        row += " 180 90 nan 0.11 0.0001 0.0001"
    # The second header is the native transition printed after ``Climbing
    # replica = ...``; per-replica stop evidence is varied independently.
    climbing_row = "10 " + row.split(" ", 1)[1]
    return "\n".join(["LAMMPS (22 Jul 2025 - Update 2)", header, row, "Climbing replica = 2", header, climbing_row, ""])


def _stats_block(stopping: str, *, iterations: int, force_evaluations: int) -> list[str]:
    return [
        "Minimization stats:",
        f"  Stopping criterion = {stopping}",
        "  Energy initial, next-to-last, final = 0.0 0.0 0.0",
        "  Force two-norm initial, final = 1.0 0.0001",
        "  Force max component initial, final = 1.0 0.0001",
        f"  Iterations, force evaluations = {iterations} {force_evaluations}",
        "",
    ]


def _write_parser_fixture(
    tmp_path: Path,
    *,
    stopping: str = "force tolerance",
    endpoint_stopping: str | None = None,
    regular_stopping: str | None = None,
    climbing_stopping: str | None = None,
) -> Path:
    directory, _prepared, _initial, _final = _prepare(tmp_path)
    atom_map = json.loads((directory / "atom-map.json").read_text(encoding="utf-8"))
    (directory / "log.lammps").write_text(_master_log(), encoding="utf-8")
    endpoint_stopping = stopping if endpoint_stopping is None else endpoint_stopping
    regular_stopping = stopping if regular_stopping is None else regular_stopping
    climbing_stopping = stopping if climbing_stopping is None else climbing_stopping
    for index in range(3):
        records: list[str] = []
        if index in {0, 2}:
            records.extend(_stats_block(endpoint_stopping, iterations=200, force_evaluations=1000))
        records.extend(_stats_block(regular_stopping, iterations=6, force_evaluations=12))
        records.extend(_stats_block(climbing_stopping, iterations=4, force_evaluations=8))
        native_echo = (directory / "in.lammps").read_text(encoding="utf-8").replace("${replica}", str(index))
        stats = "LAMMPS (22 Jul 2025 - Update 2)\n" + native_echo + "\n" + "\n".join(records)
        (directory / f"log.lammps.{index}").write_text(stats, encoding="utf-8")
        image_directory = directory / "images" / f"image-{index}"
        image_directory.mkdir(parents=True, exist_ok=True)
        (image_directory / "final.lammpstrj").write_text(
            _dump_text(atom_map, step=10), encoding="utf-8"
        )
        if index in {0, 2}:
            (image_directory / "endpoint-final.lammpstrj").write_text(
                _dump_text(atom_map, step=200), encoding="utf-8"
            )
    return directory


def test_parser_preserves_two_phases_barriers_and_neb_time_semantics(tmp_path: Path) -> None:
    result = parse_lammps_neb_outputs(_write_parser_fixture(tmp_path, stopping="force tolerance"))
    assert result["schema"] == NEB_RESULT_SCHEMA
    assert result["mode"] == "neb_path"
    assert result["time_ps"] is None
    assert result["path_provenance"]["path_id"] == "czo-neb-math-engineering-fixture"
    assert result["native_converged"] is True
    assert result["stopping"]["phase_converged"] == {"endpoint": True, "regular": True, "climbing": True}
    assert len(result["stopping"]["endpoint"]) == 2
    assert all(item["stopping_criterion"] == "force tolerance" for item in result["stopping"]["endpoint"])
    assert all(item["phase"] == "endpoint" for item in result["stopping"]["endpoint"])
    assert all(item["phase"] == "regular" for item in result["stopping"]["regular"])
    assert all(item["phase"] == "climbing" for item in result["stopping"]["climbing"])
    assert result["regular_native_converged"] is True
    assert result["climbing_native_converged"] is True
    assert result["path_endpoint_converged"] is True
    assert len(result["history"]["regular"]) == 1
    assert len(result["history"]["climbing"]) == 1
    assert all(
        all(f"{field}{image}" in result["history"]["climbing"][0] for field in ("pe", "rd"))
        for image in range(1, 4)
    )
    assert result["barrier"]["forward_eV"] == pytest.approx(0.40)
    assert result["barrier"]["backward_eV"] == pytest.approx(-0.05)
    assert result["history"]["climbing"][0]["gradient_final"] == pytest.approx(0.2)
    assert result["history"]["climbing"][0]["gradv1"] == pytest.approx(0.11)
    assert result["barrier"]["climbing_replica"] == 2
    assert result["barrier"]["highest_final_image"] == 3
    assert result["barrier"]["highest_image_is_climbing_replica"] is False
    assert result["barrier"]["highest_final_image_is_endpoint"] is True
    assert "diffusion_coefficient" not in result
    assert "rate" not in result
    assert result["production_qualification"] is False
    assert all("final.coords" not in str(value) for value in result["source_files"].values())
    assert len(result["image_dumps"]) == 3
    assert [dump["reaction_coordinate"] for dump in result["image_dumps"]] == pytest.approx([0.0, 0.5, 1.0])
    assert [dump["energy_eV"] for dump in result["image_dumps"]] == pytest.approx([0.0, 0.4, 0.45])
    assert all(dump["mode"] == "neb_path" and dump["time_ps"] is None for dump in result["image_dumps"])
    assert all(dump["force_semantics"] == "native_total_including_fix_neb" for dump in result["image_dumps"])
    assert all(row["forces_eV_per_angstrom"] == [0.0, 0.0, 0.0] for dump in result["image_dumps"] for row in dump["rows"])


def test_parser_native_convergence_follows_climbing_and_preserves_endpoint_failure(tmp_path: Path) -> None:
    result = parse_lammps_neb_outputs(
        _write_parser_fixture(
            tmp_path,
            endpoint_stopping="iteration limit reached",
            regular_stopping="iteration limit reached",
            climbing_stopping="force tolerance",
        )
    )
    assert result["native_converged"] is True
    assert result["climbing_native_converged"] is True
    assert result["regular_native_converged"] is False
    assert result["path_endpoint_converged"] is False
    assert result["stopping"]["phase_converged"] == {"endpoint": False, "regular": False, "climbing": True}
    assert all(item["stopping_criterion"] == "iteration limit reached" for item in result["stopping"]["endpoint"])
    assert result["production_qualification"] is False


def test_parser_keeps_iteration_exhaustion_as_unconverged_candidate(tmp_path: Path) -> None:
    result = parse_lammps_neb_outputs(_write_parser_fixture(tmp_path, stopping="iteration limit reached"))
    assert result["native_converged"] is False
    assert result["scientific_status"] == "neb_native_unconverged"
    assert result["stopping"]["phase_converged"] == {"endpoint": False, "regular": False, "climbing": False}
    assert result["barrier"]["forward_eV"] == pytest.approx(0.40)
    assert result["barrier"]["backward_eV"] == pytest.approx(-0.05)


def test_parser_rejects_missing_image_dump_instead_of_fabricating_output(tmp_path: Path) -> None:
    directory = _write_parser_fixture(tmp_path, stopping="force tolerance")
    (directory / "images" / "image-2" / "final.lammpstrj").unlink()
    with pytest.raises(FileNotFoundError, match="image-2.*final"):
        parse_lammps_neb_outputs(directory)


def test_parser_rejects_missing_partition_log_or_endpoint_stats_or_wrong_map(tmp_path: Path) -> None:
    missing_log = _write_parser_fixture(tmp_path / "missing-log", stopping="force tolerance")
    (missing_log / "log.lammps.1").unlink()
    with pytest.raises(FileNotFoundError, match=r"log\.lammps\.1"):
        parse_lammps_neb_outputs(missing_log)

    missing_stats = _write_parser_fixture(tmp_path / "missing-stats", stopping="force tolerance")
    (missing_stats / "log.lammps.2").write_text(
        "\n".join(_stats_block("force tolerance", iterations=6, force_evaluations=12) * 2),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="minimization stats blocks"):
        parse_lammps_neb_outputs(missing_stats)

    wrong_map = _write_parser_fixture(tmp_path / "wrong-map", stopping="force tolerance")
    map_path = wrong_map / "images" / "image-1" / "atom-map.json"
    image_map = json.loads(map_path.read_text(encoding="utf-8"))
    image_map["atoms"][0]["source_atom_id"] = 999
    map_path.write_text(json.dumps(image_map) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="atom map"):
        parse_lammps_neb_outputs(wrong_map)


def test_parser_rejects_final_dump_step_mismatch(tmp_path: Path) -> None:
    directory = _write_parser_fixture(tmp_path, stopping="force tolerance")
    atom_map = json.loads((directory / "atom-map.json").read_text(encoding="utf-8"))
    (directory / "images" / "image-2" / "final.lammpstrj").write_text(
        _dump_text(atom_map, step=7),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="step differs"):
        parse_lammps_neb_outputs(directory)

