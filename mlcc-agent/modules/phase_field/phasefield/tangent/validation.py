"""Independent nonlinear FD re-solves and algebraic single-domain reference."""
from pathlib import Path
import json,hashlib
import numpy as np
from .kernel import write
PROTOCOL=json.loads((Path(__file__).parents[2]/'protocols/tangent-protocol.json').read_text())

def algebra_hessian(P,p):
    # Independent direct second derivatives, no UFL or solver Jacobian.
    D=len(P);H=np.zeros((D,D))
    for i in range(D):
        H[i,i]=2*p.a+12*p.b*P[i]**2+2*p.c*sum(P[k]**2 for k in range(D) if k!=i)
        for j in range(D):
            if i!=j:H[i,j]=4*p.c*P[i]*P[j]
    return H

def fd_validate(s,center,result,amplitudes=None):
    """All + and - solves reload the SAME on-disk equilibrium. No AD predictor."""
    center=Path(center);disk=np.load(center/'fields.npz');state={'u':disk['mixed_state'].copy(),'field':disk['bias'].copy(),'path':json.loads((center/'loading_path.json').read_text()),'mesh_id':str(disk['mesh_id'])};sha=hashlib.sha256(state['u'].tobytes()).hexdigest();D=s.D;AD=np.array(result['total_tangent_permittivity']);rows=[]
    before=s.sensitivities.copy() if hasattr(s,'sensitivities') else None
    for amp in amplitudes or PROTOCOL['FD_wall_amplitudes' if s.base.wallkind else 'FD_amplitudes']:
        plus=np.zeros((D,D));minus=plus.copy();meanEplus=plus.copy();meanEminus=plus.copy();branch=[]
        for j in range(D):
            for sign in [-1,1]:
                s.restore(state);restored=hashlib.sha256(s.u.x.array.tobytes()).hexdigest()==sha
                target=state['field']+sign*amp*np.eye(D)[j];s.solve(target,append=False);Q=s.means(s.displacement);E=s.means(s.E)
                if sign>0:plus[:,j]=Q;meanEplus[:,j]=E
                else:minus[:,j]=Q;meanEminus[:,j]=E
                d=s.u.x.array-state['u'];rel=float(np.sqrt(max(d@(s.mass.getValues(range(len(d)),range(len(d)))@d),0)/s.volume));P0=np.column_stack([state['u'][m] for m in s.maps[:D]]);P1=np.column_stack([s.u.x.array[m] for m in s.maps[:D]]);maxP=float(np.max(np.linalg.norm(P1-P0,axis=1)));out=center.parent/(center.name+f'_FD_h{amp:g}_j{j}_{"plus" if sign>0 else "minus"}');s.save(out)
                branch.append({'direction':j,'sign':sign,'same_saved_center_reloaded':restored,'center_sha256':sha,'initial_predictor':'exact stored center; no sensitivity extrapolation','state_L2_change':rel,'maximum_nodal_P_change':maxP,'no_branch_jump':bool(maxP<.15),'mean_D':Q.tolist(),'mean_E':E.tolist(),'mean_P':s.means(s.P).tolist(),'residual':s.residual(),'folder':out.name})
        B=(meanEplus-meanEminus)/(2*amp);raw=(plus-minus)/(2*amp);FD=raw@np.linalg.inv(B);error=FD-AD;scaled=np.abs(error)/np.maximum(np.abs(AD),PROTOCOL['FD_component_relative_floor']);relative=np.linalg.norm(error)/max(np.linalg.norm(AD),1.)
        rows.append({'amplitude':amp,'tensor':FD.tolist(),'raw_control_D_response':raw.tolist(),'actual_mean_E_response':B.tolist(),'mean_E_response_condition':float(np.linalg.cond(B)),'absolute_error_components':abs(error).tolist(),'scaled_relative_error_components':scaled.tolist(),'relative_tensor_error':float(relative),'branch_checks':branch,'status':'PASS' if relative<PROTOCOL['FD_tensor_relative_error'] and np.max(abs(error))<PROTOCOL['FD_component_absolute_error'] and np.max(scaled)<PROTOCOL['FD_component_scaled_relative_error'] and all(x['same_saved_center_reloaded'] and x['no_branch_jump'] for x in branch) else 'FAIL'})
    s.restore(state)
    if before is not None:assert np.array_equal(s.sensitivities,before)
    order=[float(np.log(rows[k]['relative_tensor_error']/rows[k+1]['relative_tensor_error'])/np.log(rows[k]['amplitude']/rows[k+1]['amplitude'])) for k in range(len(rows)-1)]
    result={'status':'PASS' if all(r['status']=='PASS' for r in rows) else 'FAIL','rows':rows,'error_orders':order,'method':'independent central finite differences of actual nonlinear static solves, validation only','same_saved_branch_center':sha,'center_restored_exact':bool(np.array_equal(s.u.x.array,state['u']) and np.array_equal(s.field,state['field']))};write(center/'fd_validation.json',result);return result

