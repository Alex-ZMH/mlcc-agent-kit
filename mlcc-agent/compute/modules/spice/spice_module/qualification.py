from pathlib import Path
from dataclasses import replace
import numpy as np
from .model import MLCC
from .runner import execute,write
from .netlist import ac,transient
from .results import ac_result,transient_result,rc_error,anti_peak

def ac_case(root,name,models,points,lo,hi,single=False):
    out=root/name;data=execute(ac(models,points,lo,hi,single),out,'ac',hi,['v(port)','i(vtest)'],1 if single else 2);write(out/'input.json',{'models':[m.as_dict() for m in models],'points':points,'fmin_Hz':lo,'fmax_Hz':hi,'single_frequency':single});return ac_result(data,models,out),data
def tran_case(root,name,m,c,h):
    out=root/name;data=execute(transient(m,c,h),out,'tran',c['stop_s'],['v(bus)','i(vfeed)','i(vload)']+(['i(vcap)'] if m else []));write(out/'input.json',{'model':m.as_dict() if m else None,'circuit':c,'maxstep_s':h});return transient_result(data,c,m,out),data

def single(root,cfg,limits):
    root=root/'single';m=MLCC.from_dict(cfg['models']['single']);f0=1/(2*np.pi*np.sqrt(m.esl_H*m.capacitance_F));rows={};sweep=cfg['ac']
    for ppd in sweep['points_per_decade']:
        name=f'ppd{ppd}';rows[name],_=ac_case(root,name,[m],ppd,sweep['fmin_Hz'],sweep['fmax_Hz'])
    rows['at_srf'],_=ac_case(root,'at_srf',[m],1,f0,f0,True)
    leak=replace(m,model_name='single_leak',leakage_resistance_ohm=1e6);rows['finite_leak'],_=ac_case(root,'finite_leak',[leak],sweep['points_per_decade'][-1],.001,sweep['fmax_Hz'])
    # Two real ngspice ideal limits, not parser/interface mocks.
    for name,R,L in [('ideal_C',0.,0.),('zero_ESL',.05,0.),('zero_ESR',0.,m.esl_H)]:
        ideal=replace(m,model_name=name,esr_ohm=R,esl_H=L);rows[name],_=ac_case(root,name,[ideal],100,1e3,1e9)
    fine=rows[f'ppd{sweep["points_per_decade"][-1]}'];srferr=abs(fine['imaginary_zero_frequencies_Hz'][0]/f0-1);minimumerr=abs(fine['sampled_minimum']['frequency_Hz']/f0-1);ESRerr=abs(rows['at_srf']['sampled_minimum']['magnitude_ohm']/m.esr_ohm-1)
    checks={'AC_formula':all(r['complex_relative_error']<limits['ac_complex_relative_error'] for r in rows.values()),'AC_current':all(r['current_absolute_error_A']<limits['ac_current_absolute_error_A'] for r in rows.values()),
            'SRF_zero':srferr<limits['srf_interpolated_relative_error'],'SRF_sample':minimumerr<limits['srf_sampled_frequency_relative_error'],'ESR_exact':ESRerr<limits['exact_resonance_esr_relative_error'],
            'phase':abs(fine['endpoint_phase_deg'][0]+90)<limits['phase_endpoint_distance_deg'] and abs(fine['endpoint_phase_deg'][1]-90)<limits['phase_endpoint_distance_deg'],'power_sign_units':all(r['power_balance_relative_error']<1e-8 and r['minimum_real_impedance_ohm']>-1e-10 for r in rows.values())}
    result={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'analytic_SRF_Hz':f0,'interpolated_SRF_relative_error':srferr,'sampled_minimum_frequency_relative_error':minimumerr,'exact_SRF_ESR_relative_error':ESRerr,'cases':rows};write(root/'summary.json',result)
    if result['status']!='PASS':raise RuntimeError('single MLCC validation failed')
    return result

