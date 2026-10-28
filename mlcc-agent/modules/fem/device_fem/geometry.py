"""OCC MLCC cross section, extracted from the reviewed MLCC2DBuilder.

Original: fem-general-main src/fem_agent/geometry/mlcc.py at 9ba35c4.
See SOURCES.json. No imports from the source repository or its DTO/registries.
"""
from .common import ModuleError
from .validation import body_height

BOUNDARIES = ('ELECTRODE_A', 'ELECTRODE_B', 'OUTER_INSULATION')


def build_mlcc(gmsh, payload):
    p = payload['geometry']
    length, height = p['body_length_m'], body_height(payload)
    gap, thickness = p['dielectric_gap_m'], p['electrode_thickness_m']
    left, right, bottom = p['left_margin_m'], p['right_margin_m'], p['bottom_cover_m']
    occ = gmsh.model.occ
    body = occ.addRectangle(0, 0, 0, length, height)
    rectangles = []
    for index in range(p['active_gap_count']+1):
        x0, x1 = (0.0, length-right) if index % 2 == 0 else (left, length)
        y0 = bottom + index*(thickness+gap)
        entity = occ.addRectangle(x0, y0, 0, x1-x0, thickness)
        rectangles.append((x0, x1, y0, y0+thickness,
                           BOUNDARIES[index % 2], entity))
    dielectric, _ = occ.cut([(2, body)], [(2, r[5]) for r in rectangles],
                            removeObject=True, removeTool=True)
    occ.synchronize()
    domains = [tag for dim, tag in dielectric if dim == 2]
    if not domains:
        raise ModuleError('GEOMETRY_FAILED', 'MLCC dielectric is empty')
    gmsh.model.addPhysicalGroup(2, domains, 10)
    gmsh.model.setPhysicalName(2, 10, 'CERAMIC')
    groups = {name: [] for name in BOUNDARIES}
    tol = max(length, height)*1e-9  # geometric matching tolerance retained from source
    curves = {tag for dim, tag in gmsh.model.getBoundary(dielectric, oriented=False) if dim == 1}
    for curve in curves:
        endpoints = gmsh.model.getBoundary([(1, curve)], oriented=False)
        if len(endpoints) != 2 or any(dim != 0 for dim, _ in endpoints):
            raise ModuleError('GEOMETRY_FAILED', 'Only straight two-endpoint MLCC segments are supported')
        coords = [gmsh.model.getValue(0, tag, []) for _, tag in endpoints]
        xmin, xmax = sorted(v[0] for v in coords)
        ymin, ymax = sorted(v[1] for v in coords)
        matches = []
        for x0, x1, y0, y1, name, _ in rectangles:
            horizontal = (xmin >= x0-tol and xmax <= x1+tol and
                          (abs(ymin-y0) <= tol and abs(ymax-y0) <= tol or
                           abs(ymin-y1) <= tol and abs(ymax-y1) <= tol))
            vertical = (ymin >= y0-tol and ymax <= y1+tol and
                        (abs(xmin-x0) <= tol and abs(xmax-x0) <= tol or
                         abs(xmin-x1) <= tol and abs(xmax-x1) <= tol))
            if horizontal or vertical:
                matches.append(name)
        if len(matches) > 1:
            raise ModuleError('GEOMETRY_FAILED', f'Ambiguous electrode segment {curve}')
        if matches:
            groups[matches[0]].append(curve)
        elif (abs(xmin) <= tol and abs(xmax) <= tol or
              abs(xmin-length) <= tol and abs(xmax-length) <= tol or
              abs(ymin) <= tol and abs(ymax) <= tol or
              abs(ymin-height) <= tol and abs(ymax-height) <= tol):
            groups['OUTER_INSULATION'].append(curve)
        else:
            raise ModuleError('GEOMETRY_FAILED', f'Unassigned dielectric segment {curve}')
    for tag, name in enumerate(BOUNDARIES, 11):
        if not groups[name]:
            raise ModuleError('GEOMETRY_FAILED', 'Empty physical group ' + name)
        gmsh.model.addPhysicalGroup(1, sorted(groups[name]), tag)
        gmsh.model.setPhysicalName(1, tag, name)
    return {'body_height_m': height, 'electrode_count': p['active_gap_count']+1,
            'boundary_curve_counts': {name: len(curves) for name, curves in groups.items()},
            'domain': 'CERAMIC', 'geometry_kind': 'mlcc_2d'}


def build_plate_benchmark(gmsh, payload):
    """Harness-only analytical limit. Never selected by a public scientific input."""
    width, height = payload['geometry']['body_length_m'], body_height(payload)
    surface = gmsh.model.occ.addRectangle(0, 0, 0, width, height)
    gmsh.model.occ.synchronize()
    gmsh.model.addPhysicalGroup(2, [surface], 10)
    gmsh.model.setPhysicalName(2, 10, 'CERAMIC')
    groups = {name: [] for name in BOUNDARIES}
    for dim, tag in gmsh.model.getBoundary([(2, surface)], oriented=False):
        _, y, _ = gmsh.model.occ.getCenterOfMass(dim, tag)
        name = ('ELECTRODE_A' if abs(y) < height*1e-9 else
                'ELECTRODE_B' if abs(y-height) < height*1e-9 else 'OUTER_INSULATION')
        groups[name].append(tag)
    for tag, name in enumerate(BOUNDARIES, 11):
        gmsh.model.addPhysicalGroup(1, groups[name], tag)
        gmsh.model.setPhysicalName(1, tag, name)
    return {'body_height_m': height, 'electrode_count': 2,
            'boundary_curve_counts': {n:len(v) for n,v in groups.items()},
            'domain': 'CERAMIC', 'geometry_kind': 'parallel_plate_benchmark_only'}
