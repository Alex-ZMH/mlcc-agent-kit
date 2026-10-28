"""Load the fixed stdlib compute runtime without shadowing platform mlcc."""
import importlib
import importlib.util
from pathlib import Path
import sys


def load():
    root = Path(__file__).resolve().parent
    name = '_mlcc_compute'
    init = root / 'mlcc/__init__.py'
    existing = sys.modules.get(name)
    if existing is not None:
        if Path(existing.__file__).resolve() != init:
            raise ImportError('Compute runtime is already bound to another Bundle')
    else:
        spec = importlib.util.spec_from_file_location(name, init, submodule_search_locations=[str(init.parent)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[name] = package
        spec.loader.exec_module(package)
    return (importlib.import_module(name + '.contracts'),
            importlib.import_module(name + '.registry').Registry,
            importlib.import_module(name + '.runtime').Runtime)
