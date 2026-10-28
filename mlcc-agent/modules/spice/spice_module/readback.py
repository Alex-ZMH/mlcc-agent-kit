"""Reopen raw ngspice samples and independently verify CSV, units and conservation."""
from pathlib import Path
import sys,json,hashlib
import numpy as np
from .runner import read_raw,write
from .model import MLCC
from .reference import parallel
def verify(root):
    root=Path(root);records={}
    for file in sorted(root.rglob('execution.json')):
        p=file.parent;r=json.loads(file.read_text());inp=json.loads((p/'input.json').read_text());meta,d=read_raw(p/'output.raw');csv=np.atleast_1d(np.genfromtxt(p/'parsed.csv',delimiter=',',names=True))
        assert r['status']=='PASS' and r['returncode']==0 and r['points']==len(csv)
        checks={};errors={}
        def compare(name,a,b):
            err=float(max(abs(a-b))/max(float(max(abs(a))),1e-30));errors[name]=err;checks[name]=err<1e-12
        if r['analysis']=='ac':
            f=d['frequency'].real;V=d['v(port)'];I=d['i(vtest)'];Z=V/I;reference=parallel([MLCC.from_dict(m) for m in inp['models']],f)
            compare('frequency',f,csv['frequency_Hz']);compare('raw_CSV_Z',Z,csv['Z_real_ohm']+1j*csv['Z_imag_ohm']);compare('raw_CSV_voltage',V,csv['voltage_real_V']+1j*csv['voltage_imag_V']);compare('raw_CSV_current',I,csv['current_into_DUT_real_A']+1j*csv['current_into_DUT_imag_A'])
            errors['analytic_complex_Z']=float(max(abs(Z-reference)/abs(reference)));checks['analytic_complex_Z']=errors['analytic_complex_Z']<1e-8
            compare('power_RMS_units',np.real(V*np.conj(I)),csv['real_power_RMS_normalized_W'])
        else:
            t=d['time'];V=d['v(bus)'];feed=d['i(vfeed)'];load=d['i(vload)'];cap=d.get('i(vcap)',np.zeros(len(t)));compare('raw_CSV_time',t,csv['time_s']);compare('raw_CSV_voltage',V,csv['bus_voltage_V']);compare('raw_CSV_cap_current',cap,csv['cap_current_into_device_A']);compare('power_units_sign',V*cap,csv['cap_terminal_power_W'])
            compare('raw_CSV_source_current',feed,csv['source_current_into_bus_A']);compare('raw_CSV_load_current',load,csv['load_current_A'])
            errors['KCL']=float(max(abs(feed-load-cap))/max(max(abs(load)),1e-30));checks['KCL']=errors['KCL']<1e-6
            c=inp['circuit'];supplied=np.trapezoid(c['supply_V']*feed,t);loadenergy=np.trapezoid(V*load,t);Rloss=np.trapezoid(c['source_resistance_ohm']*feed**2,t);capenergy=np.trapezoid(V*cap,t);linechange=.5*c['line_inductance_H']*(feed[-1]**2-feed[0]**2)
            errors['supply_load_line_cap_energy']=float(abs(supplied-loadenergy-Rloss-capenergy-linechange)/max(abs(supplied),1e-30));checks['supply_load_line_cap_energy']=errors['supply_load_line_cap_energy']<.003
        records[str(p.relative_to(root))]={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'errors':errors,'raw_sha256':hashlib.sha256((p/'output.raw').read_bytes()).hexdigest()}
    data={'status':'PASS' if records and all(r['status']=='PASS' for r in records.values()) else 'FAIL','circuits':len(records),'records':records};write(root/'readback.json',data);print(data['status'],len(records),'raw/CSV/conservation checks',flush=True)
    if data['status']!='PASS':raise RuntimeError('saved-result verification failed')
    return data
if __name__=='__main__':verify(Path(sys.argv[1]).resolve())
