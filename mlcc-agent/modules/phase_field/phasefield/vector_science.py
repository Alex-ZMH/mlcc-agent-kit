"""Scientific-process-only orchestration of the frozen vector kernel and independent checker."""
from pathlib import Path
import csv
import json
import math
import numpy as np
import pyvista as pv
from .common import ROOT, digest, read_json, write_json, file_hash
from .vector_input import validate_reduced, reduce_si, require
from .vector_views import result_view, mapped_history
from .vector.kernel import VectorPhaseField
from .vector.readback import check as independent_readback
from .science import environment

class BoundedVector(VectorPhaseField):
    def __init__(self, controls, **options):
        self.controls=controls; self.allow_steady=False
        super().__init__(**options)
    def checkpoint(self):
        if not self.allow_steady:
            count=sum(bool(r['accepted']) and not r.get('steady',False) for r in self.logs)
            require(count < self.controls['max_steps'], 'Accepted-step budget reached; last accepted state retained', 'RESOURCE_LIMIT')
        return super().checkpoint()
    def steady(self):
        self.allow_steady=True
        try:return super().steady()
        finally:self.allow_steady=False

def waveform(protocol, dimension):
    if protocol['kind']=='constant':return lambda t:np.asarray(protocol['value'],float)
    if protocol['kind']=='triangle':
        v=np.asarray(protocol['direction'],float);v/=np.linalg.norm(v)
        return lambda t:v*protocol['amplitude']*(4*abs((t/protocol['period'])%1-.5)-1)
    times=np.asarray(protocol['times']);values=np.asarray(protocol['values'])
    return lambda t:values[min(np.searchsorted(times,t,side='right')-1,len(times)-1)]

def physical_files(out, context, dimension):
    si=out/'si';si.mkdir(exist_ok=False);f=context['derived']['factors']
    with np.load(out/'fields.npz',allow_pickle=False) as z:
        arrays={k:z[k].copy() for k in z.files}
    for key,factor in [('coordinates',f['length']),('P',f['polarization']),('P_history',f['polarization']),
                       ('phi',f['potential']),('phi_history',f['potential']),('times',f['time'])]:
        arrays[key]*=factor
        require(np.isfinite(arrays[key]).all(),'Nonfinite physical view','INVALID_SCALES')
    np.savez_compressed(si/'fields_si.npz',**arrays)
    grid=pv.read(out/'fields.vtu');grid.points*=f['length']
    for key in ('P',*['P'+'xyz'[i] for i in range(dimension)]):grid.point_data[key]*=f['polarization']
    grid.point_data['phi']*=f['potential']
    for key,factor in [('E',f['electric_field']),('D_cell_mean',f['polarization']),('rho_bound',f['polarization_gradient'])]:grid.cell_data[key]*=factor
    grid.save(si/'fields_si.vtu')
    write_json(si/'mapping.json',context)
    write_json(si/'history_si.json',mapped_history(read_json(out/'history.json'),context,dimension))
    units={'coordinates':'m','P':'C/m^2','phi':'V','E':'V/m','D_cell_mean':'C/m^2','rho_bound':'C/m^3','times':'s',
           'cells':'dimensionless integer connectivity; not scaled','frame':'dimensionless orthogonal frame; not scaled',
           'mesh_id':'identity of original reduced mesh; physical coordinates are an explicit view',
           'energy':'J/m' if dimension==2 else 'J','wall_excess_energy':'J/m^2'}
    write_json(si/'fields_units.json',units)
    reread=pv.read(si/'fields_si.vtu')
    with np.load(si/'fields_si.npz',allow_pickle=False) as z:
        checks={key:bool(np.array_equal(z[key],value)) for key,value in arrays.items()}
        checks['VTU_P']=bool(np.array_equal(reread.point_data['P'][:,:dimension],z['P']))
        checks['VTU_phi']=bool(np.array_equal(reread.point_data['phi'],z['phi']))
        checks['VTU_coordinates']=bool(np.array_equal(reread.points,z['coordinates']))
    write_json(si/'readback.json',{'passed':all(checks.values()),'checks':checks,'qc_domain':'dimensionless'})
    require(all(checks.values()),'Physical view roundtrip failed','INVALID_SCIENTIFIC_RESULT')

