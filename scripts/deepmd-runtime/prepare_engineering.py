"""Prepare the bounded engineering experiment inside a CPU Slurm job."""
import argparse
import json
from pathlib import Path

from mlcc_deepmd.dataset import convert_to_deepmd
from mlcc_deepmd.training import DeepMDTrainingConfig, write_sbatch_script

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--site", type=Path, required=True)
args = parser.parse_args()
site = json.loads(args.site.read_text())
root = Path(site["remote_root"])
project = root / "project"
experiment = root / "engineering-v001"
experiment.mkdir(exist_ok=False)
source_manifest = {
    "schema": "mlcc.deepmd-source-manifest.v1", "engine": "abacus",
    "method_set": "ni-oncv-pbe18-pw-engineering-v001",
    "virial": {"source": "result.stress_GPa", "sign": "source_stress_times_volume", "input_unit": "GPa", "output_unit": "eV"},
    "sources": [
        {"task_id": name, "path": str(project / "workspace/tasks" / name), "split": "train", "source_group": "ni-distorted-relax-path"}
        for name in ("h1-ni-scf-v001", "h1-ni-relax-v001")
    ],
}
(experiment / "source-manifest.json").write_text(json.dumps(source_manifest, indent=2) + "\n")
dataset = convert_to_deepmd(source_manifest, experiment / "dataset")
runtime = Path(site["runtime_prefix"])
for gpus in site["gpu_counts"]:
    directory = experiment / f"train-{gpus}gpu"
    directory.mkdir()
    train_input = {
        "model": {
            "type_map": dataset["type_map"],
            "descriptor": {"type": "se_e2_a", "rcut": 4.0, "rcut_smth": 3.5, "sel": [128],
                           "neuron": [8, 16, 32], "axis_neuron": 4, "precision": "float64", "seed": site["seed"]},
            "fitting_net": {"neuron": [32, 32], "resnet_dt": False, "precision": "float64", "seed": site["seed"]},
        },
        "learning_rate": {"type": "exp", "start_lr": 0.001, "stop_lr": 0.0001, "decay_steps": 50},
        "loss": {"type": "ener", "start_pref_e": 0.02, "limit_pref_e": 1.0,
                 "start_pref_f": 100.0, "limit_pref_f": 1.0, "start_pref_v": 0.1, "limit_pref_v": 1.0},
        "training": {
            "training_data": {"systems": [str(experiment / "dataset" / p) for p in dataset["training_systems"]], "batch_size": 1},
            "numb_steps": site["steps"], "seed": site["seed"], "disp_file": "lcurve.out",
            "disp_freq": 10, "save_freq": site["steps"], "save_ckpt": "model.ckpt",
        },
    }
    input_file = directory / "input.json"
    input_file.write_text(json.dumps(train_input, indent=2) + "\n")
    config = DeepMDTrainingConfig.from_input_json(
        input_file, workdir=directory, nproc_per_node=gpus, frozen_model="frozen_model.pth",
        cpus_per_task=2 * gpus, mem_mib=24576 if gpus == 4 else 12288,
        dp_executable=str(runtime / "bin/dp"), torchrun_executable=str(runtime / "bin/torchrun"),
        environment={"NUM_WORKERS": "0", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
        time="00:15:00", job_name=f"mlcc-dp-{gpus}gpu",
    )
    write_sbatch_script(config)
frame = dataset["systems"][0]["frames"][0]
frame["elements"] = frame["symbols"]
frame["source_task_id"] = frame["task_id"]
(experiment / "interface-frame.json").write_text(json.dumps(frame, indent=2) + "\n")
print(json.dumps({"experiment": str(experiment), "frames": len(dataset["sources"]),
                  "training_systems": dataset["training_systems"], "validation_systems": dataset["validation_systems"]}))
