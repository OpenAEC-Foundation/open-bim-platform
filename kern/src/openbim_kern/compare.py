"""Compare an IFC model with its cleaned copy, with IfcOpenShell: is the content the same?

Every record with a GlobalId (elements, spatial structure, types, property sets, relationships) gets a fingerprint of
everything it refers to, followed down to the last coordinate; a reference to another record with a GlobalId counts by
that GlobalId. Cleaning may merge identical records and leave out unreferenced geometry, properties and the like, but
these fingerprints must stay the same, as must the summary of the kern (classes, storeys, bounds, georeferencing). The
annotations without a GlobalId (styled items, layers) are compared the same way, as a set.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import ifcopenshell

from .index.spatial import summarize

# What cleaning may leave out when nothing refers to it (as converter/stepindex.mjs).
REMOVABLE = (
    "IfcGeometricRepresentationItem",
    "IfcTopologicalRepresentationItem",
    "IfcMappedItem",
    "IfcRepresentationMap",
    "IfcShapeModel",
    "IfcProductDefinitionShape",
    "IfcObjectPlacement",
    "IfcProfileDef",
    "IfcProperty",
    "IfcPropertyEnumeration",
    "IfcPhysicalQuantity",
    "IfcPresentationStyle",
    "IfcPresentationStyleAssignment",
    "IfcColourSpecification",
    "IfcColourRgbList",
    "IfcPreDefinedItem",
    "IfcCurveStyleFont",
    "IfcCurveStyleFontPattern",
    "IfcCurveStyleFontAndScaling",
    "IfcSurfaceStyleShading",
    "IfcSurfaceStyleLighting",
    "IfcSurfaceStyleRefraction",
    "IfcSurfaceStyleWithTextures",
    "IfcTextStyleForDefinedFont",
    "IfcTextStyleTextModel",
    "IfcNamedUnit",
    "IfcDerivedUnit",
    "IfcDerivedUnitElement",
    "IfcDimensionalExponents",
    "IfcMeasureWithUnit",
)
_MAX_REPORTED = 20


def model_differences(original: Path, cleaned: Path) -> list[str]:
    """What differs in content between two IFC files; empty when they hold the same model."""
    a, b = ifcopenshell.open(str(original)), ifcopenshell.open(str(cleaned))
    differences: list[str] = []
    if a.schema != b.schema:
        return [f"schema {a.schema} tegenover {b.schema}"]

    rooted_a, loose_a = _fingerprints(a)
    rooted_b, loose_b = _fingerprints(b)
    for gid in sorted(rooted_a.keys() - rooted_b.keys())[:_MAX_REPORTED]:
        differences.append(f"{rooted_a[gid][0]} {gid} ontbreekt")
    for gid in sorted(rooted_b.keys() - rooted_a.keys())[:_MAX_REPORTED]:
        differences.append(f"{rooted_b[gid][0]} {gid} is erbij gekomen")
    changed = [gid for gid in rooted_a.keys() & rooted_b.keys() if rooted_a[gid] != rooted_b[gid]]
    for gid in sorted(changed)[:_MAX_REPORTED]:
        differences.append(f"{rooted_a[gid][0]} {gid} heeft een andere inhoud")

    # Annotations: the same set, apart from loose geometry and the like that cleaning removed.
    for print_, entity in loose_b.items():
        if print_ not in loose_a:
            differences.append(f"{entity.is_a()} #{entity.id()} is erbij gekomen of veranderd")
    for print_, entity in loose_a.items():
        if print_ not in loose_b and not any(entity.is_a(t) for t in REMOVABLE):
            differences.append(f"{entity.is_a()} #{entity.id()} zonder GlobalId ontbreekt")

    summary_a, summary_b = summarize(a), summarize(b)
    for key in summary_a:
        if summary_a[key] != summary_b[key]:
            differences.append(f"samenvatting {key}: {summary_a[key]!r} tegenover {summary_b[key]!r}")
    return differences[: 3 * _MAX_REPORTED]


def _fingerprints(model: ifcopenshell.file) -> tuple[dict[str, tuple[str, int]], dict[int, Any]]:
    """Per GlobalId (class, fingerprint), and per fingerprint a record without GlobalId that nothing refers to."""
    memo: dict[int, int] = {}

    def value(v: Any) -> Any:
        if isinstance(v, ifcopenshell.entity_instance):
            if v.id() == 0:  # a typed value such as IfcLabel('x')
                return (v.is_a(), value(v.wrappedValue))
            if v.is_a("IfcRoot"):
                return ("GlobalId", v.GlobalId)
            return entity(v)
        if isinstance(v, tuple):
            return tuple(value(x) for x in v)
        return v

    def entity(e: ifcopenshell.entity_instance) -> int:
        key = e.id()
        found = memo.get(key)
        if found is None:
            found = hash((e.is_a(), tuple(value(e[i]) for i in range(len(e)))))
            memo[key] = found
        return found

    rooted = {e.GlobalId: (e.is_a(), entity(e)) for e in model.by_type("IfcRoot")}
    loose = {}
    for e in model:
        if not e.is_a("IfcRoot") and model.get_total_inverses(e) == 0:
            loose[entity(e)] = e
    return rooted, loose
