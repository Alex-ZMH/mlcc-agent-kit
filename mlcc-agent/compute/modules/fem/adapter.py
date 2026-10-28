"""Fixed Windows entry: one public JSON request/response; standard library only."""
import sys
sys.dont_write_bytecode = True
from device_fem.adapter_api import handle
from device_fem.common import ModuleError, dumps, loads

if __name__ == '__main__':
    try:
        text = sys.stdin.buffer.read(2*1024*1024+1)
        if len(text)>2*1024*1024:
            raise ModuleError('INVALID_JSON','Request too large')
        response = handle(loads(text.decode('utf-8-sig')))
    except Exception as exc:
        response = {'schema_version':'mlcc.adapter-preflight.v1','ready':False,
                    'errors':[{'code':getattr(exc,'code','INVALID_JSON'),'message':str(exc)}],
                    'warnings':[],'checks':[]}
    print(dumps(response))
