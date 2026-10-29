"""Scientific worker: native ngspice first, independent diagnostics second."""
import importlib.metadata
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from .common import ROOT, require, digest, file_hash, write_json


def probe(executable):
    exe = Path(executable)
    require(exe.is_absolute() and exe.is_file(), 'Absolute configured ngspice missing', 'BACKEND_UNAVAILABLE')
    p = subprocess.run([str(exe), '--version'], capture_output=True, text=True, timeout=3, shell=False)
    version = re.search(r'ngspice-(\d+)', p.stdout)
    require(p.returncode == 0 and version and version.group(1) == '41', 'This migration requires validated ngspice 41; no fallback', 'BACKEND_UNAVAILABLE')
    return {'ready':True, 'python':sys.executable, 'python_version':platform.python_version(),
            'ngspice_executable':str(exe), 'backend_version':version.group(1), 'ngspice_version_text':p.stdout,
            'packages':{k:importlib.metadata.version(k) for k in ('numpy','matplotlib')}}


def check(name, passed, message):
    return {'id':name, 'status':'passed' if passed else 'failed', 'message':message}


def plot(data, analysis, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    if analysis == 'ac':
        f = data['frequency'].real; z = data['v(port)']/data['i(vtest)']
        fig, axes = plt.subplots(2,1,figsize=(9,6), layout='constrained')
        axes[0].loglog(f,abs(z),marker='.' if len(f)==1 else None)
        axes[0].set_ylabel('|Z| [ohm]'); axes[1].semilogx(f,np.angle(z,deg=True),marker='.' if len(f)==1 else None)
        axes[1].set_ylabel('phase [deg]'); axes[1].set_xlabel('frequency [Hz]')
        fig.suptitle('Synthetic constant RLC: actual ngspice samples')
    else:
        fig, axes = plt.subplots(2,1,figsize=(9,6), layout='constrained')
        t=data['time']; axes[0].plot(t,data['v(bus)']); axes[0].set_ylabel('bus voltage [V]')
        axes[1].plot(t,data['i(vfeed)'],label='source into bus'); axes[1].plot(t,data['i(vload)'],label='load')
        if 'i(vcap)' in data:axes[1].plot(t,data['i(vcap)'],label='into capacitor (signed)')
        axes[1].legend(); axes[1].set_xlabel('time [s]'); axes[1].set_ylabel('current [A]')
        fig.suptitle('Single finite pulse + recovery; not periodic steady state')
    for ax in axes:ax.grid(True,alpha=.25)
    fig.savefig(out/'curve.png', dpi=140)
    plt.close(fig)


def execute(q):
    from .contract import validate_si
    require(set(q)=={'schema_version','input','operation','input_sha256','artifact_dir','ngspice','solver_timeout_seconds','max_points'} and q['schema_version']=='spice.science-request.v1', 'Invalid native request')
    c, op = q['input'], q['operation']
    require(digest(c)==q['input_sha256'], 'Canonical input identity mismatch')
    count = validate_si(c,op)
    require(type(q['solver_timeout_seconds']) is int and 1<=q['solver_timeout_seconds']<=120 and type(q['max_points']) is int and 1<=q['max_points']<=100000 and count<=q['max_points'], 'Native resource budget')
    out=Path(q['artifact_dir'])
    require(out.is_absolute() and out.is_dir() and not (out/'solver').exists(), 'Fresh runtime artifact directory required')
    os.environ['MPLCONFIGDIR']=str(out/'native/.cache/matplotlib')
    env=probe(q['ngspice']); write_json(out/'environment.json',env)
    # No raw-unit interpretation in WSL; only canonical numeric SI is admitted here.
    write_json(out/'input.solver-si.json',c)
    from .model import MLCC
    from .runner import execute as run
    from .netlist import ac, transient
    from .results import ac_result, transient_result, rc_error
    from .readback import verify
    solver=out/'solver'
    if op.startswith('ac_'):
        analysis='ac'; models=[MLCC.from_dict(m) for m in c['models']]
        deck=ac(models,c['points_per_decade'],c['fmin_Hz'],c['fmax_Hz'],c['single_frequency'])
        data=run(deck,solver,'ac',c['fmax_Hz'],['v(port)','i(vtest)'],1 if c['single_frequency'] else 2,
                 q['solver_timeout_seconds'],executable=q['ngspice'],expected_start=c['fmin_Hz'],expected_points=count,max_points=q['max_points'])
        write_json(solver/'input.json', {'models':c['models'],'points':c['points_per_decade'],'fmin_Hz':c['fmin_Hz'],'fmax_Hz':c['fmax_Hz'],'single_frequency':c['single_frequency']})
        m=ac_result(data,models,solver)
        checks=[check('circuit_reference',m['complex_relative_error']<1e-8 and m['current_absolute_error_A']<1e-9,'Independent linear network algebra; errors and RMS convention in solver/metrics.json'),
                check('power_energy',m['power_balance_relative_error']<1e-8 and m['minimum_real_impedance_ohm']>-1e-10,'Port RMS-normalized real power vs series ESR + terminal leakage')]
        summary={'minimum_impedance_ohm':m['sampled_minimum']['magnitude_ohm'],'sampled_minimum_frequency_Hz':m['sampled_minimum']['frequency_Hz'],
                 'minimum_voltage_V':None,'droop_V':None,'overshoot_V':None,'finite_window_cap_RMS_A':None}
    else:
        analysis='tran'; model=MLCC.from_dict(c['model']) if c['model'] else None; cfg=c['circuit']
        required=['v(bus)','i(vfeed)','i(vload)']
        if model:
            required+=['i(vcap)','v(xcap.nl)' if model.esl_H>0 else 'v(xcap.nr)' if model.esr_ohm>0 else 'v(cp)']
        data=run(transient(model,cfg,c['maxstep_s']),solver,'tran',cfg['stop_s'],required,2,q['solver_timeout_seconds'],
                 executable=q['ngspice'],expected_start=0,maxstep=c['maxstep_s'],max_points=q['max_points'])
        write_json(solver/'input.json',c)
        m=transient_result(data,cfg,model,solver)
        if model and model.esr_ohm==0 and model.esl_H==0 and model.leakage_resistance_ohm is None and cfg['line_inductance_H']==0:
            m['RC_closed_form_max_error_V']=rc_error(data,cfg,model.capacitance_F,solver)
            write_json(out/'rc_diagnostic.json',{'maximum_error_V':m['RC_closed_form_max_error_V']})
        checks=[check('circuit_reference',m['KCL_relative_error']<1e-6 and m['initial_voltage_error_V']<1e-7 and m.get('RC_closed_form_max_error_V',0)<2e-5,
                      'Signed KCL, leakage-aware DC operating point; finite-ramp RC closed form only when applicable'),
                check('power_energy',m.get('energy_balance',{}).get('relative_error',0)<.003,'Terminal energy vs ESR/leakage + stored-energy change; whole-source balance independently reopened')]
        summary={'minimum_impedance_ohm':None,'sampled_minimum_frequency_Hz':None,'minimum_voltage_V':m['minimum_voltage_V'],
                 'droop_V':m['droop_V'],'overshoot_V':m['overshoot_V'],'finite_window_cap_RMS_A':m['cap_current_RMS_over_pulse_and_recovery_A']}
    rb=verify(out)
    checks += [check('native_readback',rb['status']=='PASS','Reopened raw/CSV independently; checks, errors and raw hashes in readback.json'),
               {'id':'sampling_sensitivity','status':'not_checked','message':'Single task; explicit qualification harness performs the selected sampling/time refinement matrix'}]
    plot(data,analysis,out)
    results={'analysis':analysis,'samples':m['samples'],'summary':summary,'metrics_artifact':'artifacts/solver/metrics.json',
             'curve_artifact':'artifacts/solver/parsed.csv','readback_artifact':'artifacts/readback.json','plot_artifact':'artifacts/curve.png'}
    write_json(out/'summary.json',results)
    write_json(out/'native_checks.json',checks)
    hashes={p.relative_to(out).as_posix():file_hash(p) for p in out.rglob('*') if p.is_file() and 'native' not in p.relative_to(out).parts}
    return {'schema_version':'spice.science-result.v1','status':'succeeded','input_sha256':digest(c), 'results':results,'checks':checks,'environment':env,'hashes':hashes}
