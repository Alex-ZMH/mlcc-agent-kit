"""Light extraction of existing electrothermal FEM utilities; original untouched."""
from scientific_core.fenicsx import (integral_local as integral, owned_cell_count as ncells,
    scalar_dg0 as scalar, scalar_cell_values as cell_values,
    interpolate_dg0 as dg, export_scalar_dg0 as export)

import json

from pathlib import Path

from time import perf_counter

import numpy as np

import ufl

from dolfinx import fem,io,plot

from dolfinx.fem.petsc import LinearProblem

from mpi4py import MPI

OPTIONS={"ksp_type":"preonly","pc_type":"lu","ksp_error_if_not_converged":True}



def write(path,obj):

    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)

    def numeric(value):

        if isinstance(value,np.generic):return value.item()

        raise TypeError(f'Unsupported JSON value: {type(value)}')

    path.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False,default=numeric),encoding='utf-8')


















def solve_linear(a,b,bcs,prefix):

    problem=LinearProblem(a,b,bcs=bcs,petsc_options_prefix=prefix,petsc_options=OPTIONS)

    start=perf_counter();sol=problem.solve();sol.x.scatter_forward()

    reason=int(problem.solver.getConvergedReason())

    r=problem.b.duplicate();problem.A.mult(sol.x.petsc_vec,r);r.axpy(-1.,problem.b)

    relative=float(r.norm()/max(problem.b.norm(),1e-30));r.destroy()

    if reason<=0 or not np.isfinite(sol.x.array).all():raise RuntimeError('linear solve failed')

    return sol,{'reason':reason,'iterations':int(problem.solver.getIterationNumber()),'relative_residual':relative,'seconds':perf_counter()-start}




