"""Read actual ngspice samples, compare independent references, export SI CSV."""
import numpy as np
from .runner import write
from .reference import impedance,parallel,rc_voltage

def csv(path,names,columns):np.savetxt(path,np.column_stack(columns),delimiter=',',header=','.join(names),comments='',fmt='%.16e')
def ac_result(data,models,path):
    f=data['frequency'].real;v=data['v(port)'];i=data['i(vtest)']
    if np.any(abs(i)==0):raise ValueError('zero port current: no finite impedance')
    with np.errstate(divide='raise',invalid='raise',over='raise'):
        z=v/i;ref=parallel(models,f)
    if not np.isfinite(z).all() or not np.isfinite(ref).all() or np.any(abs(ref)==0):raise ValueError('singular ideal resonance; no finite relative impedance comparison')
    csv(path/'parsed.csv',['frequency_Hz','voltage_real_V','voltage_imag_V','current_into_DUT_real_A','current_into_DUT_imag_A','Z_real_ohm','Z_imag_ohm','Z_abs_ohm','phase_deg','reference_Z_real_ohm','reference_Z_imag_ohm','real_power_RMS_normalized_W'],[f,v.real,v.imag,i.real,i.imag,z.real,z.imag,abs(z),np.angle(z,deg=True),ref.real,ref.imag,(v*np.conj(i)).real])
    k=int(np.argmin(abs(z)));cross=np.flatnonzero(z.imag[:-1]*z.imag[1:]<=0)
    zeros=[float(f[j]-z.imag[j]*(f[j+1]-f[j])/(z.imag[j+1]-z.imag[j])) for j in cross if z.imag[j]!=z.imag[j+1]]
    # Power dissipated in the individual series ESRs and terminal leakage branches.
    loss=np.zeros(len(f))
    for m in models:
        zs=m.esr_ohm+1j*2*np.pi*f*m.esl_H+1/(1j*2*np.pi*f*m.capacitance_F);loss+=m.esr_ohm*abs(v/zs)**2
        if m.leakage_resistance_ohm:loss+=abs(v)**2/m.leakage_resistance_ohm
    realpower=(v*np.conj(i)).real
    r={'complex_relative_error':float(max(abs(z-ref)/abs(ref))),'current_absolute_error_A':float(max(abs(i-1/ref))),'voltage_1V_absolute_error':float(max(abs(v-1))),
       'power_balance_relative_error':float(max(abs(realpower-loss))/max(max(loss),1e-30)),'minimum_real_impedance_ohm':float(min(z.real)),
       'sampled_minimum':{'frequency_Hz':float(f[k]),'magnitude_ohm':float(abs(z[k]))},'imaginary_zero_frequencies_Hz':zeros,'endpoint_phase_deg':[float(np.angle(z[0],deg=True)),float(np.angle(z[-1],deg=True))],
       'samples':len(f),'units':{'impedance':'ohm','frequency':'Hz','voltage':'V','current':'A','power':'W'},'convention':'1V AC phasor, i(vtest) positive into DUT; phasors interpreted as RMS only for normalized power bookkeeping'}
    r['series_branch_SRFs_Hz']=[{'model_name':m.model_name,'frequency_Hz':float(1/(2*np.pi*np.sqrt(m.esl_H*m.capacitance_F))),'definition':'series branch L/C cancellation; not network antiresonance'} for m in models if m.esl_H>0]
    peaks=np.flatnonzero((abs(z)[1:-1]>abs(z)[:-2])&(abs(z)[1:-1]>abs(z)[2:]))+1
    r['sampled_network_local_maxima']=[{'frequency_Hz':float(f[j]),'magnitude_ohm':float(abs(z[j]))} for j in peaks]
    r['resonance_note']='Imaginary zeros are interpolated within the actual sweep only; no SRF claimed for ESL=0 or out-of-band branch cancellation. Sampled maxima alone do not certify network antiresonance.'
    write(path/'metrics.json',r);return r

