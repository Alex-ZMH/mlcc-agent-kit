"""Small standalone commands; numerical commands run on v100 through Slurm."""
import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    data = commands.add_parser("dataset")
    data.add_argument("manifest", type=Path)
    data.add_argument("output", type=Path)
    training = commands.add_parser("training-plan")
    training.add_argument("config", type=Path)
    create = commands.add_parser("create-task")
    create.add_argument("request", type=Path)
    handoff = commands.add_parser("finalize-task")
    handoff.add_argument("task", type=Path)
    handoff.add_argument("scheduler_record", type=Path)
    prepare = commands.add_parser("interface-prepare")
    prepare.add_argument("frame", type=Path)
    prepare.add_argument("model", type=Path)
    prepare.add_argument("output", type=Path)
    prepare.add_argument("--type-map", nargs="+", required=True)
    prepare.add_argument("--plugin")
    for name in ("interface-evaluate", "interface-compare"):
        command = commands.add_parser(name)
        command.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    if args.action == "dataset":
        from .dataset import convert_to_deepmd
        result = convert_to_deepmd(args.manifest, args.output)
    elif args.action == "training-plan":
        from .training import DeepMDTrainingConfig, write_sbatch_script
        config = DeepMDTrainingConfig.from_mapping(json.loads(args.config.read_text(encoding="utf-8")))
        result = {"script": str(write_sbatch_script(config)), "manifest": config.manifest()}
    elif args.action == "create-task":
        from .training import DeepMDTrainingConfig
        from .integration import create_training_task
        request = json.loads(args.request.read_text(encoding="utf-8"))
        result = create_training_task(
            request["workspace"], request["task_id"], DeepMDTrainingConfig.from_mapping(request["training"]),
            request["input_file"], request["dataset_manifest"], request["interface_acceptance"],
            account=request["account"],
            dataset_remote_root=request["dataset_remote_root"],
        ).data
    elif args.action == "finalize-task":
        from .integration import finalize_training_task
        result = finalize_training_task(
            args.task, json.loads(args.scheduler_record.read_text(encoding="utf-8"))
        ).data
    elif args.action == "interface-prepare":
        from .inference import prepare_interface_case
        result = prepare_interface_case(json.loads(args.frame.read_text(encoding="utf-8")),
                                        args.model, args.output, type_map=args.type_map, plugin=args.plugin)
    elif args.action == "interface-evaluate":
        from .inference import evaluate_frozen
        result = evaluate_frozen(args.directory)
    else:
        from .inference import compare_interface
        result = compare_interface(args.directory)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
