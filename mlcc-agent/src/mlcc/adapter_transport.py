"""One JSON request/response per subprocess; only adapter stdout is protocol."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

from .contracts import FrameworkError, confined, dumps, loads

MAX_PROTOCOL_BYTES = 2 * 1024 * 1024


def invoke(module, request, timeout, log_dir=None):
    entry = confined(module.root, module.manifest['adapter']['entry'])
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    # Binding belongs to the host, never to scientific JSON input.
    command = [module.python, '-u', str(entry)]
    if log_dir:
        Path(log_dir).mkdir(exist_ok=True)
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.run(command, input=dumps(request).encode('utf-8'),
                                     cwd=module.root, env=env, stdout=output, stderr=errors,
                                     timeout=timeout)
            exit_code = process.returncode
        except subprocess.TimeoutExpired as exc:
            raise FrameworkError('ADAPTER_TIMEOUT', f'Adapter exceeded {timeout}s; external child jobs may still exist. Reconcile before any new submission.') from exc
        except OSError as exc:
            raise FrameworkError('ADAPTER_LAUNCH_ERROR', str(exc)) from exc
        finally:
            if log_dir:
                import shutil
                for stream, name in ((output, 'adapter.stdout.json'), (errors, 'adapter.stderr.log')):
                    stream.seek(0)
                    with (Path(log_dir) / name).open('xb') as target:
                        shutil.copyfileobj(stream, target)
        output.seek(0)
        raw = output.read(MAX_PROTOCOL_BYTES + 1)
    if len(raw) > MAX_PROTOCOL_BYTES:
        raise FrameworkError('ADAPTER_PROTOCOL_ERROR', 'Response exceeds 2 MiB; use artifact references')
    try:
        response = loads(raw.decode('utf-8-sig'))
    except (UnicodeDecodeError, FrameworkError) as exc:
        raise FrameworkError('ADAPTER_PROTOCOL_ERROR', f'Adapter stdout is not one strict JSON document (exit {exit_code}): {exc}') from exc
    return response, exit_code