def transient_result(data,c,m,path):
    t=data['time'];v=data['v(bus)'];feed=data['i(vfeed)'];load=data['i(vload)'];cap=data['i(vcap)'] if m else np.zeros(len(t));v0=(c['supply_V']-c['source_resistance_ohm']*c['baseline_A'])/(1+c['source_resistance_ohm']/m.leakage_resistance_ohm if m and m.leakage_resistance_ohm else 1);active=t>=c['delay_s'];kcl=feed-load-cap
    rmsmask=t>=c['delay_s'];rms=float(np.sqrt(np.trapezoid(cap[rmsmask]**2,t[rmsmask])/(t[-1]-t[rmsmask][0])))
    csv(path/'parsed.csv',['time_s','bus_voltage_V','load_current_A','source_current_into_bus_A','cap_current_into_device_A','cap_terminal_power_W'],[t,v,load,feed,cap,v*cap])
    r={'minimum_voltage_V':float(min(v[active])),'maximum_voltage_V':float(max(v[active])),'baseline_voltage_V':v0,'droop_V':float(v0-min(v[active])),'overshoot_V':float(max(0,max(v[active])-v0)),
       'droop_100ns_after_edge_V':float(v0-np.interp(c['delay_s']+c['rise_s']+1e-7,t,v)),'initial_voltage_error_V':float(abs(v[0]-v0)),'KCL_relative_error':float(max(abs(kcl))/max(max(abs(load)),1e-30)),
       'cap_current_RMS_over_pulse_and_recovery_A':rms,'cap_peak_abs_current_A':float(max(abs(cap))),'net_cap_terminal_energy_J':float(np.trapezoid(v*cap,t)),'max_actual_time_step_s':float(max(np.diff(t))),'samples':len(t),
       'definition':'single delayed finite-rise pulse, DC operating point (no UIC); capacitor current into device is negative while supplying the bus; RMS is over finite pulse/recovery, not periodic steady state'}
    if m:
        branch=cap-v/m.leakage_resistance_ohm if m.leakage_resistance_ohm else cap
        node='v(xcap.nl)' if m.esl_H>0 else 'v(xcap.nr)' if m.esr_ohm>0 else 'v(cp)';energy=.5*m.capacitance_F*data[node]**2+.5*m.esl_H*branch**2;loss=float(np.trapezoid(m.esr_ohm*branch**2+(v*v/m.leakage_resistance_ohm if m.leakage_resistance_ohm else 0),t));terminal=float(np.trapezoid(v*cap,t));change=float(energy[-1]-energy[0]);scale=max(float(np.trapezoid(abs(v*cap),t)),loss,abs(change),1e-30)
        r['energy_balance']={'ESR_dissipation_J':float(np.trapezoid(m.esr_ohm*branch**2,t)),'leakage_dissipation_J':float(np.trapezoid(v*v/m.leakage_resistance_ohm,t)) if m.leakage_resistance_ohm else 0.,'total_dissipation_J':loss,'stored_energy_change_J':change,'terminal_energy_J':terminal,'relative_error':abs(terminal-loss-change)/scale}
        r['energy_balance']['loss_definition']='series ESR plus optional terminal leakage dissipation; current into device signed'
    r['RMS_window_s']=[float(t[rmsmask][0]),float(t[-1])]
    r['units']={'voltage':'V','current':'A','time':'s','power':'W','energy':'J'}
    write(path/'metrics.json',r);return r

def rc_error(data,c,C,path):
    expected=rc_voltage(c,C,data['time']);err=float(max(abs(data['v(bus)']-expected)));csv(path/'rc_reference.csv',['time_s','ngspice_V','analytic_V','error_V'],[data['time'],data['v(bus)'],expected,data['v(bus)']-expected]);return err

def anti_peak(data,flo,fhi):
    f=data['frequency'].real;z=data['v(port)']/data['i(vtest)'];mask=(f>flo)&(f<fhi);ids=np.flatnonzero(mask);k=ids[np.argmax(abs(z[mask]))]
    return {'frequency_Hz':float(f[k]),'magnitude_ohm':float(abs(z[k])),'interior_of_search_band':bool(k>ids[0] and k<ids[-1])}
