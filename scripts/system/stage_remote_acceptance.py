"""Stage a read-only MLCC remote-acceptance archive.

This module only copies project files and writes an archive.  It does not
import ``mlcc``, execute a verifier, submit a scheduler job, or perform any
scientific post-processing.  JSON metadata is copied through a small path
relocation pass so an extracted archive can be used from the requested v100
project directory.  Native structure, log, and result files are copied as
bytes; only JSON metadata containing the local Windows project root is
rewritten.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
from typing import Any, Callable, Iterable


DEFAULT_REMOTE_ROOT = "/home/v100/projects/mlcc/development/0.9.0/project"
DEFAULT_ARCHIVE_RELATIVE = Path("workspace/reports/system-v090/remote-stage-v001.tar.gz")
ARCHIVE_ROOT_NAME = "project"

# The pattern intentionally targets the project root and its path components,
# rather than every Windows path.  Linux paths in existing site/method records
# therefore remain unchanged, as required by the v100 site contract.
WINDOWS_PROJECT_PATH = re.compile(
    r"(?i)D:[\\/]+project[\\/]+mlcc(?:[\\/]+[A-Za-z0-9_.+\-]+)*"
)

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".venv",
    "venv",
    "upstream",
    "release",
    "releases",
}


@dataclass(frozen=True)
class SourceSpec:
    """One explicit source path and its archive category."""

    relative_path: Path
    category: str
    required: bool = True


class StageBuilder:
    """Collect, copy, and describe the explicit archive whitelist."""

    def __init__(self, repo_root: Path, stage_root: Path, remote_root: str) -> None:
        self.repo_root = repo_root.resolve()
        self.stage_root = stage_root.resolve()
        self.project_root = self.stage_root / ARCHIVE_ROOT_NAME
        self.remote_root = remote_root.rstrip("/")
        self.selected: dict[str, SourceSpec] = {}
        self.missing_required: list[str] = []
        self.missing_optional: list[str] = []
        self.excluded: list[dict[str, Any]] = []
        self.copied: list[dict[str, Any]] = []
        self.relocations: list[dict[str, Any]] = []

    @staticmethod
    def _is_ignored_path(path: Path) -> bool:
        return any(part in EXCLUDED_DIRECTORY_NAMES for part in path.parts)

    @staticmethod
    def _excluded_file_reason(path: Path) -> str | None:
        """Return the explicit sensitive/large native-artifact exclusion."""

        name = path.name.lower()
        upper = path.name.upper()
        if upper in {"POTCAR", "WAVECAR", "CHGCAR"}:
            return "VASP pseudopotential or wavefunction/charge-density artifact"
        if "CHARGE-DENSITY" in upper or name.endswith(".restart"):
            return "native charge-density restart/wavefunction artifact"
        if name.endswith(".wfc") or ".wfc." in name:
            return "native wavefunction artifact"
        if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            return "credential/private-key artifact"
        return None

    def _record_missing(self, relative_path: Path, required: bool) -> None:
        target = (self.missing_required if required else self.missing_optional)
        value = relative_path.as_posix()
        if value not in target:
            target.append(value)

    def add_file(
        self,
        relative_path: str | Path,
        category: str,
        *,
        required: bool = True,
        archive_path: str | Path | None = None,
    ) -> None:
        """Add one file to the whitelist, recording absent inputs explicitly."""

        relative = Path(relative_path)
        source = self.repo_root / relative
        destination = Path(archive_path) if archive_path is not None else relative
        key = destination.as_posix()
        if key in self.selected:
            raise ValueError(f"duplicate archive member: {key}")
        self.selected[key] = SourceSpec(relative, category, required)
        if self._is_ignored_path(relative) or self._is_ignored_path(destination):
            self.excluded.append({"file": relative.as_posix(), "reason": "ignored directory"})
            self.selected.pop(key)
            return
        if not source.is_file() or source.is_symlink():
            self._record_missing(relative, required)
            self.selected.pop(key)
            return
        reason = self._excluded_file_reason(source)
        if reason is not None:
            self.excluded.append({
                "file": relative.as_posix(),
                "reason": reason,
                "bytes": source.stat().st_size,
            })
            self.selected.pop(key)

    def add_tree(
        self,
        relative_root: str | Path,
        category: str,
        *,
        pattern: str = "*",
        required: bool = True,
        predicate: Callable[[Path], bool] | None = None,
    ) -> None:
        """Add files matching a narrow, explicit tree pattern."""

        relative = Path(relative_root)
        source_root = self.repo_root / relative
        if not source_root.is_dir():
            self._record_missing(relative, required)
            return
        found = False
        for source in sorted(source_root.rglob(pattern)):
            if not source.is_file() or source.is_symlink():
                continue
            source_relative = source.relative_to(self.repo_root)
            if self._is_ignored_path(source_relative):
                continue
            if predicate is not None and not predicate(source):
                continue
            found = True
            self.add_file(source_relative, category, required=required)
        if not found and required:
            self._record_missing(relative, required)

    def _rewrite_string(self, value: str, source_file: Path, archive_path: str) -> tuple[str, list[dict[str, str]]]:
        replacements: list[dict[str, str]] = []

        def replace(match: re.Match[str]) -> str:
            original = match.group(0)
            normalized = original.replace("\\", "/")
            local_prefix = "D:/project/mlcc"
            suffix = normalized[len(local_prefix):].lstrip("/")
            new = self.remote_root + (f"/{suffix}" if suffix else "")
            replacements.append({"original_path": original, "new_path": new})
            return new

        rewritten = WINDOWS_PROJECT_PATH.sub(replace, value)
        return rewritten, replacements

    def _rewrite_json(self, value: Any, source_file: Path, archive_path: str) -> tuple[Any, list[dict[str, str]]]:
        if isinstance(value, str):
            return self._rewrite_string(value, source_file, archive_path)
        if isinstance(value, list):
            rewritten: list[Any] = []
            records: list[dict[str, str]] = []
            for item in value:
                new_item, item_records = self._rewrite_json(item, source_file, archive_path)
                rewritten.append(new_item)
                records.extend(item_records)
            return rewritten, records
        if isinstance(value, dict):
            rewritten_dict: dict[Any, Any] = {}
            records = []
            for key, item in value.items():
                new_key, key_records = self._rewrite_json(key, source_file, archive_path)
                new_item, item_records = self._rewrite_json(item, source_file, archive_path)
                rewritten_dict[new_key] = new_item
                records.extend(key_records)
                records.extend(item_records)
            return rewritten_dict, records
        return value, []

    def copy_selected(self) -> None:
        """Copy selected files and relocate only project-root JSON references."""

        for archive_path in sorted(self.selected):
            spec = self.selected[archive_path]
            source = self.repo_root / spec.relative_path
            destination = self.project_root / Path(archive_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix.lower() == ".json":
                raw = source.read_bytes()
                original = json.loads(raw.decode("utf-8"))
                rewritten, records = self._rewrite_json(original, source, archive_path)
                if records:
                    with destination.open("w", encoding="utf-8", newline="\n") as stream:
                        json.dump(rewritten, stream, ensure_ascii=False, indent=2, allow_nan=False)
                        stream.write("\n")
                else:
                    destination.write_bytes(raw)
                if records:
                    self.relocations.append({
                        "file": f"{ARCHIVE_ROOT_NAME}/{archive_path}",
                        "source_file": str(source),
                        "original_path": records[0]["original_path"],
                        "new_path": records[0]["new_path"],
                        "replacements": records,
                    })
            else:
                shutil.copyfile(source, destination)
            self.copied.append({
                "file": f"{ARCHIVE_ROOT_NAME}/{archive_path}",
                "category": spec.category,
                "bytes": destination.stat().st_size,
                "source_bytes": source.stat().st_size,
                "json_metadata_rewritten": source.suffix.lower() == ".json",
            })

    def write_metadata(self) -> None:
        relocation = {
            "schema": "mlcc.source-relocation.v001",
            "source_root_local": str(self.repo_root),
            "remote_root": self.remote_root,
            "records": self.relocations,
            "note": "Only JSON metadata paths were relocated; native data files were copied byte-for-byte.",
        }
        relocation_path = self.project_root / "source-relocation.json"
        relocation_path.write_text(
            json.dumps(relocation, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )

        category_counts: dict[str, int] = {}
        for record in self.copied:
            category_counts[record["category"]] = category_counts.get(record["category"], 0) + 1
        source_bytes = sum(record["source_bytes"] for record in self.copied)
        archive_bytes = sum(record["bytes"] for record in self.copied)
        excluded_bytes = sum(item.get("bytes", 0) for item in self.excluded)
        manifest = {
            "schema": "mlcc.remote-acceptance-stage.v001",
            "remote_root": self.remote_root,
            "archive_root": ARCHIVE_ROOT_NAME,
            "purpose": "read-only remote acceptance mirror; no new numerical jobs or scientific evidence",
            "selection": {
                "categories": category_counts,
                "files": len(self.copied),
                "source_bytes": source_bytes,
                "staged_bytes": archive_bytes,
                "json_metadata_rewritten": sum(1 for item in self.copied if item["json_metadata_rewritten"]),
                "native_files_copied_without_rewrite": sum(
                    1 for item in self.copied if not item["json_metadata_rewritten"]
                ),
                "metadata_files_added": 2,
            },
            "missing_required": sorted(self.missing_required),
            "missing_optional": sorted(self.missing_optional),
            "excluded_files": self.excluded,
            "excluded_bytes": excluded_bytes,
            "path_relocation_file": f"{ARCHIVE_ROOT_NAME}/source-relocation.json",
            "scientific_processing_started": False,
            "numerical_jobs_started": [],
            "production_qualification": False,
        }
        (self.project_root / "remote-acceptance-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )

    def create_tar(self, archive_path: Path) -> None:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        if archive_path.exists():
            raise FileExistsError(archive_path)
        with tarfile.open(archive_path, mode="w:gz") as archive:
            archive.add(self.project_root, arcname=ARCHIVE_ROOT_NAME, recursive=True)

    def summary(self) -> dict[str, Any]:
        return {
            "archive": str(DEFAULT_ARCHIVE_RELATIVE),
            "remote_root": self.remote_root,
            "files": len(self.copied),
            "source_bytes": sum(item["source_bytes"] for item in self.copied),
            "staged_bytes": sum(item["bytes"] for item in self.copied),
            "excluded_files": len(self.excluded),
            "excluded_bytes": sum(item.get("bytes", 0) for item in self.excluded),
            "missing_required": sorted(self.missing_required),
            "missing_optional": sorted(self.missing_optional),
            "relocated_json_files": len(self.relocations),
            "scientific_processing_started": False,
            "numerical_jobs_started": [],
        }


def _add_whitelist(builder: StageBuilder) -> None:
    """Add the exact source, test, system-entrypoint, and evidence whitelist."""

    # Root instructions and current system-planning records used to interpret
    # the acceptance mirror.  The PDF and downloaded upstream trees remain out
    # of the archive.
    for path in (
        "AGENTS.md",
        "PLAN.md",
        "plans/system-capabilities.json",
        "docs/harness-design.md",
        "docs/system-contracts-v090.md",
        "docs/v100-environment.md",
        "docs/MLCC系统详细执行计划书-CaZrO3-BaTiO3-v002.md",
        "docs/remote-acceptance-preparation-v090.md",
    ):
        builder.add_file(path, "project-doc")

    builder.add_tree("mlcc-agent/src/mlcc", "source", pattern="*.py")
    builder.add_tree("mlcc-agent/agents", "agent-contract", pattern="*.md")
    builder.add_tree("mlcc-agent/skills", "agent-skill", pattern="*.md")
    builder.add_tree("mlcc-agent/harness/cases", "harness-case", pattern="*.json")
    builder.add_tree("mlcc-agent/tools", "package-tool", pattern="*.py")
    for path in ("mlcc-agent/pyproject.toml", "mlcc-agent/bundle.json", "mlcc-agent/README.md"):
        builder.add_file(path, "package")
    builder.add_tree("mlcc-agent/tests", "tests", pattern="test_*.py")
    builder.add_tree("scripts/system", "system-entrypoint", pattern="*.py")
    builder.add_tree("scripts/system", "system-entrypoint", pattern="*.sbatch")

    # All project and workspace JSON configuration is explicit and excludes
    # shell environment files and Python environment inventories.
    builder.add_tree("configs", "root-config", pattern="*.json")
    builder.add_tree("workspace/configs", "workspace-config", pattern="*.json")

    for model in (
        "workspace/models/cazro3-pnma-pristine/v001",
        "workspace/models/ni-abacus-engineering-relaxed/v001",
        "workspace/models/ni-fcc-engineering/v001",
        "workspace/models/ni-fcc-engineering-relaxed/v001",
        "workspace/models/ni-fcc-engineering-relaxed/v002",
    ):
        builder.add_tree(model, "model")

    builder.add_file("workspace/sources/cazro3/COD-1532747.cif", "source-data")
    builder.add_tree("workspace/resources/lammps/Ni-u3-stable22Jul2025-update4", "potential-source")

    # Real saved task identities referenced by the tests and all requested
    # system entrypoints.  Deliberately absent test fixtures such as
    # p4-czo-defect-neutral are not staged.
    for task in (
        "workspace/tasks/h0-ni-single-v002",
        "workspace/tasks/h1-ni-cutoff120-v001",
        "workspace/tasks/h1-ni-post-relax-v001",
        "workspace/tasks/h1-ni-relax-v001",
        "workspace/tasks/h1-ni-scf-v001",
        "workspace/tasks/h1-ni-scf-v003",
        "workspace/tasks/h1-ni-strainminus-v004",
        "workspace/tasks/h1-ni-strainplus-v004",
        "workspace/tasks/p4-czo-compatibility-scf-v001",
        "workspace/tasks/p9-ni-lammps-run0-v001",
    ):
        builder.add_tree(task, "task")

    # Reports needed directly by tests/configuration and the latest saved
    # entrypoint evidence.  Older system-v080 reports are retained only for
    # the three installed entrypoint acceptance mirrors.
    for path in (
        "workspace/reports/h0/vasp-comparison-v003.json",
        "workspace/reports/h1/strain-quick-v004",
        "workspace/reports/method-qualification/ca-compatibility-investigation-v001.json",
        "workspace/reports/method-qualification/czo-compatibility-protocol-v001.json",
        "workspace/reports/method-qualification/czo-native-acceptance-v001.json",
        "workspace/reports/method-qualification/czo-upf-headers-v002.json",
        "workspace/reports/p2/cazro3-setting-audit-v001.json",
        "workspace/reports/p2/cazro3-upf-inventory-v001.json",
        "workspace/reports/system-v080/installed-contracts",
        "workspace/reports/system-v080/installed-extensions",
        "workspace/reports/system-v080/installed-public",
        "workspace/reports/system-v080/acceptance.json",
        "workspace/reports/system-v090/unit-tests-v001.txt",
        "workspace/reports/system-v090/phonons/source-v002",
    ):
        path_obj = Path(path)
        if path_obj.suffix:
            builder.add_file(path, "report")
        else:
            builder.add_tree(path, "report")

    # LAMMPS acceptance evidence is kept separate from environment/install
    # probes.  It contains parser/regression records, not a runtime image.
    for path in (
        "workspace/reports/lammps-system-v001/acceptance.json",
        "workspace/reports/lammps-system-v001/execution-ledger.md",
        "workspace/reports/lammps-system-v001/final-review-v002.md",
        "workspace/reports/lammps-system-v001/final-scheduler-resources.json",
        "workspace/reports/lammps-system-v001/native-help-command.json",
        "workspace/reports/lammps-system-v001/native-help.txt",
        "workspace/reports/lammps-system-v001/native-link.json",
        "workspace/reports/lammps-system-v001/original-job41-before-review.json",
        "workspace/reports/lammps-system-v001/predeclared-acceptance.json",
        "workspace/reports/lammps-system-v001/resource-mpi-preflight.json",
        "workspace/reports/lammps-system-v001/run0-acceptance.json",
        "workspace/reports/lammps-system-v001/task-events.json",
        "workspace/reports/lammps-system-v001/unit-tests-native.txt",
        "workspace/reports/lammps-system-v001/unit-tests-preflight.txt",
    ):
        builder.add_file(path, "report")


def stage_archive(
    *,
    repo_root: Path | None = None,
    archive_path: Path | None = None,
    remote_root: str = DEFAULT_REMOTE_ROOT,
) -> dict[str, Any]:
    """Create the archive using only filesystem operations and return a summary."""

    root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    output = (archive_path or (root / DEFAULT_ARCHIVE_RELATIVE)).resolve()
    temp_parent = root / "tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="remote-stage-v001-", dir=temp_parent) as temporary:
        stage_root = Path(temporary)
        builder = StageBuilder(root, stage_root, remote_root)
        _add_whitelist(builder)
        builder.copy_selected()
        builder.write_metadata()
        builder.create_tar(output)
        result = builder.summary()
        result["archive"] = str(output)
        result["archive_bytes"] = output.stat().st_size
        return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = stage_archive(repo_root=args.repo_root, archive_path=args.output, remote_root=args.remote_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["missing_required"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
