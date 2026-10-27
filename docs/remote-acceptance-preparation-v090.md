# MLCC v0.9.0 remote acceptance preparation

The archive produced by `scripts/system/stage_remote_acceptance.py` is a
read-only project mirror for
`/home/v100/projects/mlcc/development/0.9.0/project`. It contains the
`mlcc-agent` source and tests, the `scripts/system` entry points, the root and
workspace JSON configuration needed by those entry points, the explicitly
selected real models and saved tasks, and the saved reports used by the
tests and acceptance records.

The archive does not contain a Python environment, upstream trees, release
trees, VASP executables, POTCAR files, credentials, wavefunction files, or
charge-density restart files. It also does not submit a job or run any
scientific post-processing. The copied native structures, logs, and other
non-JSON artifacts retain their source bytes. JSON metadata is rewritten only
when it contains an absolute `D:/project/mlcc` or `D:\project\mlcc` path;
`project/source-relocation.json` records every such replacement. Existing
Linux `/home/v100/...` paths remain as recorded.

After the archive is transferred and extracted on v100, install the package
dependencies into the server-managed virtual environment and run the chosen
system verification commands from the extracted project. The archive is an
acceptance mirror: existing scheduler IDs and reports are evidence copies and
must not be interpreted as new calculations or production qualification.

