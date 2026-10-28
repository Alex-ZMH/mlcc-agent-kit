"""rve task factory and parser, using the shared TaskRecord/SiteRunner."""
from .adapter_tasks import create_scale_task, read_scale_result

def create_task(**kwargs):
    return create_scale_task(module_id='rve', **kwargs)

def read_result(task_path):
    return read_scale_result(task_path)
