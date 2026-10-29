"""FEniCSx-only implementation. Imported only by the native scientific entry.

Weak form, ideal-electrode geometry, charge sign and energy method extracted
from the reviewed source; see SOURCES.json. No old service/runtime/provider.
"""
from pathlib import Path
from time import perf_counter
import math

from . import EPSILON_0, MODEL
from .common import ModuleError, write_json
from .geometry import BOUNDARIES, build_mlcc, build_plate_benchmark
from .regions import audit_regions

OPTIONS = {'ksp_type': 'preonly', 'pc_type': 'lu', 'ksp_error_if_not_converged': True}


def run(payload, output, max_cells, *, benchmark=False):
    from scientific_core.fenicsx import assemble_local
    import gmsh
    import numpy as np
    import pyvista as pv
    import ufl
    from dolfinx import fem, mesh, plot
    from dolfinx.io import gmsh as gmshio
    from dolfinx.fem.petsc import LinearProblem
    from mpi4py import MPI
    from petsc4py import PETSc

    if MPI.COMM_WORLD.size != 1 or np.dtype(PETSc.ScalarType).kind == 'c':
        raise ModuleError('BACKEND_UNSUPPORTED', 'This release requires one MPI rank and real PETSc scalars')
    start = perf_counter()
    output = Path(output)
    for folder in ('mesh', 'fields'):
        (output/folder).mkdir(exist_ok=False)
    initialized = False
    try:
        gmsh.initialize(readConfigFiles=False)
        initialized = True
        gmsh.option.setNumber('General.Terminal', 1)
        gmsh.option.setNumber('General.NumThreads', 1)
        gmsh.model.add('fea_electrostatics_2d')
        geometry = (build_plate_benchmark if benchmark else build_mlcc)(gmsh, payload)
        h = payload['mesh']['target_size_m']
        gmsh.option.setNumber('Mesh.MeshSizeMin', h)
        gmsh.option.setNumber('Mesh.MeshSizeMax', h)
        gmsh.model.mesh.generate(2)
        element_types, tags, _ = gmsh.model.mesh.getElements(2)
        count = sum(map(len, tags))
        if not 0 < count <= max_cells or set(element_types.tolist()) != {2}:
            raise ModuleError('RESOURCE_OR_MESH_LIMIT', f'Expected 1..{max_cells} first-order triangles; got {count}')
        gmsh.write(str(output/'mesh/mesh.msh'))
        data = gmshio.model_to_mesh(gmsh.model, MPI.COMM_WORLD, rank=0, gdim=2)
    finally:
        if initialized:
            gmsh.finalize()
    msh, cell_tags, facet_tags = data.mesh, data.cell_tags, data.facet_tags
    if cell_tags is None or facet_tags is None:
        raise ModuleError('MESH_INVALID', 'Missing cell or facet tags')
    if set(data.physical_groups) != {'CERAMIC', *BOUNDARIES}:
        raise ModuleError('MESH_INVALID', 'Unexpected physical identities')
    for name, dim in [('CERAMIC',2), *[(name,1) for name in BOUNDARIES]]:
        if data.physical_groups[name].dim != dim:
            raise ModuleError('MESH_INVALID', 'Wrong physical-group dimension')
    ncells = msh.topology.index_map(2).size_global
    if len(cell_tags.find(data.physical_groups['CERAMIC'].tag)) != ncells:
        raise ModuleError('MESH_INVALID', 'Ceramic cell coverage is incomplete')
    msh.topology.create_connectivity(1, 2)
    facets = {name: set(facet_tags.find(data.physical_groups[name].tag).tolist()) for name in BOUNDARIES}
    audit = audit_regions(set(mesh.exterior_facet_indices(msh.topology).tolist()), facets)
    write_json(output/'mesh/semantic_regions.json', audit)
    if not audit['valid']:
        raise ModuleError('MESH_INVALID', '; '.join(audit['errors']))

    space = fem.functionspace(msh, ('Lagrange', 1))
    bcs = []
    for name, voltage in (('ELECTRODE_A',payload['potentials']['terminal_a_V']),
                          ('ELECTRODE_B',payload['potentials']['terminal_b_V'])):
        dofs = fem.locate_dofs_topological(space, 1, facet_tags.find(data.physical_groups[name].tag))
        if not dofs.size:
            raise ModuleError('MESH_INVALID', 'Empty Dirichlet DOFs: ' + name)
        bcs.append(fem.dirichletbc(PETSc.ScalarType(voltage), dofs, space))
    eps = fem.Constant(msh, PETSc.ScalarType(EPSILON_0*payload['material']['relative_permittivity']))
    trial, test = ufl.TrialFunction(space), ufl.TestFunction(space)
    a = ufl.inner(eps*ufl.grad(trial), ufl.grad(test))*ufl.dx
    rhs = fem.Constant(msh, PETSc.ScalarType(0))*test*ufl.dx
    problem = LinearProblem(a, rhs, bcs=bcs, petsc_options_prefix='mlcc_fea_', petsc_options=OPTIONS)
    solve_start = perf_counter()
    potential = problem.solve()
    solve_seconds = perf_counter()-solve_start
    reason = int(problem.solver.getConvergedReason())
    if reason <= 0:
        raise ModuleError('SOLVER_FAILED', f'PETSc convergence reason={reason}')
    potential.x.scatter_forward()
    residual = problem.b.duplicate()
    try:
        problem.A.mult(potential.x.petsc_vec, residual)
        residual.axpy(-1.0, problem.b)
        residual_norm = float(residual.norm())
        rhs_norm = float(problem.b.norm())
    finally:
        residual.destroy()
    if not math.isfinite(residual_norm):
        raise ModuleError('SOLVER_FAILED', 'Non-finite assembled residual')
    field = -ufl.grad(potential)
    displacement = eps*field
    ds = ufl.Measure('ds', domain=msh, subdomain_data=facet_tags)
    normal = ufl.FacetNormal(msh)
    def assemble(expr):
        return float(assemble_local(expr).real)
    t = payload['out_of_plane_thickness_m']
    charges_per_depth = {n: -assemble(ufl.dot(displacement,normal)*ds(data.physical_groups[n].tag)) for n in BOUNDARIES[:2]}
    charges = {n:q*t for n,q in charges_per_depth.items()}
    outer = t*assemble(ufl.dot(displacement,normal)*ds(data.physical_groups['OUTER_INSULATION'].tag))
    energy_per_depth = 0.5*assemble(ufl.dot(field, displacement)*ufl.dx)
    energy = t*energy_per_depth
    dv = abs(payload['potentials']['terminal_a_V']-payload['potentials']['terminal_b_V'])
    cap = 2*energy/dv**2
    cap_flux = abs(charges['ELECTRODE_A'])/dv
    if not energy > 0 or not math.isfinite(energy) or not math.isfinite(cap) or cap <= 0:
        raise ModuleError('INVALID_SCIENTIFIC_RESULT', 'Nonpositive/non-finite energy or capacitance')

    cells, types, points = plot.vtk_mesh(space)
    grid = pv.UnstructuredGrid(cells, types, points)
    grid.point_data['electric_potential'] = potential.x.array.real.copy()
    vector_space = fem.functionspace(msh, ('DG', 0, (2,)))
    e_function = fem.Function(vector_space)
    e_function.interpolate(fem.Expression(field, vector_space.element.interpolation_points))
    vectors = np.asarray(e_function.x.array.real).reshape(-1, 2)
    if vectors.shape != (grid.n_cells, 2):
        raise ModuleError('FIELD_EXPORT_FAILED', 'E vector order/size differs from output mesh')
    grid.cell_data['electric_field'] = np.column_stack((vectors, np.zeros(len(vectors))))
    grid.cell_data['electric_field_magnitude'] = np.linalg.norm(vectors,axis=1)
    grid.cell_data['region_id'] = np.full(grid.n_cells, data.physical_groups['CERAMIC'].tag)
    if not all(np.isfinite(v).all() for v in (points,vectors,grid.point_data['electric_potential'])):
        raise ModuleError('FIELD_EXPORT_FAILED', 'Non-finite field/mesh data')
    triangles = grid.cells.reshape(-1,4)[:,1:]
    xyz = np.asarray(grid.points)[triangles,:2]
    edge1, edge2 = xyz[:,1]-xyz[:,0], xyz[:,2]-xyz[:,0]
    area = np.abs(edge1[:,0]*edge2[:,1]-edge1[:,1]*edge2[:,0])/2
    lengths2 = np.sum(edge1**2,axis=1)+np.sum(edge2**2,axis=1)+np.sum((xyz[:,2]-xyz[:,1])**2,axis=1)
    if np.any(area <= 0) or not np.isfinite(area).all():
        raise ModuleError('MESH_INVALID', 'Degenerate triangle')
    shape = 4*np.sqrt(3)*area/lengths2
    mesh_report = {'cells':int(ncells), 'physical_groups': {n:{'tag':g.tag,'dimension':g.dim} for n,g in data.physical_groups.items()},
                   'geometry':geometry, 'semantic_audit':audit, 'target_size_m':h,
                   'minimum_triangle_area_m2':float(area.min()), 'maximum_triangle_area_m2':float(area.max()),
                   'minimum_normalized_triangle_shape':float(shape.min()),
                   'shape_acceptance':'not_checked; no approved shape threshold',
                   'element_degree':1, 'mpi_ranks':1}
    write_json(output/'mesh/mesh_report.json',mesh_report)
    grid.save(output/'fields/fields.vtu')
    # Re-read the exported file; an in-memory object is not export evidence.
    saved = pv.read(output/'fields/fields.vtu')
    if saved.n_cells != ncells or not np.array_equal(saved.cell_data['electric_field'],grid.cell_data['electric_field']):
        raise ModuleError('FIELD_EXPORT_FAILED', 'VTU round-trip differs')
    write_json(output/'fields/manifest.json',{
        'spatial_dimension':2,'coordinates':'x,y in m; z=0 padding',
        'electric_potential':{'association':'point','unit':'V'},
        'electric_field':{'association':'cell','unit':'V/m','components':['x','y','z_padding_zero']},
        'electric_field_magnitude':{'association':'cell','unit':'V/m'},
        'region_id':{'association':'cell','meaning':'CERAMIC physical tag'},
        'cells':int(ncells),'points':int(saved.n_points)})
    balance = abs(sum(charges.values()))/max(*(abs(q) for q in charges.values()),1e-30)
    results = {'schema_version':'fea.electrostatics-output.v1','model':MODEL,
        'out_of_plane_thickness_m':t,'body_height_m':geometry['body_height_m'],
        'mesh_cells':int(ncells),'dof_count':int(space.dofmap.index_map.size_global),
        'potential_min_V':float(potential.x.array.real.min()),'potential_max_V':float(potential.x.array.real.max()),
        'electric_field_max_V_per_m':float(grid.cell_data['electric_field_magnitude'].max()),
        'charge_total_C':charges,'charge_per_unit_depth_C_per_m':charges_per_depth,
        'energy_total_J':energy,'energy_per_unit_depth_J_per_m':energy_per_depth,
        'capacitance_energy_total_F':cap,'capacitance_energy_per_unit_depth_F_per_m':cap/t,
        'capacitance_raw_flux_total_F':cap_flux,'charge_balance_relative':balance,
        'capacitance_methods_relative':abs(cap_flux-cap)/cap,'outer_displacement_flux_total_C':outer,
        'field_artifact':'artifacts/fields/fields.vtu','mesh_artifact':'artifacts/mesh/mesh.msh',
        'diagnostics_artifact':'artifacts/diagnostics.json',
        'assumptions':['2D invariant cross section, explicit extruded depth; no finite-width edge correction',
            'Single linear isotropic lossless dielectric; no external air domain',
            'Ideal equipotential electrodes removed from dielectric; no metal volume mesh',
            'Sharp-tip Emax is diagnostic, not a breakdown/safety criterion']}
    if benchmark:
        results['assumptions'].append('Harness parallel plate geometry; not an MLCC device run')
    diagnostics = {'solver':{'converged_reason':reason,'options':OPTIONS,'solve_seconds':solve_seconds,
                   'assembled_residual_norm':residual_norm,'assembled_rhs_norm':rhs_norm},
                   'mesh':mesh_report,'outer_outward_flux_C':outer,
                   'gauss_flux_residual_C':-sum(charges.values())+outer,
                   'capacitance_methods_relative':results['capacitance_methods_relative'],
                   'native_seconds':perf_counter()-start,'geometry_kind':geometry['geometry_kind']}
    write_json(output/'diagnostics.json',diagnostics)
    warnings = []
    if payload['outputs']['field_images']:
        try:
            render(grid, output/'images')
        except Exception as exc:
            warnings.append('Optional field images failed: '+str(exc))
    return results, diagnostics, warnings


def render(grid, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.tri as mtri
    output.mkdir(exist_ok=False)
    triangles = grid.cells.reshape(-1,4)[:,1:]
    xy = grid.points
    triang = mtri.Triangulation(xy[:,0],xy[:,1],triangles)
    for field, unit, cell in (('electric_potential','V',False),('electric_field_magnitude','V/m',True)):
        for detail in (False,True):
            fig, ax = plt.subplots(figsize=(10,4),layout='constrained')
            values = grid.cell_data[field] if cell else grid.point_data[field]
            plotted = (ax.tripcolor(triang,facecolors=values,shading='flat') if cell else
                       ax.tripcolor(triang,values,shading='gouraud'))
            ax.set_aspect('auto' if detail else 'equal')
            ax.set(xlabel='x [m]',ylabel='y [m]',title=field+(' (vertical scale exaggerated)' if detail else ' (physical aspect)'))
            fig.colorbar(plotted,ax=ax,label=unit)
            fig.savefig(output/(field+('_detail' if detail else '')+'.png'),dpi=150)
            plt.close(fig)
