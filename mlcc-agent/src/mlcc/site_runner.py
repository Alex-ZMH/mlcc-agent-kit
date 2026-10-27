"""Direct SSH/scp and Slurm adapter for MLCC tasks.

The adapter only controls the remote scheduler.  It never starts a numerical
program directly over SSH: the generated script is submitted with
``sbatch --parsable`` and all later state comes from ``scontrol``.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import posixpath
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Callable, Mapping, Sequence

from .tasks import TaskRecord, load_task, save_task, utc_now
from .workflow import require_result_dependencies


Execute = Callable[..., subprocess.CompletedProcess[str]]


class RunnerError(RuntimeError):
    """An external control command failed; raw output remains attached."""

    def __init__(
        self,
        action: str,
        command: Sequence[str],
        returncode: int | None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.action = action
        self.command = list(command)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        command_text = shlex.join([str(item) for item in command])
        message = f"{action} failed: {command_text}"
        if returncode is not None:
            message += f" (exit {returncode})"
        if stdout:
            message += f"\nstdout:\n{stdout.rstrip()}"
        if stderr:
            message += f"\nstderr:\n{stderr.rstrip()}"
        super().__init__(message)


@dataclass(frozen=True)
class SiteConfig:
    """Private site contract consumed by the portable runner.

    The JSON form is documented in ``docs/h0-runner.md``.  The private site
    contract requires ``workspace.remote_root``.
    """

    ssh_alias: str
    remote_root: str
    local_workspace: Path
    default_partition: str | None = None
    remote_environment_script: str | None = None
    ssh_program: str = "ssh"
    scp_program: str = "scp"
    scheduler: str = "slurm"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SiteConfig":
        ssh = value["ssh"]
        workspace = value["workspace"]
        runner = value["runner"]
        ssh_alias = ssh["alias"]
        remote_root = workspace["remote_root"]
        local_workspace = workspace["local"]
        selected = runner["selected"]
        if selected != "slurm":
            raise ValueError(f"runner.selected must be slurm, got {selected!r}")
        slurm = runner.get("slurm", {})
        default_partition = slurm.get("default_partition")
        remote_environment_script = slurm.get("environment_script")
        return cls(
            ssh_alias=str(ssh_alias),
            remote_root=str(remote_root),
            local_workspace=Path(local_workspace),
            default_partition=str(default_partition) if default_partition else None,
            remote_environment_script=(
                str(remote_environment_script) if remote_environment_script else None
            ),
            ssh_program=str(value.get("ssh_program", "ssh")),
            scp_program=str(value.get("scp_program", "scp")),
            scheduler="slurm",
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "SiteConfig":
        with Path(path).open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise ValueError("site config JSON must contain an object")
        return cls.from_mapping(value)


def _parse_scontrol_fields(raw: str) -> dict[str, str]:
    """Parse key/value tokens while retaining the complete raw response."""

    return {key: value for key, value in re.findall(r"([A-Za-z][A-Za-z0-9_]*)=([^\s]+)", raw)}


def _slurm_job_target(job_id: str) -> tuple[str, str | None]:
    if ";" in job_id:
        numeric, cluster = job_id.split(";", 1)
        return numeric, cluster
    return job_id, None


def _slurm_control_command(program: str, operation: str, job_id: str) -> str:
    numeric, cluster = _slurm_job_target(job_id)
    pieces = [program]
    if cluster:
        pieces.extend(["-M", shlex.quote(cluster)])
    pieces.extend(operation.split())
    pieces.append(shlex.quote(numeric))
    return " ".join(pieces)


class SiteRunner:
    """Prepare, transfer, submit, query, cancel and collect one task."""

    _DFT_ENGINES = frozenset({"abacus", "vasp"})

    def __init__(self, config: SiteConfig, execute: Execute | None = None) -> None:
        self.config = config
        self.execute = execute or subprocess.run

    def _local_dir(self, task: TaskRecord) -> Path:
        value = task.data.get("local_workdir")
        if value:
            return Path(value)
        if task.path is not None:
            return task.path.parent
        return self.config.local_workspace / "tasks" / task.task_id

    def _remote_dir(self, task: TaskRecord) -> str:
        value = task.data.get("remote_workdir")
        if value:
            return str(value)
        remote = posixpath.join(self.config.remote_root, "tasks", task.task_id)
        task.set(remote_workdir=remote)
        return remote

    def _ssh_command(self, remote_command: str) -> list[str]:
        return [self.config.ssh_program, self.config.ssh_alias, remote_command]

    @classmethod
    def _is_dft_task(cls, task: TaskRecord) -> bool:
        return task.data.get("engine") in cls._DFT_ENGINES

    def _dft_resource_time(self, task: TaskRecord, *, persist_default: bool) -> Any:
        """Return the only permitted DFT wall-clock value.

        DFT convergence is an engine/science criterion, so the runner does
        not accept a finite Slurm wall-clock limit.  Missing values are
        normalized to Slurm's unlimited value (``0``).  The strict type check
        intentionally accepts only integer ``0`` or the literal string
        ``"0"``; values such as ``0.0`` and ``"00:10:00"`` are not silently
        reinterpreted.
        """

        resources = task.data.get("resource_request", {})
        if not isinstance(resources, dict):
            raise ValueError("resource_request must be an object")
        if "time" not in resources or resources["time"] in (None, ""):
            resources["time"] = 0
            task.set(resource_request=resources)
            if persist_default:
                save_task(task)
            return 0
        value = resources["time"]
        if (type(value) is int and value == 0) or (type(value) is str and value == "0"):
            return value
        raise ValueError(
            f"DFT task engine={task.data.get('engine')!r} cannot use a finite "
            f"Slurm wall-clock limit; resource_request.time must be omitted, "
            f"empty, integer 0, or string '0' (got {value!r})"
        )

    def _run(self, action: str, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = self.execute(
                [str(item) for item in command],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            raise RunnerError(action, command, None, stderr=str(error)) from error
        if result.returncode != 0:
            raise RunnerError(action, command, result.returncode, result.stdout, result.stderr)
        return result

    def _resource_directives(self, task: TaskRecord) -> list[str]:
        resources = task.data.get("resource_request", {})
        if not isinstance(resources, dict):
            raise ValueError("resource_request must be an object")
        if self._is_dft_task(task):
            self._dft_resource_time(task, persist_default=False)
            resources = task.data["resource_request"]
        resources = dict(resources)
        if "partition" not in resources and self.config.default_partition:
            resources["partition"] = self.config.default_partition
        mapping = (
            ("partition", "partition"),
            ("account", "account"),
            ("ntasks", "ntasks"),
            ("cpus_per_task", "cpus-per-task"),
            ("nodes", "nodes"),
            ("mem_mib", "mem"),
            ("time", "time"),
            ("gres", "gres"),
            ("gpus", "gpus"),
            ("gpus_per_task", "gpus-per-task"),
            ("constraint", "constraint"),
            ("hint", "hint"),
            ("job_name", "job-name"),
            ("stdout_log", "output"),
            ("stderr_log", "error"),
        )
        resources.setdefault("job_name", f"mlcc-{task.task_id}")
        resources.setdefault("stdout_log", "stdout.log")
        resources.setdefault("stderr_log", "stderr.log")
        lines = ["#SBATCH --no-requeue"]
        for key, option in mapping:
            if key in resources and resources[key] not in (None, ""):
                value = resources[key]
                if key == "mem_mib":
                    value = f"{value}M"
                lines.append(f"#SBATCH --{option}={value}")
        return lines

    def _script_text(self, task: TaskRecord) -> str:
        lines = ["#!/usr/bin/env bash", *self._resource_directives(task), "set -e"]
        environment_script = task.data.get("environment_script", self.config.remote_environment_script)
        if environment_script:
            lines.append(f"source {shlex.quote(str(environment_script))}")
        environment = task.data.get("environment", {})
        if not isinstance(environment, dict):
            raise ValueError("environment must be an object")
        for key, value in environment.items():
            lines.append(f"export {key}={shlex.quote(str(value))}")
        lines.extend(
            [
                "",
                f"# MLCC task {task.task_id}",
                shlex.join(task.command),
                "",
            ]
        )
        return "\n".join(lines)

    def _save_event(self, task: TaskRecord, action: str, **values: Any) -> None:
        task.record_event(action, **values)
        save_task(task)

    def _save_failure(self, task: TaskRecord, action: str, error: RunnerError) -> None:
        failure = {
            "action": error.action,
            "command": error.command,
            "returncode": error.returncode,
            "stdout": error.stdout,
            "stderr": error.stderr,
            "message": str(error),
        }
        if action == "query" and task.data.get("scheduler_state"):
            task.set(query_error=failure)
        else:
            task.set(control_error=failure)
        if not (action == "submit" and task.data.get("submitted_unknown")):
            task.set(status=f"{action}_failed")
        task.set(last_error=failure)
        task.record_event(
            action,
            status="failed",
            command=error.command,
            returncode=error.returncode,
            stdout=error.stdout,
            stderr=error.stderr,
            error=str(error),
        )
        save_task(task)

    def prepare(self, task: TaskRecord) -> dict[str, Any]:
        """Write the Slurm batch script; no remote command is started."""

        task.command
        if self._is_dft_task(task):
            self._dft_resource_time(task, persist_default=False)
        local_dir = self._local_dir(task).resolve()
        local_dir.mkdir(parents=True, exist_ok=True)
        script_path = local_dir / "job.sbatch"
        script_path.write_text(self._script_text(task), encoding="utf-8", newline="\n")
        task.set(
            local_workdir=str(local_dir),
            remote_workdir=self._remote_dir(task),
            prepared_script=str(script_path),
            status="prepared",
        )
        self._save_event(
            task,
            "prepare",
            command=["write", str(script_path)],
            status="prepared",
            prepared_script=str(script_path),
        )
        return task.data

    def transfer(self, task: TaskRecord) -> dict[str, Any]:
        """Create the remote task directory and copy explicitly selected files."""

        local_dir = self._local_dir(task)
        remote_dir = self._remote_dir(task)
        mkdir_command = self._ssh_command(f"mkdir -p {shlex.quote(remote_dir)}")
        try:
            mkdir_result = self._run("transfer_mkdir", mkdir_command)
            self._save_event(
                task,
                "transfer_mkdir",
                command=mkdir_command,
                returncode=mkdir_result.returncode,
                stdout=mkdir_result.stdout,
                stderr=mkdir_result.stderr,
            )
            paths = task.data.get("transfer_paths", [])
            if not isinstance(paths, list):
                raise ValueError("transfer_paths must be a list")
            paths = ["job.sbatch", *paths]
            unique_paths = []
            for item in paths:
                if item not in unique_paths:
                    unique_paths.append(item)
            transferred = [str(Path(item) if Path(item).is_absolute() else local_dir / item)
                           for item in unique_paths]
            destination = f"{self.config.ssh_alias}:{remote_dir}/"
            command = [self.config.scp_program, "-r", *transferred, destination]
            result = self._run("transfer", command)
            self._save_event(task, "transfer", command=command, sources=transferred,
                             destination=destination, returncode=result.returncode,
                             stdout=result.stdout, stderr=result.stderr)
            task.set(status="transferred", transferred_files=transferred)
            save_task(task)
            return task.data
        except RunnerError as error:
            self._save_failure(task, "transfer", error)
            raise

    def submit(self, task: TaskRecord) -> dict[str, Any]:
        """Submit the prepared script and persist the native Slurm job ID."""

        if task.scheduler_job_id is not None or task.data.get("submission_attempt_started_at"):
            error = RunnerError(
                "submit",
                [],
                None,
                stderr=(
                    f"task already has scheduler_job_id={task.scheduler_job_id}"
                    if task.scheduler_job_id is not None
                    else "task already has a submission attempt"
                ),
            )
            task.set(status="submit_refused", last_error={"action": "submit", "message": str(error)})
            task.record_event("submit", status="refused", error=str(error))
            save_task(task)
            raise error
        dft_task = self._is_dft_task(task)
        if dft_task:
            # Validate before recording a submission attempt or opening SSH.
            # This also repairs an old task that omitted the new explicit
            # unlimited value, while finite legacy directives fail loudly.
            self._dft_resource_time(task, persist_default=True)
        if task.data["status"] != "transferred":
            raise ValueError(f"submit requires completed transfer, got {task.data['status']}")
        if "required_results" in task.data:
            dependency_evidence = require_result_dependencies(
                task,
                self.config.local_workspace,
            )
            task.set(dependency_evidence=dependency_evidence)
            save_task(task)
        attempt_started = utc_now()
        task.set(
            submission_attempt_started_at=attempt_started,
            submission_state="attempting",
            status="SUBMITTING",
        )
        task.record_event("submit_attempt_started", status="SUBMITTING")
        save_task(task)
        remote_dir = self._remote_dir(task)
        script_name = Path(task.data.get("prepared_script", "job.sbatch")).name
        sbatch_options = "--parsable --time=0" if dft_task else "--parsable"
        remote_command = (
            f"cd {shlex.quote(remote_dir)} && sbatch {sbatch_options} {shlex.quote(script_name)}"
        )
        command = self._ssh_command(remote_command)
        try:
            result = self._run("submit", command)
            stdout = result.stdout
            lines = [line.strip() for line in stdout.splitlines() if line.strip()]
            if not lines:
                raise RunnerError("submit", command, result.returncode, stdout, result.stderr)
            native = lines[0]
            task.set(
                scheduler_job_id=native,
                scheduler_submit_stdout=stdout,
                scheduler_submit_stderr=result.stderr,
                scheduler_submit_command=command,
                status="SUBMITTED",
                submission_state="submitted",
                submitted_unknown=False,
                submitted_at=utc_now(),
            )
            self._save_event(
                task,
                "submit",
                command=command,
                remote_command=remote_command,
                scheduler_job_id=native,
                returncode=result.returncode,
                stdout=stdout,
                stderr=result.stderr,
                status="SUBMITTED",
            )
            return task.data
        except RunnerError as error:
            if error.returncode in (None, 255):
                task.set(submission_state="unknown", submitted_unknown=True, status="SUBMITTED_UNKNOWN")
            else:
                task.set(submission_state="failed", submitted_unknown=False)
            self._save_failure(task, "submit", error)
            raise

    def query(self, task: TaskRecord) -> dict[str, Any]:
        """Query the actual controller and save raw ``scontrol`` output."""

        job_id = task.scheduler_job_id
        if job_id is None:
            raise ValueError("task has no scheduler_job_id")
        command = self._ssh_command(_slurm_control_command("scontrol", "show job", job_id))
        try:
            result = self._run("query", command)
            stdout = result.stdout
            fields = _parse_scontrol_fields(stdout)
            state = fields.get("JobState")
            task.set(
                scheduler_query_command=command,
                scheduler_query_raw_stdout=stdout,
                scheduler_query_raw_stderr=result.stderr,
                scheduler_state=state,
                scheduler_fields=fields,
                status=state or task.data.get("status", "submitted"),
                exit_code=fields.get("ExitCode"),
                log_file={
                    key: fields[key]
                    for key in ("StdOut", "StdErr")
                    if key in fields
                },
                resources={
                    key: fields[key]
                    for key in (
                        "Partition",
                        "AllocTRES",
                        "ReqTRES",
                        "NumCPUs",
                        "NNodes",
                        "NodeList",
                        "Elapsed",
                        "TimeLimit",
                        "RunTime",
                    )
                    if key in fields
                },
            )
            self._save_event(
                task,
                "query",
                command=command,
                returncode=result.returncode,
                stdout=stdout,
                stderr=result.stderr,
                scheduler_state=state,
                exit_code=fields.get("ExitCode"),
                resources=task.data["resources"],
            )
            return task.data
        except RunnerError as error:
            self._save_failure(task, "query", error)
            raise

    def cancel(self, task: TaskRecord) -> dict[str, Any]:
        """Request cancellation with Slurm's native ``scancel`` command."""

        job_id = task.scheduler_job_id
        if job_id is None:
            raise ValueError("task has no scheduler_job_id")
        command = self._ssh_command(_slurm_control_command("scancel", "", job_id).rstrip())
        try:
            result = self._run("cancel", command)
            task.set(
                cancel_command=command,
                cancel_stdout=result.stdout,
                cancel_stderr=result.stderr,
                status="CANCEL_REQUESTED",
                cancel_requested_at=utc_now(),
            )
            self._save_event(
                task,
                "cancel",
                command=command,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                status="CANCEL_REQUESTED",
            )
            return task.data
        except RunnerError as error:
            self._save_failure(task, "cancel", error)
            raise

    def collect(self, task: TaskRecord) -> dict[str, Any]:
        """Copy explicitly selected remote files back to the task workspace."""

        remote_dir = self._remote_dir(task)
        local_dir = self._local_dir(task)
        paths = task.data.get("collect_paths", [])
        if not isinstance(paths, list) or not paths:
            raise ValueError("collect_paths must be a non-empty list")
        collected: list[str] = []
        try:
            for item in paths:
                if isinstance(item, str):
                    remote_name = item
                    local_name = item
                elif isinstance(item, dict):
                    remote_name = str(item["remote"])
                    local_name = str(item["local"])
                else:
                    raise ValueError("each collect_paths item must be a string or object")
                remote_path = remote_name if remote_name.startswith("/") else posixpath.join(remote_dir, remote_name)
                local_path = local_dir / local_name
                local_path.parent.mkdir(parents=True, exist_ok=True)
                command = [
                    self.config.scp_program,
                    "-r",
                    f"{self.config.ssh_alias}:{remote_path}",
                    str(local_path),
                ]
                result = self._run("collect", command)
                collected.append(str(local_path))
                self._save_event(
                    task,
                    "collect",
                    command=command,
                    remote_path=remote_path,
                    local_path=str(local_path),
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            task.set(collected_files=collected, collect_status="collected", collected_at=utc_now())
            save_task(task)
            return task.data
        except RunnerError as error:
            self._save_failure(task, "collect", error)
            raise


def runner_for_task(site_path: str | Path, task_path: str | Path) -> tuple[SiteRunner, TaskRecord]:
    """Load the two JSON contracts used by the CLI."""

    task = load_task(task_path)
    runner = SiteRunner(SiteConfig.from_file(site_path))
    return runner, task

