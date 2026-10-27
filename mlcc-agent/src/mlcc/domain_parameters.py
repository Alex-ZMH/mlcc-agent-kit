"""Small domain-result envelope; numerical work stays in each producer.

Each named property carries its own definition, unit, conditions, coordinate
basis, atom-map reference, source references and status. Large arrays can use
``data_ref`` instead of copying their values. No units, values or statuses are
inferred here, and no solver or export target is implied.
"""

from typing import Any


def domain_parameter_product(
    *,
    kind: str,
    model: dict[str, Any],
    study: dict[str, Any],
    properties: list[dict[str, Any]],
    execution: dict[str, Any],
) -> dict[str, Any]:
    """Keep the explicit producer values and existing artifact references."""
    return {
        "schema": "mlcc.domain-parameters.v1",
        "kind": kind,
        "model": model,
        "study": study,
        "properties": properties,
        "execution": execution,
    }
