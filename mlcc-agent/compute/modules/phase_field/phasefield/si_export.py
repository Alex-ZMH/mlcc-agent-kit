"""Explicit physical view of native dimensionless data; WSL scientific environment only."""
import csv
from pathlib import Path
import numpy as np
from .common import write_json,read_json,digest
from .scaling import mapped_summary


def export_si(out,data,history,nd,mapping,images):
    f=mapping['derived']['factors'];directory=out/'si';directory.mkdir(exist_ok=False)
    write_json(directory/'mapping.json',mapping)
    write_json(directory/'summary.json',mapped_summary(nd,mapping))
    fields={}
    factors={'coordinates':'length','E_coordinates':'length','P':'polarization','phi':'potential','E':'electric_field','times':'time','P_history':'polarization','phi_history':'potential'}
    for k,v in data.items():fields[k]=v*f[factors[k]] if k in factors else v
    # Native connectivity is invariant; every scientific array has an explicit SI view.
    for k,v in fields.items():
        if not np.all(np.isfinite(v)):raise ValueError('Nonfinite SI mapped array '+k)
    np.savez_compressed(directory/'fields_si.npz',**fields)
    si_history=[{'time_s':h['t']*f['time'],'mean_P_C_per_m2':h['mean_P']*f['polarization'],
                 'electric_enthalpy':h['potential']*f['energy'],'electric_enthalpy_unit':mapping['derived']['energy_unit'],
                 'centerline_unique_wall_m':None if h['wall_x'] is None else h['wall_x']*f['length'],
                 'rate_rms_C_per_m2_s':h['rate_rms']*f['polarization']/f['time']} for h in history]
    write_json(directory/'history_si.json',si_history)
    with (directory/'history_si.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(si_history[0]));writer.writeheader();writer.writerows(si_history)
    units={'coordinates':'m','E_coordinates':'m','P':'C/m^2','phi':'V','E':'V/m','times':'s','P_history':'C/m^2','phi_history':'V','connectivity':'integer indices'}
    write_json(directory/'fields_units.json',{'units':units,'energy_unit':mapping['derived']['energy_unit'],'source':'../fields.npz','mapping':'mapping.json','slice_images_are_not_full_volume':True,'qc_domain':'dimensionless'})
    with np.load(directory/'fields_si.npz') as saved:
        for k in fields:np.testing.assert_array_equal(saved[k],fields[k])
    write_json(directory/'readback.json',{'passed':True,'all_SI_arrays_read_back':True,'mapping_sha256':digest(mapping),'native_QC_domain':'dimensionless','SI_residual_tolerance':'not_checked'})
    warnings=[]
    if images:
        try:plot_si(directory,data,fields,history,nd['dimension'],f,mapping['derived']['energy_unit'])
        except Exception as e:
            warnings.append('SI plot failed; native solve/mapped arrays retained: '+str(e));write_json(directory/'plot_failure.json',{'message':str(e)})
    return warnings


def plot_si(directory,nd,data,history,dimension,f,energy_unit):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    # Select slice in original coordinate scale to avoid metre-scale atol merging layers.
    def selection(key):
        x=nd[key];mask=np.ones(len(x),dtype=bool);label='2D full domain'
        if dimension==3:
            plane=float(x[np.argmin(abs(x[:,2])),2]);mask=np.isclose(x[:,2],plane)
            label=f'3D layer z={plane*f["length"]:.6g} m (not full volume)'
        return mask,label
    for key,coord,unit in [('P','coordinates','C/m^2'),('phi','coordinates','V'),('E','E_coordinates','V/m')]:
        mask,label=selection(coord);x=data[coord][mask];v=data[key][mask]
        if key=='E':v=np.linalg.norm(v,axis=1)
        fig,ax=plt.subplots(figsize=(8,3));im=ax.scatter(x[:,0],x[:,1],c=v,s=15)
        fig.colorbar(im,ax=ax,label=key+' ['+unit+']');ax.set(title=label,xlabel='x [m]',ylabel='y [m]');ax.set_aspect('equal');fig.tight_layout();fig.savefig(directory/(key+'_si.png'),dpi=130);plt.close(fig)
    fig,axes=plt.subplots(2,1,figsize=(7,5),sharex=True)
    times=[h['t']*f['time'] for h in history]
    axes[0].plot(times,[h['mean_P']*f['polarization'] for h in history],'.-');axes[0].set_ylabel('mean P [C/m^2]')
    axes[1].plot(times,[h['potential']*f['energy'] for h in history],'.-');axes[1].set(xlabel='time [s]',ylabel='electric enthalpy ['+energy_unit+']');fig.tight_layout();fig.savefig(directory/'history_si.png',dpi=130);plt.close(fig)
