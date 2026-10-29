"""Only controlled AC impedance and source/load transient topologies."""
import math
from .model import subcircuit
OPTIONS='.options reltol=1e-8 abstol=1e-12 vntol=1e-10 numdgt=15 method=gear maxord=2'
def end(lines,command):return '\n'.join([*lines,OPTIONS,'.control','set filetype=ascii',command,'write output.raw all','quit','.endc','.end',''])
def ac(models,points,fmin,fmax,single=False):
    if not models or not 0<fmin<=fmax or not isinstance(points,int) or points<1:raise ValueError('valid AC sweep required')
    definitions={}
    for m in models:
        key=m.model_name.lower()
        if key in definitions and definitions[key]!=m:raise ValueError('same case-insensitive model name with conflicting parameters')
        definitions[key]=m
    # A 1-V AC voltage source gives a nonsingular DC operating point even
    # without device leakage. Vtest measures current INTO the DUT, not source current.
    lines=['Controlled MLCC impedance test: 1-V AC, current positive into DUT','Vexc feed 0 DC 0 AC 1','Vtest feed port 0']
    for i,m in enumerate(models):lines.append(f'Xcap{i} port 0 {m.model_name}')
    lines.extend(subcircuit(m) for m in definitions.values())
    lines.append('.save v(port) i(vtest)')
    return end(lines,f'ac {"lin" if single else "dec"} {points} {fmin:.17e} {fmax:.17e}')
def transient(model,c,maxstep):
    for key in ['supply_V','source_resistance_ohm','line_inductance_H','baseline_A','step_A','delay_s','rise_s','hold_s','fall_s','stop_s']:
        v=c[key]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0:raise ValueError(f'invalid {key}')
    if isinstance(maxstep,bool) or not math.isfinite(maxstep) or min(c['source_resistance_ohm'],c['rise_s'],c['fall_s'],maxstep)<=0 or maxstep>c['stop_s'] or c['stop_s']<=c['delay_s']+c['rise_s']+c['hold_s']+c['fall_s']:raise ValueError('finite source impedance, timestep, rise and full timeline required')
    s=lambda x:f'{x:.17e}';t=c['delay_s'];rise=c['rise_s'];fall=t+rise+c['hold_s'];i=c['baseline_A'];hi=i+c['step_A'];times=[(0,i),(t,i),(t+rise,hi),(fall,hi),(fall+c['fall_s'],i),(c['stop_s'],i)]
    lines=['Controlled supply/load transient, DC operating point before delayed pulse',f'Vsupply src 0 {s(c["supply_V"])}',f'Rsource src nr {s(c["source_resistance_ohm"])}'];node='nr'
    if c['line_inductance_H']>0:lines.append(f'Lline nr nl {s(c["line_inductance_H"])}');node='nl'
    lines += [f'Vfeed {node} bus 0','Vload bus load 0','Iload load 0 PWL('+ ' '.join(f'{s(t)} {s(i)}' for t,i in times)+')']
    if model:lines += ['Vcap bus cp 0',f'Xcap cp 0 {model.model_name}',subcircuit(model)]
    capnode='v(xcap.nl)' if model and model.esl_H>0 else 'v(xcap.nr)' if model and model.esr_ohm>0 else 'v(cp)'
    lines.append('.save v(bus) i(vfeed) i(vload)'+(' i(vcap) '+capnode if model else ''))
    # No UIC: solve the DC operating point with baseline current before the pulse.
    return end(lines,f'tran {s(maxstep)} {s(c["stop_s"])} 0 {s(maxstep)}')
