"""One metadata catalog for all domains. Discovery imports no science libraries."""
from pathlib import Path
from .contracts import read_json

ROOT=Path(__file__).resolve().parents[2]

def describe(module_id=None):
    rows=[]
    for path in sorted((ROOT/'modules').glob('*/module.json')):
        value=read_json(path)
        if value['id'] != path.parent.name:
            raise ValueError('Module directory and identity differ')
        if module_id is None or value['id']==module_id:
            rows.append(value)
    if module_id is not None:
        if len(rows)!=1: raise ValueError('Unknown module')
        return rows[0]
    return {'schema':'mlcc.capabilities.v1','modules':rows}
