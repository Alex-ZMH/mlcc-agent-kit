"""Fail closed on ngspice error, missing/incomplete data or invalid raw format."""
from pathlib import Path
import subprocess,os,re,json,time
import numpy as np

def write(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),encoding='utf-8')

def read_raw(path):
    if Path(path).stat().st_size>256*1024*1024:raise ValueError('raw exceeds module byte budget')
    lines=Path(path).read_text(encoding='utf-8').splitlines();meta={}
    if lines.count('Values:')!=1 or lines.count('Variables:')!=1:raise ValueError('exactly one ASCII plot required')
    variables=lines.index('Variables:');start=lines.index('Values:');
    for line in lines[:variables]:
        if ':' in line:
            k,v=line.split(':',1)
            if k.strip() in meta:raise ValueError('duplicate raw metadata')
            meta[k.strip()]=v.strip()
    if meta.get('Flags') not in ['real','complex']:raise ValueError('unsupported plot flags')
    count=int(meta['No. Variables']);points=int(meta['No. Points']);names=[]
    for i,line in enumerate(lines[variables+1:start]):
        parts=line.split()
        if len(parts)<3 or int(parts[0])!=i:raise ValueError('invalid variable table')
        names.append(parts[1].lower())
    if len(names)!=count or len(set(names))!=count or not 1<=points<=500000 or not 1<=count<=32:raise ValueError('raw variable/point count mismatch or resource limit')
    vals=[line.split() for line in lines[start+1:] if line.strip()]
    if len(vals)!=points*count:raise ValueError('truncated or multiple raw plots')
    data=np.empty((points,count),complex if meta['Flags']=='complex' else float)
    for i in range(points):
        for j in range(count):
            parts=vals[i*count+j]
            if j==0:
                if len(parts)!=2 or int(parts[0])!=i:raise ValueError('invalid point index')
                token=parts[1]
            else:
                if len(parts)!=1:raise ValueError('invalid value row')
                token=parts[0]
            data[i,j]=complex(*map(float,token.split(','))) if meta['Flags']=='complex' else float(token)
    if not np.isfinite(data).all():raise ValueError('nonfinite raw values')
    scale=data[:,0].real
    if np.any(abs(data[:,0].imag)>1e-20) or np.any(np.diff(scale)<=0):raise ValueError('invalid scale')
    return meta,{n:data[:,i] for i,n in enumerate(names)}

def execute(netlist,out,analysis,expected_end,required,minimum_points=2,timeout=120,*,executable,expected_start=None,expected_points=None,maxstep=None,max_points=500000):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);(out/'circuit.cir').write_text(netlist,encoding='utf-8');exe=str(executable)
    if not Path(exe).is_absolute() or not Path(exe).is_file():raise RuntimeError('trusted absolute ngspice executable required')
    command=[exe,'-n','-b','-o','ngspice.log','circuit.cir'];start=time.perf_counter();record={'command':command,'cwd':str(out.resolve()),'analysis':analysis,'expected_end':expected_end,'expected_start':expected_start,'expected_points':expected_points,'maxstep':maxstep,'timeout_seconds':timeout}
    try:
        p=subprocess.run(command,cwd=out,env={**os.environ,'LC_ALL':'C','SPICE_ASCIIRAWFILE':'1'},capture_output=True,text=True,timeout=timeout)
        (out/'stdout.txt').write_text(p.stdout,encoding='utf-8');(out/'stderr.txt').write_text(p.stderr,encoding='utf-8');log=(out/'ngspice.log').read_text() if (out/'ngspice.log').exists() else '';record['returncode']=p.returncode
        if p.returncode or re.search(r'(?im)(^\s*(fatal|error)\b|timestep too small|singular matrix|simulation interrupted|doanalyses:|run simulation\(s\) aborted|no data rows)',log+'\n'+p.stderr+'\n'+p.stdout):raise RuntimeError('ngspice failed; inspect preserved log')
        meta,data=read_raw(out/'output.raw');scale='frequency' if analysis=='ac' else 'time'
        if not meta['Plotname'].lower().startswith('ac' if analysis=='ac' else 'transient'):raise RuntimeError('wrong analysis plot')
        if meta['Flags']!=('complex' if analysis=='ac' else 'real') or next(iter(data))!=scale:raise RuntimeError('wrong analysis flags/scale')
        if not all(n in data for n in [scale,*required]) or len(data[scale])<minimum_points:raise RuntimeError('missing vectors or points')
        if abs(data[scale][-1].real/expected_end-1)>1e-8:raise RuntimeError('analysis stopped before requested end')
        x=data[scale].real
        if len(x)>max_points:raise RuntimeError('actual point budget exceeded')
        if expected_start is not None and abs(x[0]-expected_start)>max(abs(expected_start)*1e-8,1e-30):raise RuntimeError('incorrect analysis start')
        if expected_points is not None and len(x)!=expected_points:raise RuntimeError('incorrect sampling point count')
        if analysis=='ac' and len(x)>1 and expected_start is not None:
            expected=np.geomspace(expected_start,expected_end,len(x))
            if np.max(abs(x/expected-1))>1e-8:raise RuntimeError('invalid logarithmic sampling grid')
        if maxstep is not None and len(x)>1 and np.max(np.diff(x))>maxstep*(1+1e-6):raise RuntimeError('actual timestep exceeds requested maxstep')
        record.update(status='PASS',seconds=time.perf_counter()-start,points=len(data[scale]),vectors=list(data),raw_metadata=meta);write(out/'execution.json',record);return data
    except Exception as exc:
        if isinstance(exc,subprocess.TimeoutExpired):
            record['ngspice_termination']='direct subprocess.run child killed and waited; outer WSL timeout independently may be unknown'
            for name,value in [('stdout.txt',exc.stdout),('stderr.txt',exc.stderr)]:
                if value is not None:(out/name).write_bytes(value.encode() if isinstance(value,str) else value)
        record.update(status='FAIL',seconds=time.perf_counter()-start,error=f'{type(exc).__name__}: {exc}');write(out/'execution.json',record);raise