def validate_case(s,out,fd=True,analytical=False):
    out=Path(out);r=s.tangent();sens=s.sensitivities.copy();frozen=s.tangent(frozen=True);frozen_s=s.sensitivities.copy();s.sensitivities=sens;r['frozen_polarization_tensor']=frozen['total_tangent_permittivity'];r['frozen_sensitivity_residuals']=frozen['ad_sensitivity_residuals'];r['frozen_polarization_contribution']=frozen['polarization_tangent_contribution'];A=np.array(r['total_tangent_permittivity']);B=np.array(r['background_permittivity']);P=np.array(r['polarization_tangent_contribution']);checks={
        'static_equilibrium':r['equilibrium_residual']<PROTOCOL['equilibrium_free_residual'],
        'linear_residuals':max(x['linear_relative_residual'] for x in r['ad_sensitivity_residuals'])<PROTOCOL['linear_relative_residual'],
        'mean_field':np.max(abs(np.array(r['actual_mean_field'])-s.field))<PROTOCOL['mean_field_absolute_error'],
        'mean_field_derivative':np.max(abs(np.array(r['actual_mean_field_response'])-np.eye(s.D)))<PROTOCOL['mean_field_absolute_error'],
        'decomposition':np.max(abs(A-B-P))<PROTOCOL['decomposition_absolute_error'],
        'background':np.max(abs(B-np.eye(s.D)*s.p.epsilon))<PROTOCOL['decomposition_absolute_error'],
        'frozen':np.max(abs(np.array(frozen['total_tangent_permittivity'])-np.eye(s.D)*s.p.epsilon))<PROTOCOL['analytic_tensor_relative_error'] and np.max(abs(np.array(frozen['polarization_tangent_contribution'])))<1e-10,
        'reciprocity':np.linalg.norm(A-A.T)/max(np.linalg.norm(A),1.)<PROTOCOL['reciprocity_relative_error'],
        'stable_reduced_energy':r['stability_diagnostics']['status']=='stable'}
    if analytical:
        Pnodal=np.column_stack([s.u.x.array[m] for m in s.maps[:s.D]]);uniform=float(np.max(np.ptp(Pnodal,axis=0)));H=algebra_hessian(np.array(r['mean_polarization']),s.p);ref=np.eye(s.D)*s.p.epsilon+np.linalg.inv(H);err=float(np.linalg.norm(A-ref)/max(np.linalg.norm(ref),1.));r['analytical_validation']={'Hessian':H.tolist(),'inverse_Hessian_polarization':np.linalg.inv(H).tolist(),'total_tensor':ref.tolist(),'relative_error':err,'absolute_components':abs(A-ref).tolist(),'nodal_nonuniformity':uniform};checks['analytical']=err<PROTOCOL['analytic_tensor_relative_error'] and uniform<1e-9
    s.save(out,r,sens);np.savez_compressed(out/'frozen_sensitivities.npz',sensitivities=frozen_s)
    if fd:r['fd_validation']=fd_validate(s,out,r);checks['FD']=r['fd_validation']['status']=='PASS'
    r['checks']=checks;r['validation_status']='PASS' if all(checks.values()) else 'FAIL';write(out/'tensor.json',r);print(out.name,r['validation_status'],'min_lambda',r['stability_diagnostics']['minimum_reduced_energy_eigenvalue'],flush=True);return r
