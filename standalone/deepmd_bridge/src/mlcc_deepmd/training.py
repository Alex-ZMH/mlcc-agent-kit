"""DeePMD-kit PT training plan and single-node Slurm script generation.

The bridge prepares one explicit engineering training task.  It does not
submit or poll a job; the existing MLCC ``SiteRunner`` remains the scheduler
owner.  The only supported launch in this first slice is the DeePMD-kit
PyTorch-TorchScript backend with one process per visible GPU::

    torchrun --standalone --nnodes=1 --nproc-per-node=N --no-python \
        dp --pt train input.json

``nproc_per_node`` is intentionally limited to 1, 2, or 4 for the v100 node.
There is no CPU fallback, engine substitution, retry, or synthetic result.
The training seed, batch sizes, native command paths, checkpoint, freeze
output, resources, and native errors are retained in a small JSON manifest.

The deployment pin is passed as ``deepmd_kit_version`` and defaults to the
v3.2.0 PT runtime selected for the v100 site.  The site configuration still
owns the runtime/environment path; this module does not search for it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from pathlib import Path
import shlex
from typing import Any

import numpy as np


DEEPMD_KIT_VERSION = "3.2.0"
DEEPMD_BACKEND = "pt"
DEEPMD_TRAINING_ROUTE = "ABACUS->DeePMD-kit->LAMMPS"
DEEPMD_LAMMPS_PAIR_STYLE = "deepmd"
SUPPORTED_GPU_COUNTS = (1, 2, 4)


class TrainingConfigError(ValueError):
    """Raised when a training plan or its dataset gate is invalid."""


def _path_string(value: str | Path) -> str:
    return value.as_posix() if isinstance(value, Path) else str(value)


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TrainingConfigError(f"{name} must be a positive integer")
    return value


def _pt_checkpoint_path(save_prefix: str | Path) -> str:
    """Resolve DeePMD PT's published ``save_ckpt`` symlink path."""

    value = _path_string(save_prefix)
    return value if value.endswith(".pt") else f"{value}.pt"


def _resolve_system(input_json: Path, system: str | Path) -> Path:
    path = Path(system)
    if not path.is_absolute():
        path = input_json.parent / path
    return path


def _count_system_frames(input_json: Path, raw_system: str | Path) -> int:
    system = _resolve_system(input_json, raw_system)
    if not system.is_dir():
        raise TrainingConfigError(f"training system directory does not exist: {system}")
    set_dirs = sorted(item for item in system.glob("set.*") if item.is_dir())
    if not set_dirs:
        raise TrainingConfigError(f"training system has no set.* directories: {system}")
    system_frames = 0
    for set_dir in set_dirs:
        frame_file = set_dir / "coord.npy"
        if not frame_file.is_file():
            frame_file = set_dir / "energy.npy"
        if not frame_file.is_file():
            raise TrainingConfigError(f"training set has no coord.npy or energy.npy: {set_dir}")
        shape = np.load(frame_file, mmap_mode="r", allow_pickle=False).shape
        if not shape or shape[0] <= 0:
            raise TrainingConfigError(f"training set has no frames: {frame_file}")
        system_frames += int(shape[0])
    return system_frames


def count_training_frames(input_json: str | Path, systems: Sequence[str | Path]) -> int:
    """Count frames from DeePMD ``set.*/*.{coord,energy}.npy`` files.

    The count is used only as a launch gate.  It does not transform labels or
    infer a scientific validation result.  A system with one or more sets is
    valid for an engineering smoke test.  DeePMD-kit's PT loader constructs a
    ``torch.utils.data.DistributedSampler`` with its default ``drop_last=False``;
    PyTorch pads that sampler by repeating indices when a system has fewer
    frames than DDP workers.  Therefore the only data gate here is at least
    one frame.  The plan records that padding may replicate samples so an
    engineering run is not mistaken for a data-size or scientific result.
    """

    input_path = Path(input_json)
    total = sum(_count_system_frames(input_path, raw_system) for raw_system in systems)
    if total <= 0:
        raise TrainingConfigError("training systems contain no frames")
    return total


