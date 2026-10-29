# Four independent scientific scales

This directory is part of the full MLCC Bundle. It contains the four existing
modules, their schemas/examples/method Skills, the stdlib runtime, the unique
unit converter and Scientific Core. SOURCE_MANIFEST.json identifies imported
source files; it does not certify scientific applicability. Work directories,
credentials, private deployment configuration and historical runs are excluded.

The platform package remains `mlcc`. bootstrap.py loads this runtime using a
private Python package name in a separate execution path; it does not install
or shadow the platform package, alter its CLI, or start another LLM Agent.

run_scale.py is a fixed entry inside a host-created Slurm task. The platform
creator copies this full source tree into task-local payload/ before transfer.
The host chooses explicit native_linux bindings and budgets. Runtime outputs
remain beneath that task's payload/outputs/ and are collected by SiteRunner.
Do not edit a submitted payload or remove its execution claim to rerun it.

The original module documents preserve method history and may reference
historical evidence outside this source subset. Current integration status is
reported separately in docs/four-scale-integration-2026-10-28.md at repository
root. Use platform create-scale/parse-scale and the existing task lifecycle;
historical module-development CLI examples are not a second public controller.

Deployment requires the **complete Bundle**, not the Python wheel alone. No
scientific dependency is added to the platform public import layer. DFT/MD and
their native unit systems are not included or converted by this directory.
