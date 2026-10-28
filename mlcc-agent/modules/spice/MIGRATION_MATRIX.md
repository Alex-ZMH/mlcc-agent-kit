# Migration scope

| Prototype source | Formal destination | Scope |
|---|---|---|
| model.py | spice_module/model.py | Constant series RLC plus optional terminal leakage; synthetic/manual only |
| netlist.py | spice_module/netlist.py | One shared controlled AC operation (single/parallel), finite-edge transient |
| runner.py | spice_module/runner.py | Real ngspice, strict ASCII native parser, trusted absolute executable |
| results.py / reference.py | spice_module/ | CSV/metrics and independent algebra/RC check; never substitute for ngspice |
| stages.py | spice_module/qualification.py | Explicit 27-analysis qualification fixture only; never every task |
| verify_run.py | spice_module/readback.py | Independent raw→CSV/energy re-read |
| configs/demo.json / validation.json | cases/ | Frozen synthetic fixture and unchanged qualification limits |
| run.py / compare_replay.py / figures.py | harness/ + task plotting | Runtime orchestration, explicit replay comparison, task-local curves |

Excluded: arbitrary netlist execution, nonlinear/material/vendor models, parameter fitting, PCB extraction, periodic ripple qualification, cross-scale transfer, new Agent/Web/scheduler. Material/device validation stays not_checked. Production code never imports experiments or other modules; experiments are read-only qualification references. See SOURCES.json for exact hashes and changes.
