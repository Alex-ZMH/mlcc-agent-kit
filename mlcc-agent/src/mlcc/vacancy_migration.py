"""Local oxygen-vacancy site assignment and adjacent-frame migration events.

The function in this module only compares supplied coordinates with fixed
mother-lattice sites.  It does not unwrap trajectories, fit rates or
diffusion coefficients, and it never bridges an unresolved frame.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

import numpy as np
from ase.geometry import find_mic


SCHEMA = "mlcc.vacancy-migration.v1"


def _number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return result


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    result = int(value)
    if result < 1:
        raise ValueError(f"{name} must be at least 1")
    return result


def _ids(value: Any, name: str, *, allow_empty: bool = False) -> list[int]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence of integer IDs")
    result: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, np.integer)):
            raise ValueError(f"{name}[{index}] must be an integer ID")
        result.append(int(item))
    if not allow_empty and not result:
        raise ValueError(f"{name} must not be empty")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must contain unique IDs")
    return result


def _array(value: Any, shape: tuple[int, ...], name: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != shape:
        raise ValueError(f"{name} must have shape {shape}")
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must contain finite values")
    return result


def _unknown_occupancy(site_ids: Sequence[int]) -> list[dict[str, Any]]:
    return [
        {"site_atom_id": int(site_id), "status": "unknown", "occupants": []}
        for site_id in site_ids
    ]


def _frame_mode_fields(frame: Mapping[str, Any], mode: str) -> tuple[dict[str, Any], list[str]]:
    fields: dict[str, Any] = {}
    reasons: list[str] = []
    if mode == "md_time":
        if "step" not in frame:
            reasons.append("missing step")
        else:
            step = frame["step"]
            if isinstance(step, bool) or not isinstance(step, (int, np.integer)):
                raise ValueError("frame.step must be an integer")
            fields["step"] = int(step)
        if "physical_time_ps" not in frame or frame["physical_time_ps"] is None:
            reasons.append("missing physical_time_ps")
        else:
            fields["physical_time_ps"] = _number(frame["physical_time_ps"], "frame.physical_time_ps")
    else:
        if "image_index" not in frame:
            reasons.append("missing image_index")
        else:
            image_index = frame["image_index"]
            if isinstance(image_index, bool) or not isinstance(image_index, (int, np.integer)):
                raise ValueError("frame.image_index must be an integer")
            fields["image_index"] = int(image_index)
        if "reaction_coordinate" not in frame:
            reasons.append("missing reaction_coordinate")
        else:
            fields["reaction_coordinate"] = _number(frame["reaction_coordinate"], "frame.reaction_coordinate")
        if frame.get("physical_time_ps") is not None:
            reasons.append("neb physical_time_ps must be null")
        fields["physical_time_ps"] = None
    return fields, reasons


def _candidate_record(
    site_id: int,
    distance: float,
    image: Sequence[int],
    radius: float,
) -> dict[str, Any]:
    return {
        "site_atom_id": int(site_id),
        "distance_angstrom": float(distance),
        "site_image": [int(value) for value in image],
        "within_radius": bool(distance <= radius),
    }


def _assign_frame(
    frame: Mapping[str, Any],
    frame_index: int,
    *,
    site_ids: Sequence[int],
    site_positions: np.ndarray,
    cell: np.ndarray,
    inverse_cell: np.ndarray,
    pbc: Sequence[bool],
    mobile_ids: Sequence[int],
    mode: str,
    radius: float,
    ambiguity_tolerance: float,
) -> dict[str, Any]:
    fields, reasons = _frame_mode_fields(frame, mode)
    if frame.get("coordinate_basis") != "source_cartesian":
        reasons.append("coordinate_basis must be source_cartesian")
    result: dict[str, Any] = {
        "frame_index": int(frame_index),
        "source_frame": copy.deepcopy(dict(frame)),
        **fields,
        "status": "unresolved",
        "assignments": [],
        "atom_candidates": [],
        "site_occupancy": _unknown_occupancy(site_ids),
        "vacancy_site_atom_ids": None,
        "vacancy_position_angstrom": None,
        "unresolved_reasons": list(reasons),
    }
    source_ids_value = frame.get("source_atom_ids")
    positions_value = frame.get("positions_angstrom")
    if source_ids_value is not None:
        result["source_atom_ids"] = copy.deepcopy(source_ids_value)
    if positions_value is not None:
        result["positions_angstrom"] = copy.deepcopy(positions_value)
    if source_ids_value is None:
        result["unresolved_reasons"].append("missing source_atom_ids")
    if positions_value is None:
        result["unresolved_reasons"].append("missing positions_angstrom")
    if source_ids_value is None or positions_value is None or frame.get("coordinate_basis") != "source_cartesian":
        return result
    source_ids = _ids(source_ids_value, f"frames[{frame_index}].source_atom_ids")
    positions = _array(positions_value, (len(source_ids), 3), f"frames[{frame_index}].positions_angstrom")
    position_by_id = {atom_id: positions[index] for index, atom_id in enumerate(source_ids)}
    missing_mobile = [atom_id for atom_id in mobile_ids if atom_id not in position_by_id]
    for atom_id in missing_mobile:
        result["atom_candidates"].append({
            "mobile_atom_id": int(atom_id),
            "status": "unresolved",
            "reason": "mobile atom ID is missing from frame",
            "candidates": [],
        })
        result["assignments"].append({
            "mobile_atom_id": int(atom_id),
            "status": "unresolved",
            "reason": "mobile atom ID is missing from frame",
        })
        result["unresolved_reasons"].append(f"mobile atom {atom_id} is missing from frame")
    occupied: dict[int, list[dict[str, Any]]] = {int(site_id): [] for site_id in site_ids}
    for atom_id in mobile_ids:
        if atom_id not in position_by_id:
            continue
        candidates: list[dict[str, Any]] = []
        for site_id, site_position in zip(site_ids, site_positions):
            delta = position_by_id[atom_id] - site_position
            mic_vector, mic_distance = find_mic(
                delta.reshape(1, 3), cell=cell, pbc=np.asarray(pbc, dtype=bool)
            )
            mic_delta = np.asarray(mic_vector, dtype=float).reshape(-1, 3)[0]
            distance = float(np.asarray(mic_distance, dtype=float).reshape(-1)[0])
            image = np.rint((delta - mic_delta) @ inverse_cell).astype(int).tolist()
            candidates.append(_candidate_record(site_id, distance, image, radius))
        candidates.sort(key=lambda item: (item["distance_angstrom"], item["site_atom_id"]))
        nearest = candidates[0]
        if not nearest["within_radius"]:
            status = "unresolved"
            reason = "no site candidate within assignment radius"
        elif len(candidates) > 1 and candidates[1]["distance_angstrom"] - nearest["distance_angstrom"] <= ambiguity_tolerance:
            status = "unresolved"
            reason = "nearest and second-nearest site distances are ambiguous"
        else:
            status = "resolved"
            reason = None
        atom_record: dict[str, Any] = {
            "mobile_atom_id": int(atom_id),
            "status": status,
            "candidates": candidates,
            "nearest_candidate": copy.deepcopy(nearest),
        }
        assignment: dict[str, Any] = {"mobile_atom_id": int(atom_id), "status": status}
        if status == "resolved":
            site_id = int(nearest["site_atom_id"])
            assignment.update({
                "site_atom_id": site_id,
                "site_image": copy.deepcopy(nearest["site_image"]),
                "distance_angstrom": nearest["distance_angstrom"],
            })
            occupied[site_id].append({
                "mobile_atom_id": int(atom_id),
                "site_image": copy.deepcopy(nearest["site_image"]),
                "distance_angstrom": nearest["distance_angstrom"],
            })
        else:
            assignment["reason"] = reason
            atom_record["reason"] = reason
            result["unresolved_reasons"].append(f"mobile atom {atom_id}: {reason}")
        result["atom_candidates"].append(atom_record)
        result["assignments"].append(assignment)
    result["site_occupancy"] = [
        {
            "site_atom_id": int(site_id),
            "status": "occupied" if occupants else "vacant",
            "occupants": occupants,
        }
        for site_id, occupants in occupied.items()
    ]
    duplicate_sites = [site_id for site_id, occupants in occupied.items() if len(occupants) > 1]
    missing_sites = [site_id for site_id, occupants in occupied.items() if not occupants]
    result["unoccupied_site_atom_ids"] = missing_sites
    for site_id in duplicate_sites:
        result["unresolved_reasons"].append(f"multiple mobile atoms occupy site {site_id}")
    if len(missing_sites) != 1:
        result["unresolved_reasons"].append(f"expected exactly one vacancy, found {len(missing_sites)}")
    if not result["unresolved_reasons"] and len(result["assignments"]) == len(mobile_ids):
        result["status"] = "resolved"
        result["vacancy_site_atom_id"] = int(missing_sites[0])
        result["vacancy_site_atom_ids"] = missing_sites
        result["vacancy_position_angstrom"] = site_positions[list(site_ids).index(missing_sites[0])].tolist()
    return result


def _transition(
    old: Mapping[str, Any],
    new: Mapping[str, Any],
    *,
    mobile_ids: Sequence[int],
    mode: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if old["status"] != "resolved" or new["status"] != "resolved":
        return None, {
            "from_frame_index": old["frame_index"],
            "to_frame_index": new["frame_index"],
            "status": "unresolved",
            "reason": "transition endpoint is unresolved",
        }
    old_by_atom = {item["mobile_atom_id"]: item["site_atom_id"] for item in old["assignments"]}
    new_by_atom = {item["mobile_atom_id"]: item["site_atom_id"] for item in new["assignments"]}
    changed = [
        (atom_id, old_by_atom[atom_id], new_by_atom[atom_id])
        for atom_id in mobile_ids
        if old_by_atom[atom_id] != new_by_atom[atom_id]
    ]
    if not changed:
        return None, None
    old_vacancy = old["vacancy_site_atom_id"]
    new_vacancy = new["vacancy_site_atom_id"]
    if len(changed) != 1 or changed[0][1:] != (new_vacancy, old_vacancy):
        return None, {
            "from_frame_index": old["frame_index"],
            "to_frame_index": new["frame_index"],
            "status": "unresolved",
            "reason": "site changes do not represent one vacancy move",
            "changed_assignments": [
                {"mobile_atom_id": atom, "old_site_atom_id": old_site, "new_site_atom_id": new_site}
                for atom, old_site, new_site in changed
            ],
        }
    atom_id, old_site, new_site = changed[0]
    event: dict[str, Any] = {
        "status": "resolved",
        "from_frame_index": old["frame_index"],
        "to_frame_index": new["frame_index"],
        "old_vacancy_site_atom_id": int(old_vacancy),
        "new_vacancy_site_atom_id": int(new_vacancy),
        "moving_atom_id": int(atom_id),
        "moving_atom_old_site_atom_id": int(old_site),
        "moving_atom_new_site_atom_id": int(new_site),
        "observation": "change between adjacent resolved frames; jump time is not inferred",
    }
    if mode == "md_time":
        event.update({
            "step_from": old["step"],
            "step_to": new["step"],
            "physical_time_ps_from": old["physical_time_ps"],
            "physical_time_ps_to": new["physical_time_ps"],
        })
    else:
        event.update({
            "image_index_from": old["image_index"],
            "image_index_to": new["image_index"],
            "reaction_coordinate_from": old["reaction_coordinate"],
            "reaction_coordinate_to": new["reaction_coordinate"],
        })
    return event, None


def _assignment_signature(frame: Mapping[str, Any]) -> tuple[tuple[Any, ...], ...]:
    return tuple(sorted(
        (
            int(item["mobile_atom_id"]),
            item["status"],
            int(item["site_atom_id"]),
        )
        for item in frame["assignments"]
    ))


def _unconfirmed_transition(
    candidate: Mapping[str, Any],
    *,
    reason: str,
    confirmation_frames: int,
    confirmation_frame_indices: Sequence[int],
    failed_frame_index: int | None = None,
) -> dict[str, Any]:
    transition = {
        "from_frame_index": candidate["from_frame_index"],
        "to_frame_index": candidate["to_frame_index"],
        "status": "unresolved",
        "reason": reason,
        "not_confirmed": True,
        "required_confirmation_frames": int(confirmation_frames),
        "confirmation_frame_indices": [int(index) for index in confirmation_frame_indices],
        "candidate_event": copy.deepcopy(dict(candidate)),
    }
    if failed_frame_index is not None:
        transition["failed_confirmation_frame_index"] = int(failed_frame_index)
    return transition


def analyze_vacancy_frames(
    frames: Sequence[Mapping[str, Any]],
    *,
    site_atom_ids: Sequence[int],
    site_positions_angstrom: Sequence[Sequence[float]],
    cell_angstrom: Sequence[Sequence[float]],
    pbc: Sequence[bool],
    mobile_atom_ids: Sequence[int],
    mode: str,
    assignment_radius_angstrom: float,
    ambiguity_tolerance_angstrom: float,
    confirmation_frames: int,
) -> dict[str, Any]:
    """Assign mobile oxygen atoms to fixed sites and confirm adjacent moves."""
    if isinstance(frames, (str, bytes)) or not isinstance(frames, Sequence) or not frames:
        raise ValueError("frames must be a non-empty sequence")
    if mode not in {"md_time", "neb_path"}:
        raise ValueError("mode must be 'md_time' or 'neb_path'")
    confirmation_count = _count(confirmation_frames, "confirmation_frames")
    site_ids = _ids(site_atom_ids, "site_atom_ids")
    mobile_ids = _ids(mobile_atom_ids, "mobile_atom_ids")
    site_positions = _array(site_positions_angstrom, (len(site_ids), 3), "site_positions_angstrom")
    cell = _array(cell_angstrom, (3, 3), "cell_angstrom")
    inverse_cell = np.linalg.inv(cell)
    if isinstance(pbc, (str, bytes)) or not isinstance(pbc, Sequence) or len(pbc) != 3:
        raise ValueError("pbc must contain three booleans")
    pbc_values: list[bool] = []
    for index, value in enumerate(pbc):
        if not isinstance(value, (bool, np.bool_)):
            raise ValueError(f"pbc[{index}] must be a boolean")
        pbc_values.append(bool(value))
    radius = _number(assignment_radius_angstrom, "assignment_radius_angstrom", minimum=0.0)
    ambiguity_tolerance = _number(ambiguity_tolerance_angstrom, "ambiguity_tolerance_angstrom", minimum=0.0)
    analyzed_frames: list[dict[str, Any]] = []
    for frame_index, frame in enumerate(frames):
        if not isinstance(frame, Mapping):
            raise ValueError(f"frames[{frame_index}] must be an object")
        analyzed_frames.append(_assign_frame(
            frame, frame_index, site_ids=site_ids, site_positions=site_positions,
            cell=cell, inverse_cell=inverse_cell, pbc=pbc_values,
            mobile_ids=mobile_ids, mode=mode, radius=radius,
            ambiguity_tolerance=ambiguity_tolerance,
        ))
    order_fields = ("step", "physical_time_ps") if mode == "md_time" else ("image_index",)
    for old, new in zip(analyzed_frames, analyzed_frames[1:]):
        for field in order_fields:
            if old.get(field) is not None and new.get(field) is not None and new[field] <= old[field]:
                new["status"] = "unresolved"
                new["unresolved_reasons"].append(f"{field} is not strictly increasing")
    events: list[dict[str, Any]] = []
    unresolved_transitions: list[dict[str, Any]] = []
    for pair_index, (old, new) in enumerate(zip(analyzed_frames, analyzed_frames[1:])):
        event, unresolved = _transition(old, new, mobile_ids=mobile_ids, mode=mode)
        if event is not None:
            required_end = pair_index + confirmation_count
            if required_end >= len(analyzed_frames):
                unresolved_transitions.append(_unconfirmed_transition(
                    event, reason="insufficient_frames", confirmation_frames=confirmation_count,
                    confirmation_frame_indices=list(range(pair_index + 1, len(analyzed_frames))),
                ))
                continue
            expected_signature = _assignment_signature(new)
            confirmation_indices = list(range(pair_index + 1, required_end + 1))
            failed_index = next(
                (
                    index for index in confirmation_indices
                    if analyzed_frames[index]["status"] != "resolved"
                    or _assignment_signature(analyzed_frames[index]) != expected_signature
                ),
                None,
            )
            if failed_index is not None:
                unresolved_transitions.append(_unconfirmed_transition(
                    event, reason="not_confirmed", confirmation_frames=confirmation_count,
                    confirmation_frame_indices=confirmation_indices, failed_frame_index=failed_index,
                ))
                continue
            event["confirmation_frame_indices"] = [int(index) for index in confirmation_indices]
            events.append(event)
        if unresolved is not None:
            unresolved_transitions.append(unresolved)
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": mode,
        "site_atom_ids": site_ids,
        "site_positions_angstrom": site_positions.tolist(),
        "mobile_atom_ids": mobile_ids,
        "cell_angstrom": cell.tolist(),
        "pbc": pbc_values,
        "assignment_radius_angstrom": radius,
        "ambiguity_tolerance_angstrom": ambiguity_tolerance,
        "confirmation_frames": confirmation_count,
        "vacancy_position_definition": "fixed host cell representative; global winding is not inferred",
        "site_image_definition": "nearest current-frame site image only; not trajectory unwrapping",
        "frames": analyzed_frames,
        "unresolved_transitions": unresolved_transitions,
        "status": "resolved"
        if all(frame["status"] == "resolved" for frame in analyzed_frames) and not unresolved_transitions
        else "unresolved",
    }
    result["jump_events" if mode == "md_time" else "site_changes"] = events
    return result



def _read_json(path):
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def _md_native_frames(directory):
    """Read only the saved dump and its existing mapping/time records."""
    from .lammps import _parse_dump

    atom_map = _read_json(directory / "atom-map.json")
    method = _read_json(directory / "method.json")
    conditions = _read_json(directory / "md-conditions.json")
    task = _read_json(directory / "task.json")
    if atom_map["units"] != "metal" or method["units"] != "metal":
        raise ValueError("vacancy MD coordinates require LAMMPS metal units")
    if method["protocol"] != conditions["protocol"]:
        raise ValueError("MD method and saved conditions have different protocols")
    if str(task["scheduler_job_id"]) != str(conditions["native_job"]["scheduler_job_id"]):
        raise ValueError("MD task and conditions have different native jobs")
    identity = (atom_map["model_id"], atom_map["version"])
    if identity != (method["model_id"], method["version"]) or identity != (
        conditions["model"]["model_id"], conditions["model"]["version"]
    ):
        raise ValueError("MD source model identities differ")
    entries = {int(item["lammps_id"]): item for item in atom_map["atoms"]}
    rotation = np.asarray(atom_map["rotation_matrix_ase_to_lammps"], dtype=float)
    origin = np.asarray(atom_map["lammps_origin_angstrom"], dtype=float)
    dt = method["protocol"].get("timestep_ps")
    recorded_dt = conditions["time"].get("timestep_ps")
    if dt is not None and recorded_dt is not None and float(dt) != float(recorded_dt):
        raise ValueError("MD method and saved conditions have different timesteps")
    time_available = dt is not None and recorded_dt is not None
    lines = (directory / "trajectory.lammpstrj").read_text(encoding="utf-8").splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == "ITEM: TIMESTEP"]
    if not starts:
        raise ValueError("MD trajectory is missing the native timestep header")
    frames = []
    first_step = None
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        step, rows = _parse_dump("\n".join(lines[start:end]) + "\n", atom_map)
        if first_step is None:
            first_step = step
        native_ids = [int(row[0]) for row in rows]
        source_ids = [entries[atom_id].get("source_atom_id") for atom_id in native_ids]
        native_positions = np.asarray([row[2] for row in rows], dtype=float)
        source_positions = (native_positions - origin) @ rotation.T
        frames.append({
            "frame_index": index, "step": step,
            "physical_time_ps": (step - first_step) * float(dt) if time_available else None,
            "time_source": "native STEP relative to first frame plus method/conditions timestep_ps",
            "source_atom_ids": source_ids if all(value is not None for value in source_ids) else None,
            "lammps_atom_ids": native_ids,
            "positions_angstrom": source_positions.tolist(), "coordinate_basis": "source_cartesian",
            "native_positions_angstrom": native_positions.tolist(),
            "native_coordinate_basis": "lammps_prism_cartesian",
            "native_image_flags": None, "native_unwrapped_positions_angstrom": None,
        })
    source = {
        "native_job": copy.deepcopy(conditions["native_job"]),
        "model": copy.deepcopy(conditions["model"]), "potential": copy.deepcopy(method["potential"]),
        "method": method, "conditions": conditions, "atom_map": atom_map,
        "task_id": task["task_id"], "method_set": task["method_set"],
        "study": copy.deepcopy(task["study"]),
        "wrapped_coordinates": True, "image_flags": "missing", "unwrap_evidence": "missing",
        "limitations": ["No continuous winding, net displacement or diffusion is reconstructed.",
                        "Unobserved motion between saved frames is not determined."],
        "source_files": {name: str(directory / name) for name in (
            "trajectory.lammpstrj", "atom-map.json", "method.json", "md-conditions.json", "task.json"
        )},
    }
    return frames, source, atom_map["source_cell_angstrom"]

def _neb_saved_frames(result_file):
    """Normalize saved NEB image output while retaining its complete native record."""
    native = _read_json(result_file)
    if native["schema"] != "mlcc.lammps-neb-result.v1" or native["mode"] != "neb_path":
        raise ValueError("vacancy path requires a saved LAMMPS NEB result")
    if native["time_ps"] is not None:
        raise ValueError("NEB path must not carry MD time")
    frames = []
    cell = native["image_dumps"][0]["source_cell_angstrom"]
    for image in native["image_dumps"]:
        if image["time_ps"] is not None or image["mode"] != "neb_path":
            raise ValueError("NEB image must retain path mode with null time")
        if not np.allclose(image["source_cell_angstrom"], cell, rtol=0, atol=1e-8):
            raise ValueError("NEB images have different fixed cells")
        ids = [row["source_atom_id"] for row in image["rows"]]
        if ids != image["source_atom_ids"]:
            raise ValueError("NEB image rows differ from declared source atom mapping")
        frames.append({
            "image_index": image["image_index"], "reaction_coordinate": image["reaction_coordinate"],
            "minimization_step": image["step"], "energy_eV": image["energy_eV"],
            "physical_time_ps": None, "source_atom_ids": ids,
            "coordinate_basis": "source_cartesian",
            "positions_angstrom": [row["positions_angstrom"] for row in image["rows"]],
            "native_image": copy.deepcopy(image),
        })
    source = {
        "native_result": native, "model": {"model_id": native["model_id"], "version": native["version"]},
        "study": copy.deepcopy(native["study"]), "potential": copy.deepcopy(native["potential"]),
        "native_job": {name: native[name] for name in ("scheduler_job_id", "scheduler_state", "exit_code")},
        "source_files": {"neb_result": str(result_file)},
        "path_provenance": copy.deepcopy(native["path_provenance"]),
        "barrier": copy.deepcopy(native["barrier"]),
    }
    return frames, source, cell


def analyze_vacancy_migration_request(request_path):
    """Consume declared saved sources into one source-bound vacancy product."""
    import os
    from pathlib import Path
    from .md_rdf import _observation_frames
    from .modeling import read_model_artifacts

    request_file = Path(request_path).expanduser().resolve()
    request = _read_json(request_file)
    if request["schema"] != "mlcc.vacancy-migration-request.v1":
        raise ValueError("unsupported vacancy migration request")

    def path(value):
        return (request_file.parent / Path(value).expanduser()).resolve()

    study_file = path(request["study_path"])
    study = _read_json(study_file)
    host = read_model_artifacts(path(request["host_model_path"]))
    vacancy = read_model_artifacts(path(request["vacancy_model_path"]))
    model_ref = {"model_id": vacancy.model_id, "version": vacancy.version,
                 "path": str(vacancy.artifact_dir.resolve())}
    if (vacancy.model_id, vacancy.version) != (study["model"]["model_id"], study["model"]["version"]):
        raise ValueError("vacancy model differs from Study")
    if not np.allclose(host.atoms.cell.array, vacancy.atoms.cell.array, rtol=0, atol=1e-8):
        raise ValueError("fixed host and vacancy model cells differ")
    if not np.array_equal(host.atoms.pbc, vacancy.atoms.pbc):
        raise ValueError("fixed host and vacancy model PBC differ")
    host_by_id = {atom_id: index for index, atom_id in enumerate(host.atom_ids)}
    vacancy_by_id = {atom_id: index for index, atom_id in enumerate(vacancy.atom_ids)}
    site_ids = _ids(request["site_atom_ids"], "site_atom_ids")
    mobile_ids = _ids(request["mobile_atom_ids"], "mobile_atom_ids")
    host_symbols = host.atoms.get_chemical_symbols()
    vacancy_symbols = vacancy.atoms.get_chemical_symbols()
    if any(host_symbols[host_by_id[atom_id]] != "O" for atom_id in site_ids):
        raise ValueError("requested host sites must be oxygen")
    if any(vacancy_symbols[vacancy_by_id[atom_id]] != "O" for atom_id in mobile_ids):
        raise ValueError("requested mobile atoms must be oxygen")
    parent_file = path(request["parent_mapping_path"])
    parent_record = _read_json(parent_file)
    if (parent_record["model_id"], parent_record["model_version"]) != (vacancy.model_id, vacancy.version):
        raise ValueError("parent mapping record belongs to a different vacancy model")
    parent_mapping = parent_record.get("parent_mapping")
    missing_mapping = []
    if parent_mapping is None:
        missing_mapping.append("parent_mapping")
    else:
        mapped = {entry["child_atom_id"]: entry for entry in parent_mapping["entries"]}
        missing_mapping = [f"parent mapping for mobile atom {atom_id}" for atom_id in mobile_ids if atom_id not in mapped]
        for atom_id in mobile_ids:
            if atom_id in mapped and mapped[atom_id]["parent_atom_id"] not in site_ids:
                raise ValueError("mobile atom parent is outside the selected host oxygen sites")

    source_request = request["source"]
    if source_request["kind"] == "md_native":
        directory = path(source_request["directory"])
        frames, source, cell = _md_native_frames(directory)
        if (source["model"]["model_id"], source["model"]["version"]) != (vacancy.model_id, vacancy.version):
            raise ValueError("saved MD belongs to a different vacancy model")
        if source["study"]["study_id"] != study["study_id"]:
            raise ValueError("saved MD belongs to a different Study")
        frame_indices, frames = _observation_frames(frames, request["observation_window"])
        mode = "md_time"
    elif source_request["kind"] == "neb_result":
        frames, source, cell = _neb_saved_frames(path(source_request["path"]))
        if (source["model"]["model_id"], source["model"]["version"]) != (vacancy.model_id, vacancy.version):
            raise ValueError("saved NEB belongs to a different vacancy model")
        if source["study"]["study_id"] != study["study_id"]:
            raise ValueError("saved NEB belongs to a different Study")
        if request["observation_window"] != {"kind": "whole_record"}:
            raise ValueError("NEB vacancy analysis requires explicit whole_record image selection")
        frame_indices = [frame["image_index"] for frame in frames]
        mode = "neb_path"
    else:
        raise ValueError(f"unsupported vacancy source kind: {source_request['kind']}")
    if not np.allclose(cell, host.atoms.cell.array, rtol=0, atol=1e-8):
        raise ValueError("saved source cell differs from fixed host cell")
    source_refs = [str(request_file), str(study_file), str(host.artifact_dir.resolve()),
                   str(vacancy.artifact_dir.resolve()), str(parent_file), *source["source_files"].values()]
    common = {
        "schema": SCHEMA, "mode": mode,
        "study_id": study["study_id"], "case_id": study["case_id"], "case_role": study["case_role"],
        "model_ref": model_ref,
        "host_model_ref": {"model_id": host.model_id, "version": host.version, "path": str(host.artifact_dir.resolve())},
        "request": copy.deepcopy(request), "source_record": source,
        "parent_mapping": parent_mapping, "source_parent_record": parent_record, "source_refs": source_refs,
        "observation": {"request": request["observation_window"], "source_frame_indices": frame_indices},
        "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
    }
    if missing_mapping:
        return {**common, "status": "unresolved", "frames": None,
                "jump_events" if mode == "md_time" else "site_changes": None,
                "unresolved_reasons": missing_mapping}
    assignment = request["assignment"]
    result = analyze_vacancy_frames(
        frames, site_atom_ids=site_ids,
        site_positions_angstrom=[host.atoms.positions[host_by_id[atom_id]].tolist() for atom_id in site_ids],
        cell_angstrom=host.atoms.cell.array.tolist(), pbc=host.atoms.pbc.tolist(),
        mobile_atom_ids=mobile_ids, mode=mode,
        assignment_radius_angstrom=assignment["capture_radius_angstrom"],
        ambiguity_tolerance_angstrom=assignment["ambiguity_gap_angstrom"],
        confirmation_frames=assignment["confirmation_frames"],
    )
    return {**result, **common}


__all__ = ["SCHEMA", "analyze_vacancy_frames", "analyze_vacancy_migration_request"]
