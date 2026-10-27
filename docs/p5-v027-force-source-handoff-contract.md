# 0.27: phonon force collection to Gamma source handoff

Frozen 2026-10-23.0.26 remains enabled,0.25 rollback. This is a small source-path handoff in existing functions, not new phonon/dielectric mathematics or orchestration. No new DFT/MD/training.

## Ownership

Main owns this contract, phonon_gamma.py/test_phonon_gamma.py (bounded Luna implementation), integration and release judgment. Existing implementation chat01a15851-eb0c-7832-ba67-4833802afd0f exclusively owns phonon_forces.py/test_phonon_forces.py and workspace/reports/phonon-force-source-handoff-v001/. Do not modify another owner's files. Both modules retain current schemas and CLI routes.

## Collection producer

collect_phonon_forces already receives explicit task_paths and loads their TaskRecords. Add native_task_records: list[str] to the collection, containing absolute canonical task.json file paths. Order follows [manifest.reference, *manifest.displacements], including reference if collected, independently of caller input order. Use the actual loaded task directory, never infer a task from a native-log path or reconstruct directories from task IDs.

An incomplete collection records only actually collected known entries; no null placeholders or invented task paths. Preserve duplicate known entries in their existing input order within each displacement, so the existing duplicate issue is not silently erased. Unknown/missing-identity entries remain in existing checks/issues and cannot make ready_for_harmonic true. Empty input yields an empty list and existing blocked status. Existing source checks, failed-job handling, readiness and qualification remain unchanged. Paths are provenance, not force-set or numerical qualification.

## Gamma consumer

In native_source_bound mode, _validate_source_binding reads collection.native_task_records automatically. If the caller also provides source_binding.native_task_records, normalize each explicit file/directory to its absolute task.json and require identical ordered lists. A conflicting/empty/invalid explicit list must not override the saved list. New collections use reference-first manifest order. For legacy collections lacking the key, retain the existing explicit-list path and its historical ordering; without either list, retain an actionable missing-source error. Do not guess directories. A present malformed collection field is an error, never a legacy fallback.

Every chosen task still passes all existing source, parent, plan, complete displacement-set, method/PP, job, force/unit/atom-map and native evidence checks. Duplicate paths/IDs and missing sources remain rejected. Existing software_math_only cannot acquire native source records. Keep source_bound output task records and downstream provenance; no new numerical qualification flags or mathematical changes.

## Verification and integration

Only exact pytest node IDs for newly added or genuinely affected cases. Before execution, collect that exact list within a small v100 CPU Slurm allocation, save it, and inspect the names/count; then execute the reviewed IDs once. After a diagnosed failure rerun only affected failures. Never use -k or rerun old mathematics/suites. Use existing0.9 Python and0.15 dependencies with explicit0.27 candidate PYTHONPATH; no account override, no automatic retries.

Producer covers input-order normalization, partial/empty/duplicate paths and unchanged blocked statuses. Consumer covers automatic selection, matching explicit list, conflict, legacy explicit and missing-list behavior, with existing validation retained. Reuse any saved native collection/task evidence that actually exists. An incomplete real collection remains blocked; do not invent harmonic/Born data to make it pass. A complete source-handoff software positive must be explicitly labeled software_contract_only, with stubs listed, and never counted as a native Gamma result.

Integrate the changed collection -> Gamma source binding -> existing ionic dielectric source consumption using retained artifacts and existing equations. Public request routing passes source_binding already, so change CLI only if an actual incompatibility is found. Existing epsilon-infinity external tensor input remains an external input, not an ABACUS producer. Full native Gamma/Born/dielectric and scientific production qualification remain incomplete. No repeated0.26 host or old numerical acceptance to substitute for this changed path.