def plots(out, dimension, context=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    path=out/'si' if context else out
    name='fields_si.npz' if context else 'fields.npz'
    with np.load(path/name,allow_pickle=False) as z:
        coords=z['coordinates'];P=z['P'];phi=z['phi']
    # Saved rotated walls need a slice in their own orthogonal coordinate frame.
    frame=np.asarray(read_json(out/'config.json')['frame']); local=coords[:,:dimension]@frame
    mask=np.ones(len(coords),bool)
    if dimension==3:
        plane=local[np.argmin(abs(local[:,2])),2];mask=np.isclose(local[:,2],plane)
    fig,axes=plt.subplots(1,dimension+1,figsize=(4*(dimension+1),3.6))
    for i,ax in enumerate(axes):
        values=P[:,i] if i<dimension else phi
        field='P'+'xyz'[i] if i<dimension else 'phi'
        unit=('C/m²' if i<dimension else 'V') if context else 'dimensionless'
        image=ax.tricontourf(local[mask,0],local[mask,1],values[mask],levels=20)
        fig.colorbar(image,ax=ax,label=field+' ['+unit+']');ax.set_aspect('equal');ax.set_title(field)
        ax.set_xlabel('local x ['+('m' if context else 'nd')+']');ax.set_ylabel('local y ['+('m' if context else 'nd')+']')
    fig.suptitle('2D full field' if dimension==2 else '3D nodal slice in stored local frame; full volume in NPZ/VTU')
    fig.tight_layout();fig.savefig(path/'vector_fields.png',dpi=120);plt.close(fig)
    history=read_json(path/('history_si.json' if context else 'history.json'))
    times=np.array([r['t'] for r in history]);means=np.array([r['mean_P'] for r in history]);E=np.array([r['E_applied'] for r in history])
    fig,axes=plt.subplots(1,2,figsize=(9,3.5))
    for i in range(dimension):
        axes[0].plot(times,means[:,i],label='P'+'xyz'[i]);axes[1].plot(E[:,i],means[:,i],label='component '+'xyz'[i])
    axes[0].set(xlabel='time ['+('s' if context else 'nd')+']',ylabel='mean P ['+('C/m²' if context else 'nd')+']')
    axes[1].set(xlabel='applied E ['+('V/m' if context else 'nd')+']',ylabel='mean P ['+('C/m²' if context else 'nd')+']')
    fig.suptitle('Finite dynamic trajectory; material quasistatic Ec is not inferred',fontsize=10)
    for ax in axes:ax.legend();ax.grid(alpha=.25)
    fig.tight_layout();fig.savefig(path/'vector_history.png',dpi=120);plt.close(fig)

def compute(q, core):
    require(set(q)=={'schema_version','input','input_sha256','artifact_dir','max_cells','threads','operation','task_id','unit_context'},'Invalid vector native request','INVALID_REQUEST')
    p=validate_reduced(q['input']);out=Path(q['artifact_dir']);context=q['unit_context']
    require(q['operation']==p['operation'] and digest(p)==q['input_sha256'] and q['threads']==1,'Native identity/thread mismatch','INVALID_REQUEST')
    if context:
        check,derived=reduce_si(context['canonical_si'])
        require(check==p and derived==context['derived'] and digest(context['original_input'])==context['original_input_sha256'],'Native unit mapping identity mismatch','INVALID_REQUEST')
    env=environment();require(env['ranks']==1 and env['versions']['fenics-dolfinx']=='0.11.0','Reviewed real single-rank environment required','BACKEND_UNAVAILABLE')
    wave=waveform(p['field_protocol'],p['dimension']);initial=p['initial_condition'];controls=p['evolution']
    options={'dimension':p['dimension'],'cells':p['cells'],'parameters':p['parameters'],'kind':initial['kind'],
             'field':wave(0).tolist(),'initial':initial.get('values'),'width':initial.get('width_factor',1.)}
    s=BoundedVector(controls,**options)
    require(s.m.topology.index_map(p['dimension']).size_global<=q['max_cells'],'Actual mesh exceeds host limit','RESOURCE_LIMIT')
    write_json(out/'input.solver-dimensionless.json',p);write_json(out/'environment.json',env)
    try:
        if p['field_protocol']['kind']=='stairs':
            times=p['field_protocol']['times'];values=p['field_protocol']['values']
            for i,t in enumerate(times):
                target=min(controls['end'],times[i+1] if i+1<len(times) else controls['end'])
                if s.t<target:s.advance(target,controls['dt'],field=lambda t,i=i:values[i],max_retries=controls['max_halvings'])
        elif controls['end']>0:s.advance(controls['end'],controls['dt'],field=wave,max_retries=controls['max_halvings'])
        if p['operation']=='vector_steady':s.steady()
        s.save(out)
    except Exception:
        s.save(out)
        raise
    rb=independent_readback(out);write_json(out/'readback.json',rb)
    require(rb['status']=='PASS' and rb['checks'] and all(v is True for v in rb['checks'].values()),'Independent vector field/residual readback failed','INVALID_SCIENTIFIC_RESULT')
    history=read_json(out/'history.json');logs=read_json(out/'nonlinear.json');metrics=read_json(out/'metrics.json')
    protocol=read_json(ROOT/'protocols/vector-protocol.json')
    accepted=[x for x in logs if x['accepted']];rejected=[x for x in logs if not x['accepted']]
    checks={'nonlinear':all(x['reason']>0 and x['residual']<protocol['SNES_absolute_residual'] for x in accepted),
            'rollback':all(x.get('rollback_exact') is True for x in rejected),
            'voltage_bc':max(x['potential_BC_error'] for x in history)<protocol['field_BC_absolute'],
            'history_accounting':len(history)==len(accepted)+1,
            'completed_time':abs(history[-1]['t']-controls['end'])<=1e-12*max(1,controls['end']),
            'independent_readback':rb['status']=='PASS'}
    # Same voltage-work inequality as frozen integrator, using each accepted old-state energy.
    previous=history[0]['enthalpy'];energy_ok=True;cursor=1
    for row in logs:
        if row['accepted']:
            if not row.get('steady'):energy_ok &= row['energy_change_minus_work']<=protocol['fixed_voltage_energy_work_absolute_per_volume']*max(1,abs(previous),s.volume)
            previous=history[cursor]['enthalpy'];cursor+=1
    checks['voltage_work_energy']=bool(energy_ok)
    require(all(checks.values()),'Native trajectory/QC verification failed','INVALID_SCIENTIFIC_RESULT')
    write_json(out/'native_checks.json',checks);write_json(out/'scientific_core.json',core.provenance())
    with (out/'history.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream);writer.writerow(['time_nd']+['mean_P'+'xyz'[i]+'_nd' for i in range(p['dimension'])]+['E'+'xyz'[i]+'_nd' for i in range(p['dimension'])]+['enthalpy_nd'])
        writer.writerows([[r['t'],*r['mean_P'],*r['E_applied'],r['enthalpy']] for r in history])
    if context:physical_files(out,context,p['dimension'])
    warnings=[]
    if p['output']['images']:
        try:
            plots(out,p['dimension'])
            if context:plots(out,p['dimension'],context)
        except Exception as exc:
            warnings.append('Plot export failed; complete native fields retained: '+str(exc));write_json(out/'plot_failure.json',{'error':str(exc)})
    refs=['artifacts/'+f.relative_to(out).as_posix() for f in sorted(out.rglob('*')) if f.is_file() and 'native' not in f.relative_to(out).parts]
    refs=sorted(set(refs+['artifacts/summary.json']))
    result=result_view(p,metrics,history,logs,context,refs);write_json(out/'summary.json',result)
    hashes={ref:file_hash(out/ref.removeprefix('artifacts/')) for ref in refs}
    return {'status':'succeeded','task_id':q['task_id'],'input_sha256':digest(p),
            'unit_mapping_sha256':digest(context) if context else None,'results':result,
            'checks':checks,'hashes':hashes,'warnings':warnings}
