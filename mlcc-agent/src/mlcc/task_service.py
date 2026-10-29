"""Shared deterministic dispatch; legacy creators retain their exact arguments."""
import importlib
from pathlib import Path
from .capabilities import describe

def create_task(module_id, operation, **kwargs):
    manifest=describe(module_id)
    if manifest.get('schema_version')=='mlcc.capability.v1':
        if operation!='create': raise ValueError('Select the existing domain create operation')
        provider=manifest['operations'][operation]['provider']
        name,function=provider.split(':')
        return getattr(importlib.import_module(name),function)(**kwargs)
    if operation not in manifest['operations']: raise ValueError('Unknown operation')
    name,function=manifest['task_provider'].split(':')
    return getattr(importlib.import_module(name),function)(operation=operation,**kwargs)

def read_result(task_path, **kwargs):
    from .tasks import load_task
    task=load_task(task_path)
    if task.data.get('execution_protocol')=='mlcc.adapter.v1' or task.data.get('engine')=='scale_compute':
        from .result_views import read_adapter_result
        delivery=read_adapter_result(task_path)
        return {**delivery,'schema':'mlcc.task-result-view.v1','task_id':task.task_id,
                'module_id':task.data.get('module_id'),'engine':task.data.get('engine')}
    module={'abacus':'dft','lammps':'md'}.get(task.data.get('engine'))
    if not module: raise ValueError('No registered result reader')
    from .workflow import inspect_task
    from .contracts import read_json
    decision=inspect_task(task)
    path=decision.get('result_file') or task.data.get('result_file')
    if not path: raise ValueError('No saved parsed result; use the existing explicit parse command first')
    result=read_json(Path(path))
    if result.get('task_id') not in (None,task.task_id): raise ValueError('Saved result identity differs')
    return {'schema':'mlcc.task-result-view.v1','task_id':task.task_id,'module_id':module,
            'engine':task.data['engine'],'result':result,
            'scientific_status':task.data.get('scientific_status','not_checked')}
