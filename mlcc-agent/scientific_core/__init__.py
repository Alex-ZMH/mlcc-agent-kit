"""Optional numerical primitives; importing this root needs only Python's stdlib.

No Runtime, units, tasks, module registration, physical models or QC policy.
Backends must be explicitly imported in their own scientific environment.
"""
from hashlib import sha256
from pathlib import Path
import sys

__version__ = '0.1.0'


def provenance():
    """Identify the actual bundled source; this is not scientific acceptance."""
    root = Path(__file__).resolve().parent
    return {
        'schema_version': 'scientific_core.provenance.v1',
        'version': __version__,
        'source_files': {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
                         for p in sorted(root.rglob('*.py'))},
        'loaded_modules': sorted(n for n in sys.modules
                                 if n == __name__ or n.startswith(__name__+'.')),
    }
