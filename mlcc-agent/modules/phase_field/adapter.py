"""Windows standard-library JSON adapter entry."""
import sys
sys.dont_write_bytecode=True
from phasefield.adapter_api import handle
from phasefield.common import loads,dumps

if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise ValueError('Request too large')
        result=handle(loads(raw.decode('utf-8-sig')))
    except Exception as e:
        result={'schema_version':'mlcc.adapter-preflight.v1','ready':False,'errors':[{'code':'INVALID_JSON','message':str(e)}],'warnings':[],'checks':[]}
    print(dumps(result))
