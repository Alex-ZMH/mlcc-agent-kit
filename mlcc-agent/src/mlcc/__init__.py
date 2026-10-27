"""Small, explicit MLCC execution adapters.

The package deliberately keeps site control separate from scientific engines.
Numerical programs are submitted to Slurm through :mod:`mlcc.site_runner`.
"""

from .tasks import TaskRecord, load_task, save_task
from .site_runner import SiteConfig, SiteRunner, RunnerError

__all__ = [
    "RunnerError",
    "SiteConfig",
    "SiteRunner",
    "TaskRecord",
    "load_task",
    "save_task",
]

