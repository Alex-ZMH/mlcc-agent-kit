"""Fixed Bundle loader for native science_entry scripts, including Python -I.

Executed via runpy.run_path by trusted entrypoints; never modifies sys.path or
searches an installed fallback. The caller pins the required Core version.
"""
import importlib.util
from pathlib import Path
import sys


def load(entry, *, required_version):
    root = Path(entry).resolve().parents[2] / 'scientific_core'
    init = root / '__init__.py'
    existing = sys.modules.get('scientific_core')
    if existing is not None:
        if Path(existing.__file__).resolve() != init.resolve():
            raise ImportError('Scientific Core already loaded from another Bundle')
        package = existing
    else:
        spec = importlib.util.spec_from_file_location(
            'scientific_core', init, submodule_search_locations=[str(root)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = package
        try:
            spec.loader.exec_module(package)
        except BaseException:
            del sys.modules[spec.name]
            raise
    if package.__version__ != required_version:
        raise ImportError(f'Scientific Core {required_version} required; got {package.__version__}')
    return package
