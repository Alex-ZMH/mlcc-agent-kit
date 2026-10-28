"""Small stdlib CLI for the same scale and SiteRunner functions as MLCC."""
import argparse
import json
from pathlib import Path
from .scale_tasks import create_scale_task, describe_scales, read_scale_result
from .site_runner import RunnerError, runner_for_task


def register(subparsers):
    subparsers.add_parser('list-scales')
    describe = subparsers.add_parser('describe-scale')
    describe.add_argument('--module', required=True)
    describe.add_argument('--operation', required=True)
    create = subparsers.add_parser('create-scale')
    create.add_argument('--module', required=True, choices=('fem', 'phase_field', 'rve', 'spice'))
    create.add_argument('--operation', required=True)
    for name in ('input', 'site', 'request'):
        create.add_argument('--' + name, type=Path, required=True)
    parse = subparsers.add_parser('parse-scale')
    parse.add_argument('--task', type=Path, required=True)


def dispatch(args):
    if args.action == 'list-scales':
        return describe_scales()
    if args.action == 'describe-scale':
        return describe_scales(args.module, args.operation)
    if args.action == 'create-scale':
        return create_scale_task(module_id=args.module, operation=args.operation,
                                 input_path=args.input, site_path=args.site, request_path=args.request)
    return read_scale_result(args.task)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    register(actions)
    for name in ('prepare', 'transfer', 'submit', 'query', 'cancel', 'collect'):
        action = actions.add_parser(name)
        action.add_argument('--site', type=Path, required=True)
        action.add_argument('--task', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action in ('list-scales', 'describe-scale', 'create-scale', 'parse-scale'):
            result = dispatch(args)
        else:
            runner, task = runner_for_task(args.site, args.task)
            result = getattr(runner, args.action)(task)
    except (RunnerError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
