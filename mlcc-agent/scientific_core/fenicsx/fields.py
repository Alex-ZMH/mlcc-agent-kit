"""Owned-cell DG0 operations with explicit blocked cell DOF indexing."""
import numpy as np
from dolfinx import fem


def owned_cell_count(mesh):
    return mesh.topology.index_map(mesh.topology.dim).size_local


def scalar_dg0(mesh, values, name):
    space = fem.functionspace(mesh, ('DG', 0))
    field = fem.Function(space, name=name)
    for cell, value in enumerate(np.broadcast_to(values, (owned_cell_count(mesh),))):
        field.x.array[space.dofmap.cell_dofs(cell)[0]] = value
    field.x.scatter_forward()
    return field


def cell_dof_values(field):
    """Return (owned cells, block components), not coefficient storage order.

    Only one-block-per-cell DG0 fields are supported. This is not a reader for
    CG, mixed, RT or higher-order elements, nor a distributed global gather.
    """
    space = field.function_space
    element = space.element.basix_element
    if element.degree != 0 or not element.discontinuous:
        raise ValueError('DG0 field required for cell DOF readback')
    block_size = space.dofmap.index_map_bs
    count = owned_cell_count(space.mesh)
    values = np.empty((count, block_size), dtype=field.x.array.dtype)
    for cell in range(count):
        dofs = space.dofmap.cell_dofs(cell)
        if len(dofs) != 1:
            raise ValueError('One DG0 block per cell required')
        index = int(dofs[0])*block_size
        values[cell] = field.x.array[index:index+block_size]
    return values


def scalar_cell_values(field):
    if field.function_space.dofmap.index_map_bs != 1 or field.ufl_shape != ():
        raise ValueError('Scalar DG0 field required')
    return cell_dof_values(field)[:, 0]


def interpolate_dg0(expression, mesh, name, vector=False):
    """Interpolate at DG0 interpolation points; does not perform L2 projection."""
    shape = ('DG', 0, (mesh.geometry.dim,)) if vector else ('DG', 0)
    space = fem.functionspace(mesh, shape)
    field = fem.Function(space, name=name)
    field.interpolate(fem.Expression(expression, space.element.interpolation_points))
    return field