def decoupling(root,cfg,limits):
    root=root/'decoupling';m=MLCC.from_dict(cfg['models']['decap']);ideal=replace(m,model_name='ideal_decap',esr_ohm=0.,esl_H=0.);c=cfg['transient'];rows={};rc={}
    for h in cfg['transient_maxsteps_s']:
        for name,cap in [('no_cap',None),('ideal_cap',ideal),('MLCC',m)]:
            key=f'{name}_h{h:g}';rows[key],_=tran_case(root,key,cap,c,h)
    for h in cfg['rc_maxsteps_s']:
        key=f'RC_h{h:g}';row,data=tran_case(root,key,ideal,cfg['rc_reference'],h);rc[key]={'max_error_V':rc_error(data,cfg['rc_reference'],ideal.capacitance_F,root/key),'metrics':row}
    hs=cfg['transient_maxsteps_s'];changes={};rmschanges={}
    for name in ['no_cap','ideal_cap','MLCC']:
        fine=rows[f'{name}_h{hs[-1]:g}'];medium=rows[f'{name}_h{hs[-2]:g}'];changes[name]={key:abs(fine[key]-medium[key]) for key in ['minimum_voltage_V','maximum_voltage_V','droop_V','overshoot_V','droop_100ns_after_edge_V']};rmschanges[name]=abs(fine['cap_current_RMS_over_pulse_and_recovery_A']-medium['cap_current_RMS_over_pulse_and_recovery_A'])/max(fine['cap_current_RMS_over_pulse_and_recovery_A'],1e-30)
    allrows=[*rows.values(),*[r['metrics'] for r in rc.values()]]
    checks={'RC_closed_form':max(r['max_error_V'] for r in rc.values())<limits['RC_reference_max_error_V'],'RC_refines':list(rc.values())[-1]['max_error_V']<list(rc.values())[0]['max_error_V'],
            'KCL':max(r['KCL_relative_error'] for r in allrows)<limits['transient_KCL_relative_error'],'DC_initial':max(r['initial_voltage_error_V'] for r in allrows)<limits['initial_operating_point_error_V'],
            'timestep_metrics':max(v for row in changes.values() for v in row.values())<limits['transient_fine_metric_change_V'],'timestep_RMS':max(rmschanges.values())<limits['transient_fine_RMS_relative_change'],
            'energy_balance':max(r['energy_balance']['relative_error'] for r in allrows if 'energy_balance' in r)<limits['transient_energy_relative_error'],
            'droop_direction':all(r['droop_V']>0 for r in rows.values()),'peak_decoupling':rows[f'ideal_cap_h{hs[-1]:g}']['droop_V']<rows[f'no_cap_h{hs[-1]:g}']['droop_V'],
            'actual_tmax':all(r['max_actual_time_step_s']<=h*(1+1e-6) for h in hs for r in [rows[f'{name}_h{h:g}'] for name in ['no_cap','ideal_cap','MLCC']])}
    result={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'cases':rows,'RC_reference':rc,'fine_metric_changes_V':changes,'fine_RMS_relative_changes':rmschanges};write(root/'summary.json',result)
    if result['status']!='PASS':raise RuntimeError('decoupling transient validation failed')
    return result

def parallel_demo(root,cfg,limits):
    root=root/'parallel';A=MLCC.from_dict(cfg['models']['parallel_A']);B=MLCC.from_dict(cfg['models']['parallel_B']);D=replace(B,model_name='parallel_b_damped',esr_ohm=cfg['parallel']['damped_B_esr_ohm']);s=cfg['parallel'];rows={};peaks={};freqs=[1/(2*np.pi*np.sqrt(m.esl_H*m.capacitance_F)) for m in [A,B]]
    for name,models in [('A',[A]),('B',[B]),('AB',[A,B]),('AB_damped',[A,D])]:
        for ppd in (s['points_per_decade'] if name in ['AB','AB_damped'] else [s['points_per_decade'][-1]]):
            key=f'{name}_ppd{ppd}';rows[key],data=ac_case(root,key,models,ppd,s['fmin_Hz'],s['fmax_Hz']);peaks[key]=anti_peak(data,min(freqs)*1.03,max(freqs)*.97)
    fine=f'AB_ppd{s["points_per_decade"][-1]}';coarse=f'AB_ppd{s["points_per_decade"][-2]}';damped=f'AB_damped_ppd{s["points_per_decade"][-1]}';ratio=peaks[damped]['magnitude_ohm']/peaks[fine]['magnitude_ohm'];freqchange=abs(peaks[fine]['frequency_Hz']/peaks[coarse]['frequency_Hz']-1);ampchange=abs(peaks[fine]['magnitude_ohm']/peaks[coarse]['magnitude_ohm']-1)
    checks={'parallel_formula':max(r['complex_relative_error'] for r in rows.values())<limits['ac_complex_relative_error'],'passive_power':max(r['power_balance_relative_error'] for r in rows.values())<1e-8,
            'actual_antiresonance':peaks[fine]['interior_of_search_band'],'damping':ratio<limits['damped_peak_ratio_max'],'peak_frequency_sampling':freqchange<limits['parallel_peak_fine_frequency_relative_change'],'peak_amplitude_sampling':ampchange<limits['parallel_peak_fine_amplitude_relative_change']}
    result={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'single_series_SRFs_Hz':freqs,'peaks_between_SRFs':peaks,'damped_to_undamped_peak_ratio':ratio,'fine_peak_frequency_relative_change':freqchange,'fine_peak_amplitude_relative_change':ampchange,'cases':rows,'topology':'two independent series RLC branches in parallel; no shared PCB L'};write(root/'summary.json',result)
    if result['status']!='PASS':raise RuntimeError('parallel validation failed')
    return result
