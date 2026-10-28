"""Windows stdlib entry; stable under -I and arbitrary cwd."""
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
root = Path(__file__).resolve().parent / 'spice_module'
spec = importlib.util.spec_from_file_location('spice_module', root / '__init__.py', submodule_search_locations=[str(root)])
package = importlib.util.module_from_spec(spec)
sys.modules['spice_module'] = package
spec.loader.exec_module(package)
from spice_module.common import loads, dumps
from spice_module.adapter_api import handle

if __name__ == '__main__':
    try:
        raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Request exceeds 2 MiB')
        response = handle(loads(raw.decode('utf-8-sig')))
    except Exception as e:
        response = {'schema_version': 'mlcc.adapter-preflight.v1', 'ready': False, 'errors': [{'code': 'INVALID_JSON', 'message': str(e)}], 'warnings': [], 'checks': []}
    sys.stdout.reconfigure(encoding='utf-8')
    print(dumps(response))
