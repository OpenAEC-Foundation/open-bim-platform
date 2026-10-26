"""Spatial tree and model summary read straight from the IFC entities (no geometry iterator)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.util.element as element_util
import ifcopenshell.util.placement
import ifcopenshell.util.unit


def _node(entity: ifcopenshell.entity_instance) -> dict[str, Any]:
    kids: list[dict[str, Any]] = []
    for rel in getattr(entity, "IsDecomposedBy", None) or []:
        if rel.is_a("IfcRelAggregates"):
            kids.extend(_node(child) for child in rel.RelatedObjects)
    for rel in getattr(entity, "ContainsElements", None) or []:
        kids.extend(_node(child) for child in rel.RelatedElements)
    return {"globalid": entity.GlobalId, "klasse": entity.is_a(), "naam": entity.Name, "kinderen": kids}


def build_spatial_tree(ifc: Path) -> dict[str, Any]:
    """Tree of IfcRelAggregates decomposition and spatial containment, rooted at the IfcProject."""
    model = ifcopenshell.open(str(ifc))
    projects = model.by_type("IfcProject")
    if not projects:
        raise ValueError("model has no IfcProject")
    return _node(projects[0])


def _georeferencing(model: ifcopenshell.file) -> dict[str, Any] | None:
    if model.schema == "IFC2X3":
        return None
    for conversion in model.by_type("IfcMapConversion"):
        crs = conversion.TargetCRS
        return {
            "eastings": conversion.Eastings,
            "northings": conversion.Northings,
            "orthogonal_height": conversion.OrthogonalHeight,
            "x_axis_abscissa": conversion.XAxisAbscissa,
            "x_axis_ordinate": conversion.XAxisOrdinate,
            "scale": conversion.Scale,
            "crs": crs.Name if crs is not None else None,
        }
    return None


def _bounds(model: ifcopenshell.file) -> dict[str, list[float]] | None:
    points = []
    for product in model.by_type("IfcProduct"):
        if product.ObjectPlacement is None or product.is_a("IfcOpeningElement"):
            continue
        try:
            matrix = ifcopenshell.util.placement.get_local_placement(product.ObjectPlacement)
        except Exception:  # noqa: BLE001 - malformed placements are skipped, bounds are best effort
            continue
        points.append([float(v) for v in matrix[:3, 3]])
    if not points:
        return None
    return {
        "min": [min(p[i] for p in points) for i in range(3)],
        "max": [max(p[i] for p in points) for i in range(3)],
    }


def build_summary(ifc: Path) -> dict[str, Any]:
    """Schema, length unit, georeferencing, placement-based bounds and element counts."""
    model = ifcopenshell.open(str(ifc))
    unit = ifcopenshell.util.unit.get_project_unit(model, "LENGTHUNIT")
    per_class: Counter[str] = Counter()
    per_storey: Counter[str] = Counter()
    for product in model.by_type("IfcProduct"):
        per_class[product.is_a()] += 1
    for el in model.by_type("IfcElement"):
        node = element_util.get_container(el)
        while node is not None and not node.is_a("IfcBuildingStorey"):
            node = element_util.get_aggregate(node)
        if node is not None:
            per_storey[node.GlobalId] += 1
    return {
        "schema": model.schema,
        "lengte_eenheid": ifcopenshell.util.unit.get_full_unit_name(unit) if unit else None,
        "georeferentie": _georeferencing(model),
        "begrenzing": _bounds(model),
        "aantallen_per_klasse": dict(per_class),
        "aantallen_per_verdieping": dict(per_storey),
    }
