from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from mlcc.site_runner import RunnerError, SiteConfig, SiteRunner
from mlcc.tasks import TaskRecord, load_task, save_task


class FakeExecutor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def result(stdout="", stderr="", returncode=0):
    from subprocess import CompletedProcess

    return CompletedProcess(["stub"], returncode, stdout, stderr)


class SiteRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.task_path = self.root / "task.json"
        self.task = TaskRecord(
            {
                "task_id": "fixture-001",
                "stage": "P1",
                "engine": "test-stub",
                "command": ["/opt/example/program", "--input", "INCAR"],
                "resource_request": {
                    "partition": "cpu",
                    "ntasks": 1,
                    "cpus_per_task": 1,
                    "mem_mib": 512,
                    "time": "00:05:00",
                },
                "transfer_paths": ["INCAR"],
                "collect_paths": ["OUTCAR", {"remote": "vasprun.xml", "local": "results/vasprun.xml"}],
            },
            self.task_path,
        )
        save_task(self.task)
        (self.root / "INCAR").write_text("stub input\n", encoding="utf-8")
        self.config = SiteConfig(
            ssh_alias="v100",
            remote_root="/home/v100/projects/mlcc",
            local_workspace=self.root,
            default_partition="cpu",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_prepare_writes_slurm_script_and_record(self):
        executor = FakeExecutor([])
        runner = SiteRunner(self.config, executor)

        data = runner.prepare(load_task(self.task_path))

        script = Path(data["prepared_script"])
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")
        self.assertIn("#SBATCH --no-requeue", text)
        self.assertIn("set -e", text)
        self.assertIn("#SBATCH --partition=cpu", text)
        self.assertIn("#SBATCH --output=stdout.log", text)
        self.assertIn("#SBATCH --error=stderr.log", text)
        self.assertIn("/opt/example/program --input INCAR", text)
        self.assertEqual(executor.calls, [])
        saved = load_task(self.task_path).data
        self.assertEqual(saved["status"], "prepared")
        self.assertEqual(saved["events"][0]["action"], "prepare")

    def test_prepare_preserves_explicit_slurm_account(self):
        self.task.data["resource_request"]["account"] = "v100"
        runner = SiteRunner(self.config, FakeExecutor([]))
        data = runner.prepare(self.task)
        self.assertIn("#SBATCH --account=v100", Path(data["prepared_script"]).read_text())

    def test_prepare_resolves_relative_task_directory(self):
        executor = FakeExecutor([])
        runner = SiteRunner(self.config, executor)
        previous_cwd = Path.cwd()
        relative_task_path = Path("relative-task") / "task.json"
        task_file = self.root / relative_task_path
        other_cwd = self.root / "other-cwd"
        other_cwd.mkdir()

        try:
            os.chdir(self.root)
            relative_task = TaskRecord(dict(self.task.data), relative_task_path)
            save_task(relative_task, relative_task_path)

            data = runner.prepare(load_task(relative_task_path))

            expected_dir = (self.root / relative_task_path.parent).resolve()
            self.assertEqual(Path(data["local_workdir"]), expected_dir)
            self.assertEqual(Path(data["prepared_script"]), expected_dir / "job.sbatch")
            self.assertTrue(Path(data["local_workdir"]).is_absolute())
            self.assertTrue(Path(data["prepared_script"]).is_absolute())

            os.chdir(other_cwd)
            self.assertTrue(Path(data["prepared_script"]).is_file())
            saved = json.loads(task_file.read_text(encoding="utf-8"))
            self.assertEqual(Path(saved["local_workdir"]), expected_dir)
            self.assertEqual(Path(saved["prepared_script"]), expected_dir / "job.sbatch")
        finally:
            os.chdir(previous_cwd)

    def test_prepare_dft_engines_default_to_and_persist_unlimited_time(self):
        for engine in ("abacus", "vasp"):
            for marker in ("missing", None, ""):
                task_path = self.root / engine / str(marker) / "task.json"
                task = TaskRecord(dict(self.task.data), task_path)
                resources = {
                    key: value
                    for key, value in self.task.data["resource_request"].items()
                    if key != "time"
                }
                if marker != "missing":
                    resources["time"] = marker
                task.set(engine=engine, resource_request=resources)
                save_task(task)

                runner = SiteRunner(self.config, FakeExecutor([]))
                data = runner.prepare(load_task(task_path))

                self.assertEqual(data["resource_request"]["time"], 0)
                self.assertEqual(load_task(task_path).data["resource_request"]["time"], 0)
                self.assertIn("#SBATCH --time=0", Path(data["prepared_script"]).read_text(encoding="utf-8"))

    def test_dft_finite_time_is_rejected_before_prepare_and_submit(self):
        for engine in ("abacus", "vasp"):
            task_path = self.root / f"{engine}-finite.json"
            task = TaskRecord(dict(self.task.data), task_path)
            task.set(
                engine=engine,
                resource_request={**self.task.data["resource_request"], "time": "00:05:00"},
            )
            save_task(task)
            executor = FakeExecutor([])
            runner = SiteRunner(self.config, executor)

            with self.assertRaisesRegex(ValueError, "cannot use a finite"):
                runner.prepare(load_task(task_path))
            self.assertEqual(executor.calls, [])
            self.assertNotIn("prepared_script", load_task(task_path).data)

            task = load_task(task_path)
            task.set(status="transferred")
            save_task(task)
            with self.assertRaisesRegex(ValueError, "cannot use a finite"):
                runner.submit(task)
            self.assertEqual(executor.calls, [])
            self.assertNotIn("submission_attempt_started_at", load_task(task_path).data)

    def test_dft_submit_forces_explicit_unlimited_time(self):
        executor = FakeExecutor([result("123\n")])
        runner = SiteRunner(self.config, executor)
        task = load_task(self.task_path)
        task.set(
            engine="abacus",
            status="transferred",
            resource_request={**task.data["resource_request"], "time": "0"},
        )
        save_task(task)

        runner.submit(task)

        self.assertIn("sbatch --parsable --time=0 job.sbatch", executor.calls[0][0][2])
        self.assertEqual(task.data["resource_request"]["time"], "0")

    def test_non_dft_time_behavior_is_unchanged(self):
        executor = FakeExecutor([result("123\n")])
        runner = SiteRunner(self.config, executor)
        task = load_task(self.task_path)
        runner.prepare(task)
        task.set(status="transferred")
        runner.submit(task)

        self.assertEqual(task.data["resource_request"]["time"], "00:05:00")
        self.assertIn("#SBATCH --time=00:05:00", Path(task.data["prepared_script"]).read_text(encoding="utf-8"))
        self.assertIn("sbatch --parsable job.sbatch", executor.calls[0][0][2])
        self.assertNotIn("--time=0", executor.calls[0][0][2])

    def test_transfer_submit_query_cancel_collect_preserve_commands(self):
        responses = [
            result(),  # mkdir
            result(),  # all selected input files in one scp
            result("123\n"),  # sbatch
            result("JobId=123 JobName=fixture JobState=COMPLETED ExitCode=0:0 Partition=cpu NumCPUs=1 NodeList=v100 Elapsed=00:00:03\n"),
            result(),  # scancel
            result(),  # OUTCAR
            result(),  # vasprun
        ]
        executor = FakeExecutor(responses)
        runner = SiteRunner(self.config, executor)
        task = load_task(self.task_path)

        runner.prepare(task)
        runner.transfer(task)
        runner.submit(task)
        queried = runner.query(task)
        runner.cancel(task)
        collected = runner.collect(task)

        self.assertEqual(queried["scheduler_job_id"], "123")
        self.assertEqual(queried["scheduler_state"], "COMPLETED")
        self.assertEqual(queried["exit_code"], "0:0")
        self.assertEqual(collected["collect_status"], "collected")
        commands = [call[0] for call in executor.calls]
        self.assertEqual(commands[0][:2], ["ssh", "v100"])
        self.assertIn("sbatch --parsable", commands[2][2])
        self.assertIn("scontrol show job 123", commands[3][2])
        self.assertIn("scancel 123", commands[4][2])
        saved = load_task(self.task_path).data
        self.assertEqual(saved["scheduler_query_raw_stdout"].split()[0], "JobId=123")
        self.assertEqual(len(saved["events"]), 9)

    def test_submit_does_not_duplicate_existing_job(self):
        executor = FakeExecutor([])
        runner = SiteRunner(self.config, executor)
        task = load_task(self.task_path)
        task.set(scheduler_job_id="44", status="COMPLETED")
        save_task(task)

        with self.assertRaises(RunnerError) as raised:
            runner.submit(task)
        self.assertIn("already has scheduler_job_id=44", str(raised.exception))
        self.assertEqual(executor.calls, [])

    def test_submit_requires_saved_result_dependencies_before_sbatch(self):
        executor = FakeExecutor([])
        runner = SiteRunner(self.config, executor)
        task = load_task(self.task_path)
        task.set(
            status="transferred",
            required_results=[
                {
                    "task_id": "parent-001",
                    "result_file": "result.json",
                    "scientific_status": "converged",
                }
            ],
        )
        save_task(task)
        parent_dir = self.root / "tasks" / "parent-001"
        parent_dir.mkdir(parents=True)
        save_task(
            TaskRecord(
                {
                    "task_id": "parent-001",
                    "status": "COMPLETED",
                    "scheduler_state": "COMPLETED",
                    "exit_code": "0:0",
                    "scheduler_job_id": "parent-job-1",
                },
                parent_dir / "task.json",
            )
        )

        with self.assertRaisesRegex(ValueError, "required result file does not exist"):
            runner.submit(task)

        self.assertEqual(executor.calls, [])
        saved = load_task(self.task_path).data
        self.assertNotIn("submission_attempt_started_at", saved)
        self.assertNotIn("dependency_evidence", saved)

    def test_submit_preserves_parsable_cluster_suffix_and_uses_numeric_target(self):
        executor = FakeExecutor([
            result("123;mlcc-v100\n"),
            result("JobId=123 JobState=COMPLETED ExitCode=0:0\n"),
        ])
        runner = SiteRunner(self.config, executor)
        task = load_task(self.task_path)
        task.set(status="transferred")
        runner.submit(task)
        runner.query(task)
        self.assertEqual(task.scheduler_job_id, "123;mlcc-v100")
        self.assertIn("scontrol -M mlcc-v100 show job 123", executor.calls[1][0][2])

    def test_failed_control_command_keeps_raw_error(self):
        executor = FakeExecutor([result("", "scontrol: error: Invalid job id specified", 1)])
        runner = SiteRunner(self.config, executor)
        task = load_task(self.task_path)
        task.set(scheduler_job_id="404")
        save_task(task)

        with self.assertRaises(RunnerError) as raised:
            runner.query(task)
        self.assertIn("Invalid job id specified", str(raised.exception))
        saved = load_task(self.task_path).data
        self.assertEqual(saved["last_error"]["stderr"], "scontrol: error: Invalid job id specified")
        self.assertEqual(saved["events"][-1]["status"], "failed")

    def test_failed_transfer_cannot_be_submitted(self):
        executor = FakeExecutor([result(), result("", "Connection closed", 255)])
        runner = SiteRunner(self.config, executor)
        task = load_task(self.task_path)
        runner.prepare(task)
        with self.assertRaises(RunnerError):
            runner.transfer(task)
        with self.assertRaisesRegex(ValueError, "requires completed transfer"):
            runner.submit(task)
        self.assertEqual(len(executor.calls), 2)


if __name__ == "__main__":
    unittest.main()