@dataclass(frozen=True)
class DeepMDTrainingConfig:
    """Explicit one-node PT/DDP configuration for an engineering test."""

    input_json: str | Path
    workdir: str | Path
    nproc_per_node: int
    local_batch_size: int
    seed: int
    checkpoint: str | Path = "model.ckpt"
    frozen_model: str | Path = "frozen_model"
    stop_batch: int | None = None
    training_systems: tuple[str, ...] = ()
    training_frame_count: int | None = None
    training_system_frame_counts: tuple[int, ...] = ()
    validation_systems: tuple[str, ...] = ()
    disp_file: str | Path = "lcurve.out"
    disp_freq: int = 100
    save_freq: int = 100
    deepmd_kit_version: str = DEEPMD_KIT_VERSION
    partition: str = "gpu"
    gres: str | None = None
    nodes: int = 1
    ntasks: int = 1
    cpus_per_task: int | None = None
    mem_mib: int | None = 16384
    time: str = "00:30:00"
    job_name: str = "mlcc-deepmd-train"
    stdout_log: str | Path = "stdout.log"
    stderr_log: str | Path = "stderr.log"
    status_file: str | Path = "training-status.json"
    manifest_file: str | Path = "training-manifest.json"
    environment_script: str | Path | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    restart_checkpoint: str | Path | None = None
    dp_executable: str = "dp"
    torchrun_executable: str = "torchrun"
    freeze: bool = True

    def __post_init__(self) -> None:
        if self.nproc_per_node not in SUPPORTED_GPU_COUNTS:
            raise TrainingConfigError(
                f"nproc_per_node must be one of {SUPPORTED_GPU_COUNTS}, got {self.nproc_per_node!r}"
            )
        _positive_int(self.local_batch_size, "local_batch_size")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TrainingConfigError("seed must be an explicit integer")
        if self.stop_batch is not None:
            _positive_int(self.stop_batch, "stop_batch")
        _positive_int(self.disp_freq, "disp_freq")
        _positive_int(self.save_freq, "save_freq")
        if self.training_frame_count is not None:
            _positive_int(self.training_frame_count, "training_frame_count")
        if self.nodes != 1 or self.ntasks != 1:
            raise TrainingConfigError("the standalone bridge requires nodes=1 and ntasks=1")
        if self.cpus_per_task is not None:
            _positive_int(self.cpus_per_task, "cpus_per_task")
        if self.mem_mib is not None:
            _positive_int(self.mem_mib, "mem_mib")
        if not self.partition:
            raise TrainingConfigError("partition must be non-empty")
        if not self.time:
            raise TrainingConfigError("time must be a finite Slurm time string")
        if not self.deepmd_kit_version:
            raise TrainingConfigError("deepmd_kit_version must be recorded")
        if self.cpus_per_task is None:
            object.__setattr__(self, "cpus_per_task", 4 * self.nproc_per_node)
        if self.gres is None:
            object.__setattr__(self, "gres", f"gpu:v100:{self.nproc_per_node}")
        if not self.gres:
            raise TrainingConfigError("gres must be non-empty")
        if self.training_systems and not isinstance(self.training_systems, tuple):
            object.__setattr__(self, "training_systems", tuple(str(item) for item in self.training_systems))
        if self.training_system_frame_counts and not isinstance(self.training_system_frame_counts, tuple):
            object.__setattr__(
                self,
                "training_system_frame_counts",
                tuple(int(item) for item in self.training_system_frame_counts),
            )
        for frame_count in self.training_system_frame_counts:
            _positive_int(frame_count, "training_system_frame_counts entry")
        if self.validation_systems and not isinstance(self.validation_systems, tuple):
            object.__setattr__(self, "validation_systems", tuple(str(item) for item in self.validation_systems))
        if set(self.training_systems).intersection(self.validation_systems):
            raise TrainingConfigError("validation systems must be separate paths from training systems")

    @property
    def global_batch_size(self) -> int:
        """The effective data-parallel batch size across all ranks."""

        return self.local_batch_size * self.nproc_per_node

    @property
    def threads_per_rank(self) -> int:
        assert self.cpus_per_task is not None
        return max(1, self.cpus_per_task // self.nproc_per_node)

    @property
    def replicated_samples(self) -> bool:
        """Whether PT DDP must pad sampler indices across ranks."""

        if self.training_system_frame_counts:
            return any(frame_count < self.nproc_per_node for frame_count in self.training_system_frame_counts)
        return self.training_frame_count is not None and self.training_frame_count < self.nproc_per_node

    def resource_request(self) -> dict[str, Any]:
        """Return the resource fields consumed by the existing SiteRunner."""

        resources: dict[str, Any] = {
            "nodes": self.nodes,
            "partition": self.partition,
            "ntasks": self.ntasks,
            "cpus_per_task": self.cpus_per_task,
            "gres": self.gres,
            "time": self.time,
            "job_name": self.job_name,
            "stdout_log": _path_string(self.stdout_log),
            "stderr_log": _path_string(self.stderr_log),
        }
        if self.mem_mib is not None:
            resources["mem_mib"] = self.mem_mib
        return resources

    def training_command(self) -> tuple[str, ...]:
        command: list[str] = [
            self.torchrun_executable,
            "--standalone",
            "--nnodes=1",
            f"--nproc-per-node={self.nproc_per_node}",
            "--no-python",
            self.dp_executable,
            "--pt",
            "train",
        ]
        if self.restart_checkpoint is not None:
            command.extend(("--restart", _path_string(self.restart_checkpoint)))
        command.append(_path_string(self.input_json))
        return tuple(command)

    def freeze_command(self) -> tuple[str, ...]:
        return (
            self.dp_executable,
            "--pt",
            "freeze",
            "-c",
            _path_string(self.checkpoint),
            "-o",
            _path_string(self.frozen_model),
        )

    def manifest(self) -> dict[str, Any]:
        return {
            "schema_version": "mlcc.deepmd.training.v1",
            "status": "planned",
            "scientific_status": "not_assessed",
            "scientific_qualification": False,
            "engine": "deepmd",
            "deepmd_kit_version": self.deepmd_kit_version,
            "backend": DEEPMD_BACKEND,
            "route": DEEPMD_TRAINING_ROUTE,
            "input_json": _path_string(self.input_json),
            "batch": {
                "local_per_rank": self.local_batch_size,
                "global": self.global_batch_size,
                "world_size": self.nproc_per_node,
            },
            "seed": self.seed,
            "stop_batch": self.stop_batch,
            "training_controls": {
                "disp_file": _path_string(self.disp_file),
                "disp_freq": self.disp_freq,
                "save_freq": self.save_freq,
            },
            "dataset": {
                "training_systems": list(self.training_systems),
                "training_frame_count": self.training_frame_count,
                "training_system_frame_counts": list(self.training_system_frame_counts),
                "minimum_frames_required": 1,
                "validation_systems": list(self.validation_systems),
                "validation_is_independent": bool(self.validation_systems),
            },
            "ddp_sampling": {
                "sampler": "torch.utils.data.DistributedSampler",
                "drop_last": False,
                "padding": "repeat_indices_to_equalize_rank_lengths",
                "replicated_samples": self.replicated_samples,
                "replication_is_engineering_only": self.replicated_samples,
            },
            "resources": self.resource_request(),
            "torchrun": {
                "command": list(self.training_command()),
                "nnodes": self.nodes,
                "nproc_per_node": self.nproc_per_node,
                "visible_device_policy": "one_LOCAL_RANK_per_CUDA_VISIBLE_DEVICES_entry",
            },
            "checkpoint": {
                "path_or_prefix": _path_string(self.checkpoint),
                "freeze_cli_accepts": "checkpoint_directory_or_prefix",
            },
            "freeze": {
                "enabled": self.freeze,
                "command": list(self.freeze_command()) if self.freeze else None,
                "output": _path_string(self.frozen_model) if self.freeze else None,
                "lammps_pair_style": DEEPMD_LAMMPS_PAIR_STYLE,
            },
            "logs": {
                "stdout": _path_string(self.stdout_log),
                "stderr": _path_string(self.stderr_log),
                "status": _path_string(self.status_file),
            },
            "native_results": {},
            "native_error": None,
        }

    @classmethod
    def from_input_json(
        cls,
        input_json: str | Path,
        *,
        workdir: str | Path,
        nproc_per_node: int,
        checkpoint: str | Path | None = None,
        **overrides: Any,
    ) -> "DeepMDTrainingConfig":
        """Build a plan from a DeePMD input and enforce the sample-count gate."""

        input_path = Path(input_json)
        try:
            raw = json.loads(input_path.read_text(encoding="utf-8"))
        except OSError as error:
            raise TrainingConfigError(f"cannot read DeePMD input JSON {input_path}: {error}") from error
        except json.JSONDecodeError as error:
            raise TrainingConfigError(f"invalid DeePMD input JSON {input_path}: {error}") from error
        if not isinstance(raw, dict) or not isinstance(raw.get("training"), dict):
            raise TrainingConfigError("DeePMD input JSON requires a training object")
        training = raw["training"]
        training_data = training.get("training_data")
        if not isinstance(training_data, dict):
            raise TrainingConfigError("training.training_data must be an object")
        systems = training_data.get("systems")
        if not isinstance(systems, list) or not systems or not all(isinstance(item, str) for item in systems):
            raise TrainingConfigError("training.training_data.systems must be a non-empty list of paths")
        batch = training_data.get("batch_size")
        _positive_int(batch, "training.training_data.batch_size")
        seed = training.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TrainingConfigError("training.seed must be an explicit integer")
        stop_batch = training.get("numb_steps")
        _positive_int(stop_batch, "training.numb_steps")
        frame_counts = tuple(_count_system_frames(input_path, item) for item in systems)
        frame_count = sum(frame_counts)
        validation_data = training.get("validation_data")
        if validation_data is None:
            validation = []
        elif isinstance(validation_data, dict):
            validation = validation_data.get("systems", [])
        else:
            raise TrainingConfigError("training.validation_data must be an object or null")
        if not isinstance(validation, list) or not all(isinstance(item, str) for item in validation):
            raise TrainingConfigError("training.validation_data.systems must be a list of paths")
        disp_freq = training.get("disp_freq", 100)
        save_freq = training.get("save_freq", 100)
        _positive_int(disp_freq, "training.disp_freq")
        _positive_int(save_freq, "training.save_freq")
        disp_file = training.get("disp_file", "lcurve.out")
        if not isinstance(disp_file, str) or not disp_file:
            raise TrainingConfigError("training.disp_file must be a non-empty path")
        resolved_train = {_resolve_system(input_path, item).resolve() for item in systems}
        resolved_validation = {_resolve_system(input_path, item).resolve() for item in validation}
        if resolved_train.intersection(resolved_validation):
            raise TrainingConfigError("validation systems must be separate paths from training systems")
        values = dict(overrides)
        values.update(
            input_json=input_json,
            workdir=workdir,
            nproc_per_node=nproc_per_node,
            local_batch_size=batch,
            seed=seed,
            stop_batch=stop_batch,
            checkpoint=(
                checkpoint
                if checkpoint is not None
                else _pt_checkpoint_path(training.get("save_ckpt", "model.ckpt"))
            ),
            training_systems=tuple(systems),
            training_frame_count=frame_count,
            training_system_frame_counts=frame_counts,
            validation_systems=tuple(validation),
            disp_file=disp_file,
            disp_freq=disp_freq,
            save_freq=save_freq,
        )
        return cls(**values)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DeepMDTrainingConfig":
        """Build from an explicit bridge mapping; no site discovery is done."""

        if not isinstance(value, Mapping):
            raise TrainingConfigError("training configuration must be an object")
        required = ("input_json", "workdir", "nproc_per_node", "local_batch_size", "seed")
        missing = [name for name in required if name not in value]
        if missing:
            raise TrainingConfigError("missing required training fields: " + ", ".join(missing))
        resources = value.get("resource_request", {})
        if not isinstance(resources, Mapping):
            raise TrainingConfigError("resource_request must be an object")
        kwargs = dict(value)
        kwargs.pop("resource_request", None)
        kwargs["partition"] = kwargs.get("partition", resources.get("partition", "gpu"))
        kwargs["gres"] = kwargs.get("gres", resources.get("gres"))
        kwargs["nodes"] = kwargs.get("nodes", resources.get("nodes", 1))
        kwargs["ntasks"] = kwargs.get("ntasks", resources.get("ntasks", 1))
        kwargs["cpus_per_task"] = kwargs.get("cpus_per_task", resources.get("cpus_per_task"))
        kwargs["mem_mib"] = kwargs.get("mem_mib", resources.get("mem_mib", 16384))
        kwargs["time"] = kwargs.get("time", resources.get("time", "00:30:00"))
        kwargs["job_name"] = kwargs.get("job_name", resources.get("job_name", "mlcc-deepmd-train"))
        kwargs["stdout_log"] = kwargs.get("stdout_log", resources.get("stdout_log", "stdout.log"))
        kwargs["stderr_log"] = kwargs.get("stderr_log", resources.get("stderr_log", "stderr.log"))
        return cls(**kwargs)


def prepare_training_input(
    *,
    systems: Sequence[str | Path],
    type_map: Sequence[str] = ("Ni",),
    batch_size: int = 1,
    seed: int = 20261022,
    stop_batch: int = 100,
    disp_freq: int = 10,
    save_freq: int = 100,
    save_ckpt: str | Path = "model.ckpt",
    disp_file: str | Path = "lcurve.out",
    validation_systems: Sequence[str | Path] = (),
    validation_batch_size: int = 1,
    validation_batches: int = 1,
) -> dict[str, Any]:
    """Return the canonical DeePMD-kit v3.2 PT training input mapping.

    This is the deliberately small engineering fixture used by the bridge:
    ``se_e2_a`` with the selected Ni settings, an explicit integer per-rank
    batch, 100 steps, and non-zero energy/force/virial loss weights.  The
    paths are copied as supplied; the caller chooses whether they are absolute
    or relative to the input file.  Validation is omitted unless paths are
    supplied, because one training system is a valid engineering fixture.
    """

    if isinstance(systems, (str, bytes)) or not systems:
        raise TrainingConfigError("systems must be a non-empty sequence of paths")
    if not all(isinstance(item, (str, Path)) and str(item) for item in systems):
        raise TrainingConfigError("systems must contain non-empty paths")
    if isinstance(type_map, (str, bytes)) or not type_map:
        raise TrainingConfigError("type_map must be a non-empty sequence of element names")
    if not all(isinstance(item, str) and item for item in type_map):
        raise TrainingConfigError("type_map must contain non-empty strings")
    _positive_int(batch_size, "batch_size")
    _positive_int(stop_batch, "stop_batch")
    _positive_int(disp_freq, "disp_freq")
    _positive_int(save_freq, "save_freq")
    _positive_int(validation_batch_size, "validation_batch_size")
    _positive_int(validation_batches, "validation_batches")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TrainingConfigError("seed must be an explicit integer")
    if not isinstance(disp_file, (str, Path)) or not str(disp_file):
        raise TrainingConfigError("disp_file must be a non-empty path")
    if not isinstance(save_ckpt, (str, Path)) or not str(save_ckpt):
        raise TrainingConfigError("save_ckpt must be a non-empty path prefix")
    if isinstance(validation_systems, (str, bytes)):
        raise TrainingConfigError("validation_systems must be a sequence of paths")
    if not all(isinstance(item, (str, Path)) and str(item) for item in validation_systems):
        raise TrainingConfigError("validation_systems must contain non-empty paths")

    input_value: dict[str, Any] = {
        "model": {
            "type_map": list(type_map),
            "descriptor": {
                "type": "se_e2_a",
                "sel": [128] * len(type_map),
                "rcut": 4.0,
                "rcut_smth": 3.5,
                "neuron": [8, 16, 32],
                "axis_neuron": 4,
                "precision": "float64",
            },
            "fitting_net": {
                "neuron": [32, 32],
                "precision": "float64",
            },
        },
        "learning_rate": {
            "type": "exp",
            "start_lr": 0.001,
            "stop_lr": 3.51e-8,
            "decay_steps": 5000,
        },
        "loss": {
            "type": "ener",
            "start_pref_e": 0.02,
            "limit_pref_e": 1.0,
            "start_pref_f": 1000.0,
            "limit_pref_f": 1.0,
            "start_pref_v": 0.02,
            "limit_pref_v": 1.0,
        },
        "training": {
            "training_data": {
                "systems": [_path_string(item) for item in systems],
                "batch_size": batch_size,
            },
            "numb_steps": stop_batch,
            "seed": seed,
            "disp_file": _path_string(disp_file),
            "disp_freq": disp_freq,
            "save_freq": save_freq,
            "save_ckpt": _path_string(save_ckpt),
        },
    }
    if validation_systems:
        input_value["training"]["validation_data"] = {
            "systems": [_path_string(item) for item in validation_systems],
            "batch_size": validation_batch_size,
            "numb_btch": validation_batches,
        }
    return input_value


def write_training_input(
    path: str | Path,
    **kwargs: Any,
) -> Path:
    """Write :func:`prepare_training_input` as UTF-8 JSON and return its path."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(prepare_training_input(**kwargs), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target


TrainingConfig = DeepMDTrainingConfig


def build_torchrun_command(config: DeepMDTrainingConfig) -> tuple[str, ...]:
    return config.training_command()


def build_freeze_command(config: DeepMDTrainingConfig) -> tuple[str, ...]:
    return config.freeze_command()


def _status_function(config: DeepMDTrainingConfig) -> str:
    status_file = shlex.quote(_path_string(config.status_file))
    stdout_log = _path_string(config.stdout_log)
    stderr_log = _path_string(config.stderr_log)
    return "\n".join(
        [
            f"STATUS_FILE={status_file}",
            "write_status() {",
            "  local status=\"$1\" phase=\"$2\" rc=\"$3\"",
            "  printf '{\"schema_version\":\"mlcc.deepmd.training.v1\",\"status\":\"%s\",\"phase\":\"%s\",\"returncode\":%s,\"scheduler_job_id\":\"%s\",\"stdout_log\":\"%s\",\"stderr_log\":\"%s\"}\\n' \"$status\" \"$phase\" \"$rc\" \"${SLURM_JOB_ID:-unknown}\" "
            f"\"{stdout_log}\" \"{stderr_log}\" > \"$STATUS_FILE\"",
            "}",
        ]
    )


def build_sbatch_script(config: DeepMDTrainingConfig) -> str:
    """Generate a script for ``sbatch`` without submitting it."""

    resources = config.resource_request()
    lines = [
        "#!/usr/bin/env bash",
        f"#SBATCH --job-name={resources['job_name']}",
        f"#SBATCH --partition={resources['partition']}",
        f"#SBATCH --nodes={resources['nodes']}",
        f"#SBATCH --ntasks={resources['ntasks']}",
        f"#SBATCH --cpus-per-task={resources['cpus_per_task']}",
        f"#SBATCH --gres={resources['gres']}",
        f"#SBATCH --time={resources['time']}",
    ]
    if "mem_mib" in resources:
        lines.append(f"#SBATCH --mem={resources['mem_mib']}M")
    lines.extend(
        [
            f"#SBATCH --output={resources['stdout_log']}",
            f"#SBATCH --error={resources['stderr_log']}",
            "#SBATCH --no-requeue",
            "",
            "set -euo pipefail",
            f"cd {shlex.quote(_path_string(config.workdir))}",
        ]
    )
    if config.environment_script is not None:
        lines.append(f"source {shlex.quote(_path_string(config.environment_script))}")
    lines.extend(
        [
            "export CUDA_DEVICE_ORDER=PCI_BUS_ID",
            "if [ -z \"${CUDA_VISIBLE_DEVICES:-}\" ]; then",
            "  echo 'DeePMD training requires Slurm CUDA_VISIBLE_DEVICES; no CPU fallback is allowed' >&2",
            "  exit 2",
            "fi",
            "visible_gpu_count=$(awk -F, '{print NF}' <<< \"$CUDA_VISIBLE_DEVICES\")",
            f"if [ \"$visible_gpu_count\" -ne {config.nproc_per_node} ]; then",
            f"  echo \"expected {config.nproc_per_node} visible GPUs, got $CUDA_VISIBLE_DEVICES\" >&2",
            "  exit 2",
            "fi",
            f"export OMP_NUM_THREADS={config.threads_per_rank}",
            f"export DP_INTRA_OP_PARALLELISM_THREADS={config.threads_per_rank}",
            "export DP_INTER_OP_PARALLELISM_THREADS=1",
        ]
    )
    for key, value in sorted(config.environment.items()):
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            raise TrainingConfigError(f"invalid environment variable name {key!r}")
        lines.append(f"export {key}={shlex.quote(str(value))}")
    lines.extend(
        [
            "",
            "# torchrun assigns LOCAL_RANK 0..N-1; DeePMD maps each rank to one visible GPU.",
            f"printf 'deePMD_kit={shlex.quote(config.deepmd_kit_version)} backend=pt world_size={config.nproc_per_node} local_batch={config.local_batch_size} global_batch={config.global_batch_size} seed={config.seed} stop_batch={config.stop_batch}\\n'",
            f"printf 'SLURM_JOB_ID=%s CUDA_VISIBLE_DEVICES=%s\\n' \"${{SLURM_JOB_ID:-unknown}}\" \"$CUDA_VISIBLE_DEVICES\"",
            f"printf 'ddp_sampler=torch.utils.data.DistributedSampler drop_last=false replicated_samples={str(config.replicated_samples).lower()}\\n'",
            _status_function(config),
            "write_status running training 0",
            "",
            f"if {shlex.join(config.training_command())}; then",
            "  write_status completed training 0",
            "else",
            "  rc=$?",
            "  write_status failed training \"$rc\"",
            "  exit \"$rc\"",
            "fi",
        ]
    )
    if config.freeze:
        lines.extend(
            [
                "",
                f"if {shlex.join(config.freeze_command())}; then",
                "  write_status completed freeze 0",
                "else",
                "  rc=$?",
                "  write_status failed freeze \"$rc\"",
                "  exit \"$rc\"",
                "fi",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def write_sbatch_script(
    config: DeepMDTrainingConfig,
    path: str | Path | None = None,
    *,
    write_manifest: bool = True,
) -> Path:
    target = Path(path) if path is not None else Path(config.workdir) / "deepmd-train.sbatch"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_sbatch_script(config), encoding="utf-8", newline="\n")
    if write_manifest:
        manifest_path = Path(config.manifest_file)
        if not manifest_path.is_absolute():
            manifest_path = target.parent / manifest_path
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(config.manifest(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return target


def write_manifest(config: DeepMDTrainingConfig, path: str | Path | None = None) -> Path:
    target = Path(path) if path is not None else Path(config.workdir) / _path_string(config.manifest_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config.manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return target


def record_native_result(
    manifest_path: str | Path,
    *,
    phase: str,
    command: Sequence[str],
    returncode: int,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, Any]:
    """Record one native training/freeze result without retrying it."""

    if phase not in ("training", "freeze"):
        raise TrainingConfigError("phase must be 'training' or 'freeze'")
    target = Path(manifest_path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except OSError as error:
        raise TrainingConfigError(f"cannot read training manifest {target}: {error}") from error
    if not isinstance(data, dict):
        raise TrainingConfigError("training manifest must contain an object")
    result = {
        "phase": phase,
        "command": [str(item) for item in command],
        "returncode": int(returncode),
        "status": "completed" if returncode == 0 else "failed",
        "stdout": stdout,
        "stderr": stderr,
    }
    native_results = data.setdefault("native_results", {})
    if not isinstance(native_results, dict):
        raise TrainingConfigError("training manifest native_results must be an object")
    native_results[phase] = result
    if returncode != 0:
        data["status"] = "failed"
        data["native_error"] = result
    elif phase == "freeze" or (phase == "training" and not data.get("freeze", {}).get("enabled", True)):
        data["status"] = "completed"
    else:
        data["status"] = "training_completed"
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return data


def make_training_plan(config: DeepMDTrainingConfig) -> dict[str, Any]:
    """Return the task fields needed by the existing site runner."""

    return {
        "engine": "deepmd",
        "engine_version": config.deepmd_kit_version,
        "backend": DEEPMD_BACKEND,
        "command": list(config.training_command()),
        "freeze_command": list(config.freeze_command()) if config.freeze else None,
        "resource_request": config.resource_request(),
        "batch": {"local_per_rank": config.local_batch_size, "global": config.global_batch_size},
        "seed": config.seed,
        "stop_batch": config.stop_batch,
            "training_controls": {
                "disp_file": _path_string(config.disp_file),
                "disp_freq": config.disp_freq,
                "save_freq": config.save_freq,
            },
        "checkpoint": _path_string(config.checkpoint),
        "freeze_output": _path_string(config.frozen_model) if config.freeze else None,
        "scientific_status": "not_assessed",
        "scientific_qualification": False,
        "runner": "existing_site_runner",
    }


__all__ = [
    "DEEPMD_BACKEND",
    "DEEPMD_KIT_VERSION",
    "DEEPMD_LAMMPS_PAIR_STYLE",
    "DEEPMD_TRAINING_ROUTE",
    "DeepMDTrainingConfig",
    "TrainingConfig",
    "TrainingConfigError",
    "build_freeze_command",
    "build_sbatch_script",
    "build_torchrun_command",
    "count_training_frames",
    "make_training_plan",
    "prepare_training_input",
    "record_native_result",
    "write_manifest",
    "write_sbatch_script",
    "write_training_input",
]
