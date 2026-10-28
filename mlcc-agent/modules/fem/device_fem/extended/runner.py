"""Single-case WSL orchestration of the reviewed experiment kernels."""
from pathlib import Path
import numpy as np
import ufl
from dolfinx import mesh
from . import thermal_core as core
from ..validation import body_height

ASSUMPTIONS=[
    '2D invariant cross section with explicit extruded depth; no 3D packaging or out-of-plane heat transfer.',
    'Linear passive synthetic/user-declared coefficients; material and actual device applicability not_checked.',
    'Sequential one-way steady heat; no temperature feedback, transient, thermomechanics or magnetic material response.',
    'Raw P1 gradient flux is retained separately from discrete reaction balance; mesh convergence is task-specific.',
]


def thermal_report(report,enabled):
    mapping={'maximum_temperature_K':'Tmax_K','mean_temperature_K':'Tavg_K','maximum_rise_K':'dTmax_K','mean_rise_K':'dTavg_K',
             'hotspot_thermal_resistance_K_per_W':'Rth_hotspot_K_W','mean_thermal_resistance_K_per_W':'Rth_average_K_W',
             'source_power_W':'source_power_W','outward_power_W':'outward_power_W','raw_outward_power_W':'raw_gradient_out_W'}
    return {'enabled':enabled,**{key:report[value] if enabled else None for key,value in mapping.items()}}


def heat(payload,m,labels,q,tags,out):
    t=payload['thermal']; depth=payload['out_of_plane_thickness_m']
    k=core.scalar(m,np.where(labels==10,t['ceramic_k_W_per_m_K'],t['Ni_k_W_per_m_K']),'k_W_mK')
    bc={'kind':t['boundary_kind'],'groups':[31],'h_W_m2K':t['convection_h_W_per_m2_K']}
    T,theta,flux,r=core.thermal(m,k,q,tags,bc,depth,t['ambient_K'])
    output=core.export(out/'thermal',m,[T,theta],[q,k,flux],labels)
    return r,output


