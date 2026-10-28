"""Local assembly and explicitly requested global sum are separate operations."""
from dolfinx import fem


def assemble_local(expression):
    """Return the rank-local scalar contribution, retaining its scalar type."""
    return fem.assemble_scalar(fem.form(expression))


def integral_local(expression):
    """Real-valued rank-local integral; no implicit MPI reduction."""
    return float(assemble_local(expression))


def integral_global(expression, *, comm):
    """Real-valued SUM on the caller's communicator, as in the phase kernel."""
    from mpi4py import MPI
    return float(comm.allreduce(assemble_local(expression), op=MPI.SUM))
