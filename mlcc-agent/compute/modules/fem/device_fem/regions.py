"""Pure set-based boundary audit, extracted from source RegionManifest.audit."""
from .geometry import BOUNDARIES


def audit_regions(exterior, facets):
    claimed, overlap, internal = set(), set(), set()
    errors = []
    for name in BOUNDARIES:
        region = facets.get(name, set())
        if not region:
            errors.append('Empty boundary: ' + name)
        overlap |= region & claimed
        internal |= region - exterior
        claimed |= region
    unknown = exterior - claimed
    if overlap:
        errors.append('Boundary groups overlap')
    if internal:
        errors.append('Boundary contains non-exterior facets')
    if unknown:
        errors.append('Exterior facets lack semantic labels')
    if set(facets) != set(BOUNDARIES):
        errors.append('Unexpected boundary identities')
    return {'valid': not errors, 'errors': errors,
            'facet_counts': {name: len(facets.get(name, set())) for name in BOUNDARIES},
            'exterior_facet_count': len(exterior), 'covered_exterior_facet_count': len(exterior & claimed),
            'unknown_exterior_facet_count': len(unknown), 'overlap_facet_count': len(overlap),
            'non_exterior_tagged_facet_count': len(internal)}