def run(payload,out,max_cells):
    from mpi4py import MPI
    from petsc4py import PETSc
    if MPI.COMM_WORLD.size!=1 or np.dtype(PETSc.ScalarType).kind!='f':raise ValueError('Extended kernels require serial real PETSc')
    out=Path(out); native=out/'solution'; native.mkdir(exist_ok=False)
    analysis=payload['analysis']; h=payload['mesh']['target_size_m']; depth=payload['out_of_plane_thickness_m']
    diagnostics={'analysis':analysis,'tolerance_basis':'Reviewed experiment code thresholds are numerical regression checks, not product tolerances; see EXTENDED_SOURCES.json.', 'checks':{}}
    e={'loss_total_W':0.,'loss_ceramic_W':0.,'loss_metal_W':0.,'electric_field_max_V_per_m':0.,
       'capacitance_F':None,'electric_energy_J':None,'magnetic_energy_J':None,'magnetic_inductance_H':None,'admittance_S':None,'impedance_ohm':None}
    t=None; outputs={}; tr=None
    if analysis in ('electrothermal','ac_eqs'):
        layered=payload['dielectric_layout']=='half_height_layered'
        parent,labels,child,mapping,et,tt=core.device_mesh(payload,h,native,split_y=body_height(payload)/2 if layered else None,max_cells=max_cells)
        if analysis=='electrothermal':
            mat=payload['materials']['ceramic_lower']; p=payload['potentials']; loss=payload['loss_model']
            spec={'model':'ac' if loss=='ac_prescribed' else loss,'sigma_S_m':mat['sigma_S_m'],'frequency_Hz':payload['frequency_Hz'],'tan_delta':mat['tan_delta'],'voltage_convention':payload['voltage_convention']}
            phi,E,q,r=core.electric(child,et,p['terminal_a_real_V'],p['terminal_b_real_V'],mat['eps_r'],spec,depth)
            outputs['electrical']=core.export(native/'electrical',child,[phi],[E,q],np.full(core.ncells(child),10))
            e.update(loss_total_W=r['loss_power_W'],loss_ceramic_W=r['loss_power_W'],electric_field_max_V_per_m=r['Emax_V_m'],
                     capacitance_F=2*r['electrostatic_energy_J']/r['effective_voltage_difference_rms_or_dc_V']**2,electric_energy_J=r['electrostatic_energy_J'])
            diagnostics['checks']['power_balance']=r['terminal_power_relative_error']<1e-9
            diagnostics['checks']['linear_solver']=r['solver']['reason']>0 and r['solver']['relative_residual']<1e-8
            diagnostics['electrical']=r
        else:
            from .ac_solver import solve,save_fields
            p=payload['potentials']; regions=np.full(core.ncells(child),101,dtype=np.int32)
            if layered:
                centers=mesh.compute_midpoints(child,2,np.arange(core.ncells(child),dtype=np.int32)); regions=np.where(centers[:,1]<body_height(payload)/2,101,102).astype(np.int32)
                for c in range(core.ncells(child)):
                    y=child.geometry.x[child.geometry.dofmap[c],1]
                    if y.min()<body_height(payload)/2-1e-14 and y.max()>body_height(payload)/2+1e-14:raise ValueError('Dielectric interface crosses a cell')
            materials={str(tag):{k:payload['materials'][name][k] for k in ('eps_r','sigma_S_m','tan_delta')} for tag,name in ((101,'ceramic_lower'),(102,'ceramic_upper')) if layered or tag==101}
            fields,r=solve(child,et,regions,materials,payload['frequency_Hz'],[p['terminal_a_real_V'],p['terminal_a_imag_V']],[p['terminal_b_real_V'],p['terminal_b_imag_V']],depth,convention=payload['voltage_convention'])
            q=fields['q']; outputs['electrical']=save_fields(native,child,fields,regions)
            e.update(loss_total_W=r['volume_power_W'],loss_ceramic_W=r['volume_power_W'],capacitance_F=r['Cp_parallel_F'],admittance_S=r['Y_S'],impedance_ohm=r['Z_ohm'],
                     electric_field_max_V_per_m=float(np.max(np.sqrt(np.sum(core.cell_values_vector(fields['Er'])**2+core.cell_values_vector(fields['Ei'])**2,axis=1)))))
            diagnostics['checks']['power_balance']=r['complex_work_relative_error']<1e-9 and r['current_balance_relative']<1e-9 and r['q_dot_identity_relative']<1e-12
            diagnostics['checks']['linear_solver']=r['solver']['reason']>0 and r['solver']['relative_free_residual']<1e-9
            diagnostics['electrical']=r
        cells=core.ncells(parent)
        if payload['thermal']['enabled']:
            received,tr=core.transfer(q,parent,mapping,labels)
            t,outputs['thermal']=heat(payload,parent,labels,received,tt,native)
            np.savez(native/'cell_transfer.npz',child_to_parent=mapping,parent_material=labels,q_child=core.cell_values(q),q_parent=core.cell_values(received))
            diagnostics['checks']['source_transfer']=tr['relative_error']<1e-12 and tr['Ni_source_max_W_m3']==0
    else:
        from .em_geometry import build,solid
        from .em_solver import solve,save
        port=payload['port']; m,ft,regions,geometry=build(payload,h,native,bus=port['bus_width_m'],feed=port['feed_air_m'],bottom=port['bottom_air_m'],max_cells=max_cells)
        materials={str(tag):{k:payload['materials'][name][k] for k in ('eps_r','sigma_S_m','tan_delta')} for tag,name in ((10,'ceramic'),(20,'Ni'),(30,'air'))}
        current=complex(payload['current']['real_A_rms'],payload['current']['imag_A_rms'])
        fields,r=solve(m,ft,regions,materials,payload['frequency_Hz'],depth,current,lifting_bounds=(0.,geometry['body_height_m']))
        outputs['electrical']=save(native,m,fields,regions); cells=core.ncells(m)
        e.update(loss_total_W=r['volume_loss_W'],loss_ceramic_W=r['regions']['10']['total_W'],loss_metal_W=r['regions']['20']['total_W'],electric_energy_J=r['electric_energy_J'],magnetic_energy_J=r['magnetic_energy_J'],magnetic_inductance_H=r['L_magnetic_energy_H'],capacitance_F=r['C_electric_energy_F'],impedance_ohm=r['Z_ohm'],admittance_S=[float((1/complex(*r['Z_ohm'])).real),float((1/complex(*r['Z_ohm'])).imag)],electric_field_max_V_per_m=float(np.max(np.sqrt(np.sum(core.cell_values_vector(fields['Er'])**2+core.cell_values_vector(fields['Ei'])**2,axis=1)))))
        diagnostics.update(electrical=r,geometry=geometry)
        diagnostics['checks'].update(power_balance=r['complex_power_relative_error']<1e-7 and r['active_power_relative_error']<1e-5,linear_solver=r['solver']['reason']>0 and r['weak_Maxwell_relative_residual']<1e-7)
        if payload['thermal']['enabled']:
            s,mapping,labels,tt=solid(m,regions,geometry['L_m'],geometry['bus_width_m'])
            qparent=core.cell_values(fields['q']); received=core.scalar(s,qparent[mapping],'q_W_m3')
            parent_power=depth*core.integral(fields['q']*ufl.dx); child_power=depth*core.integral(received*ufl.dx)
            tr={'relative_error':abs(child_power-parent_power)/max(parent_power,1e-30),'input_W':parent_power,'received_W':child_power}
            diagnostics['checks']['source_transfer']=tr['relative_error']<1e-12
            t,outputs['thermal']=heat(payload,s,labels,received,tt,native)
            np.savez(native/'cell_transfer.npz',solid_to_em=mapping,em_regions=regions,q_parent=qparent,q_solid=core.cell_values(received))
        ASSUMPTIONS_EM=['Closed guided Ex/Ey/Hz port with PEC rails, specified feed/reference plane and magnetic wall; no open radiation.',
                        'mu_r=1 fixed; no magnetic hysteresis or frequency-dependent permeability.',
                        'Port R and magnetic-energy L are model quantities, not calibrated commercial ESR/ESL/SRF.']
    diagnostics['checks']['mesh_semantics']=True
    diagnostics['checks']['field_finiteness']=all(o['VTU_readback']=='PASS' for o in outputs.values())
    if t is not None:
        diagnostics['checks']['linear_solver'] &= t['solver']['reason']>0
        if analysis=='electrothermal':diagnostics['checks']['linear_solver'] &= max(t['solver']['relative_residual'],t['weak_residual_relative'])<1e-8
        diagnostics['checks']['thermal_balance']=t['balance_absolute_W']<1e-10 if e['loss_total_W']==0 else t['balance_relative']<(1e-8 if analysis=='electromagnetic' else 1e-9)
    diagnostics.update(thermal=t,source_transfer=tr,outputs=outputs,mesh_cells=cells,solver_environment={'mpi_ranks':MPI.COMM_WORLD.size,'MPI_library':MPI.Get_library_version(),'PETSc_scalar':str(np.dtype(PETSc.ScalarType))})
    fields=['artifacts/solution/'+p.name for p in native.glob('*.vtu')]
    assumptions=ASSUMPTIONS+(ASSUMPTIONS_EM if analysis=='electromagnetic' else ['Ni is thermally conductive but electrically ideal in this operation; Ni heat=0.'])
    if analysis=='electrothermal':assumptions+=['Prescribed AC uses a real electrostatic field and dielectric loss only; reported loss current is not a full complex admittance.']
    result={'schema_version':'fem.device-result.v1','analysis':analysis,'frequency_Hz':payload['frequency_Hz'],'out_of_plane_thickness_m':depth,'mesh_cells':cells,
            'phasor_convention':'dc' if analysis=='electrothermal' and payload['voltage_convention']=='dc' else 'RMS exp(+j omega t)',
            'electrical':e,'thermal':thermal_report(t,t is not None),'mesh_artifact':'artifacts/solution/mesh.msh',
            'diagnostics_artifact':'artifacts/diagnostics.json','field_artifacts':fields,'assumptions':assumptions}
    core.write(out/'diagnostics.json',diagnostics)
    warnings=[]
    if payload['outputs']['field_images']:
        try:images(native)
        except Exception as exc:warnings.append('Optional field images failed: '+str(exc))
    # Scientific NumPy scalars must not leak across the stdlib JSON boundary.
    import json
    def primitive(value):
        if isinstance(value,np.generic):return value.item()
        raise TypeError(type(value).__name__)
    def plain(value):return json.loads(json.dumps(value,allow_nan=False,default=primitive))
    return plain(result),plain(diagnostics),warnings


def images(out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.tri as tri
    import pyvista as pv
    for file in out.glob('*.vtu'):
        grid=pv.read(file); cells=grid.cells.reshape(-1,4)[:,1:]; triang=tri.Triangulation(grid.points[:,0],grid.points[:,1],cells)
        choices=['temperature_rise_K','potential_V','phi_real_V_rms','H_amplitude_A_m']
        name=next((n for n in choices if n in grid.point_data),None)
        if name is None:continue
        fig,ax=plt.subplots(figsize=(10,3)); im=ax.tripcolor(triang,np.asarray(grid.point_data[name]),shading='gouraud')
        fig.colorbar(im,ax=ax,label=name); ax.set(xlabel='x [m]',ylabel='y [m]',title=name+' (vertical scale exaggerated)')
        fig.tight_layout();fig.savefig(out/(name+'.png'),dpi=130);plt.close(fig)
