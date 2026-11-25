"""Export a passport as OpenLineage dataset facets.

No OpenLineage dependency is needed: the facets are plain JSON that you attach to
a dataset in a RunEvent (``inputs[].facets`` / ``inputs[].inputFacets``), for
example from an Airflow or Dagster task. Field sets follow the published facet
schemas (SchemaDatasetFacet 1-1-1, DataQualityMetricsInputDatasetFacet 1-0-1,
DatasetVersionDatasetFacet 1-0-1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..__about__ import __version__

if TYPE_CHECKING:
    from ..models import Passport

PRODUCER = f"https://pypi.org/project/datapassport/{__version__}"
SCHEMA = "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json"
DQ = "https://openlineage.io/spec/facets/1-0-1/DataQualityMetricsInputDatasetFacet.json"
VERSION = "https://openlineage.io/spec/facets/1-0-1/DatasetVersionDatasetFacet.json"


def passport_facets(p: Passport) -> dict[str, Any]:
    """Return ``{"facets": {...}, "inputFacets": {...}}`` for an OpenLineage dataset."""
    schema = {
        "_producer": PRODUCER,
        "_schemaURL": SCHEMA,
        "fields": [{"name": c.name, "type": c.type} for c in sorted(p.schema_, key=lambda c: c.position)],
    }
    columns: dict[str, Any] = {}
    for name, c in p.columns.items():
        m: dict[str, Any] = {"nullCount": c.nulls, "count": c.count}
        if c.distinct is not None:
            m["distinctCount"] = c.distinct
        if c.numeric and not c.sensitive:
            if c.numeric.min is not None:
                m["min"], m["max"] = c.numeric.min, c.numeric.max
            if c.numeric.mean is not None:
                m["sum"] = c.numeric.mean * (c.count - c.numeric.nan - c.numeric.infinite)
            q = c.numeric.quantiles
            if q:
                m["quantiles"] = {"0.25": q[25], "0.5": q[50], "0.75": q[75]}
        columns[name] = m
    dq: dict[str, Any] = {"_producer": PRODUCER, "_schemaURL": DQ, "rowCount": p.rows, "columnMetrics": columns}
    if p.source.bytes is not None:
        dq["bytes"] = p.source.bytes
    if p.source.files is not None:
        dq["fileCount"] = p.source.files
    version = {"_producer": PRODUCER, "_schemaURL": VERSION, "datasetVersion": p.fingerprint.dataset}
    return {
        "facets": {"schema": schema, "version": version},
        "inputFacets": {"dataQualityMetrics": dq},
    }
