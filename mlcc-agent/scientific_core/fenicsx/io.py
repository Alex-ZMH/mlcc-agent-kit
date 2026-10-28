"""Static serial CG1 scalar / DG0 scalar-or-vector export and VTU readback.

The module owns field names, units, coordinates, physical interpretation, and
scientific checks. No unit conversion, smoothing, projection or QC threshold.
"""
from pathlib import Path
import numpy as np
from dolfinx import io, plot
from .fields import cell_dof_values


def export_scalar_dg0(out, mesh, point_fields, cell_fields, tags=None):
    import pyvista as pv

    if mesh.comm.size != 1:
        raise ValueError('Static VTU readback exporter supports one MPI rank only')
    if not point_fields:
        raise ValueError('At least one CG1 scalar point field is required')
    dimension = mesh.geometry.dim
    if dimension not in (2, 3):
        raise ValueError('Only geometric dimensions 2 and 3 are supported')
    names = [f.name for f in point_fields+cell_fields]
    if len(set(names)) != len(names) or (tags is not None and 'material_tag' in names):
        raise ValueError('Unique field names required for lossless export')
    for field in point_fields:
        element = field.function_space.element.basix_element
        if field.ufl_shape != () or element.degree != 1 or element.discontinuous:
            raise ValueError('CG1 scalar point fields required')
    space = point_fields[0].function_space
    top, types, xyz = plot.vtk_mesh(space)
    grid = pv.UnstructuredGrid(top, types, xyz)
    for field in point_fields:
        if not np.array_equal(field.function_space.tabulate_dof_coordinates(),
                              space.tabulate_dof_coordinates()):
            raise ValueError('Point fields must share mesh and DOF ordering')
        grid.point_data[field.name] = field.x.array.copy()
    for field in cell_fields:
        if field.ufl_shape not in ((), (dimension,)):
            raise ValueError('DG0 scalar or geometric vector cell fields required')
        if field.function_space.mesh is not mesh:
            raise ValueError('Cell fields must belong to the exported mesh')
        values = cell_dof_values(field)
        grid.cell_data[field.name] = (values[:, 0] if values.shape[1] == 1 else
                                     np.c_[values, np.zeros(len(values))]
                                     if values.shape[1] == 2 else values)
    if tags is not None:
        grid.cell_data['material_tag'] = tags
    if not all(np.isfinite(a).all() for a in [grid.points, *grid.point_data.values(), *grid.cell_data.values()]):
        raise ValueError('Non-finite field or mesh cannot be exported')
    out = Path(out)
    grid.save(out.with_suffix('.vtu'))
    saved = pv.read(out.with_suffix('.vtu'))
    if not np.array_equal(saved.cells, grid.cells) or not np.array_equal(saved.points, grid.points):
        raise ValueError('export mesh readback mismatch')
    for name in grid.point_data:
        if not np.array_equal(saved.point_data[name], grid.point_data[name]):
            raise ValueError('point readback mismatch')
    for name in grid.cell_data:
        if not np.array_equal(saved.cell_data[name], grid.cell_data[name]):
            raise ValueError('cell readback mismatch')
    with io.XDMFFile(mesh.comm, str(out.with_suffix('.xdmf')), 'w') as stream:
        stream.write_mesh(mesh)
        for field in point_fields+cell_fields:
            stream.write_function(field)
    return {'cells': grid.n_cells, 'points': grid.n_points, 'VTU_readback': 'PASS',
            'fields': list(grid.point_data)+list(grid.cell_data)}
