"""Shared stdlib resource advice; never alters or rejects a numerical request."""
import math


def estimate(payload, unit_context=None):
    op=payload['operation']
    if op=='dielectric_tangent':
        from .tangent_input import estimate_resources
    elif op.startswith('vector_'):
        from .vector_input import estimate_resources
    else:
        from .validation import estimate_resources
    budget=estimate_resources(payload)
    if 'dofs' not in budget:
        m=payload['mesh'];budget['dofs']=2*math.prod(m.get(k,0)+1 for k in ('nx','ny','nz'))
    if unit_context:
        budget['history_bytes']*=2
        if op!='dielectric_tangent':budget['work']*=2
    return budget


def mesh_axes(payload):
    return payload.get('cells') or [payload['mesh'][k] for k in ('nx','ny','nz')[:payload['dimension']]]


def mesh_recommendations(payload):
    op=payload['operation'];d=payload['dimension']
    if op=='dielectric_tangent':return {'dofs':3300,'axis_cells':[128]*d}
    if op.startswith('vector_'):return {'dofs':25000,'axis_cells':[25000]*d}
    return {'axis_cells':[48,12,12][:d]}


def planning_report(payload, config, unit_context=None):
    observed=estimate(payload,unit_context);observed['axis_cells']=mesh_axes(payload)
    recommended={k:config['max_'+k] for k in ('cells','work','history_bytes')}
    recommended.update(mesh_recommendations(payload))
    exceeded=[k for k,v in recommended.items() if k!='axis_cells' and observed[k]>v]
    exceeded += [f'axis_cells[{i}]' for i,(n,r) in enumerate(zip(observed['axis_cells'],recommended['axis_cells'])) if n>r]
    return {'enforced':False,'estimates':observed,'recommendations':recommended,'exceeded':exceeded}


def planning_warnings(report):
    warnings=[]
    if report['exceeded']:
        warnings.append('Planning estimates exceed resource recommendations for '+', '.join(report['exceeded'])+'; advisory only, execution allowed without changing the input.')
    if 'dense_stability_matrix_bytes' in report['estimates']:
        warnings.append('Static tangent uses dense stability eigensolves: a single full matrix is estimated at '+str(report['estimates']['dense_stability_matrix_bytes'])+' bytes; multiple matrices and eigensolver workspaces require additional memory. The full stability check remains enabled.')
    return warnings


def actual_report(payload, recommended_cells, cells, dofs):
    from .common import ModuleError
    if type(recommended_cells) is not int or recommended_cells<1:
        raise ModuleError('INVALID_REQUEST','Positive cell-count recommendation required')
    if cells<=0 or dofs<=0:
        raise ModuleError('INVALID_SCIENTIFIC_RESULT','Nonempty mesh and finite-element space required')
    recommended={'cells':recommended_cells,**mesh_recommendations(payload)}
    exceeded=[]
    if cells>recommended_cells:exceeded.append('cells')
    if 'dofs' in recommended and dofs>recommended['dofs']:exceeded.append('dofs')
    axes=mesh_axes(payload)
    exceeded += [f'axis_cells[{i}]' for i,(n,r) in enumerate(zip(axes,recommended['axis_cells'])) if n>r]
    return {'enforced':False,'actual':{'cells':cells,'dofs':dofs,'axis_cells':axes},
            'recommendations':recommended,'exceeded':exceeded}


def actual_warnings(report):
    return (['Actual mesh exceeds recommendations for '+', '.join(report['exceeded'])+'; advisory only, no mesh/DOF count cap was enforced.']
            if report['exceeded'] else [])
