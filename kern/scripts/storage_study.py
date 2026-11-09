"""Storage study for the design note on element storage and a relation graph.

    python scripts/storage_study.py <model.ifc> [--vorige <vorige versie.ifc>] [--uit <rapport.json>] [--frag]

For one IFC model it measures:

- the semantic graph without geometry: every object definition (element, spatial element, type, group) and every
  material or classification it is associated with is a node; every objectified relationship becomes edges between
  its relating and related objects; property sets become values on the nodes. Stored as relational tables in SQLite
  (measured) and in a record-based graph store (estimated lower bound, see `graph_store_bytes`);
- the naive graph that turns every STEP entity into a node and every reference into an edge;
- the derived data of today: the property index of the kern and, with --frag, the fragments file;
- the geometry per element, triangulated in its own coordinates and hashed by content (independent of the order of
  vertices and triangles): how much is shared within the model, and between two versions: --vorige, or else a second
  version made by moving and reshaping some elements, with the changes per IFC class;
- opening the model in IfcOpenShell: time and memory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import tempfile
import time
import zlib
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import psutil

from openbim_kern.index.properties import index_model

ENTITY_LINE = re.compile(rb"^\s*#\d+\s*=")
REFERENCE = re.compile(rb"#\d+")
# Classic record layout of a record-based graph store: fixed-size records for nodes, relationships and properties
# (up to four property blocks per record); a string that does not fit in a block goes to a dynamic store in blocks of
# 128 bytes. Indexes, labels beyond the record and the transaction log are left out, so this is a lower bound.
NODE_RECORD = 15
RELATIONSHIP_RECORD = 34
PROPERTY_RECORD = 41
BLOCKS_PER_PROPERTY_RECORD = 4
INLINE_STRING = 7
STRING_BLOCK = 128
STRING_BLOCK_PAYLOAD = 120
# Vertices are compared to 0.1 mm (the geometry iterator works in metres).
QUANTUM = 1e-4


def step_counts(path: Path) -> dict[str, int]:
    """Entities and references of a STEP file, read line by line."""
    entities = references = 0
    with path.open("rb") as f:
        for line in f:
            if ENTITY_LINE.match(line):
                entities += 1
                references += len(REFERENCE.findall(line)) - 1
    return {"bytes": path.stat().st_size, "entities": entities, "references": references}


def _entities(value: Any) -> Iterator[ifcopenshell.entity_instance]:
    if isinstance(value, ifcopenshell.entity_instance):
        yield value
    elif isinstance(value, tuple):
        for item in value:
            yield from _entities(item)


def _value(prop: ifcopenshell.entity_instance) -> tuple[str, str] | None:
    """(name, value as text) of a single property or quantity; None for complex ones."""
    if prop.is_a("IfcPropertySingleValue"):
        nominal = prop.NominalValue
        return prop.Name, "" if nominal is None else str(nominal.wrappedValue)
    if prop.is_a("IfcPhysicalSimpleQuantity"):
        return prop.Name, str(prop[3])
    return None


def semantic_graph(model: ifcopenshell.file) -> dict[str, Any]:
    """Nodes, edges and property values of the model without geometry."""
    nodes: dict[int, tuple[str | None, str, str | None]] = {}

    def node(entity: ifcopenshell.entity_instance) -> int:
        if entity.id() not in nodes:
            nodes[entity.id()] = (
                getattr(entity, "GlobalId", None),
                entity.is_a(),
                getattr(entity, "Name", None),
            )
        return entity.id()

    for entity in model.by_type("IfcObjectDefinition"):
        node(entity)
    edges: list[tuple[int, int, str]] = []
    values: list[tuple[int, str, str, str]] = []
    unique_values = 0
    for rel in model.by_type("IfcRelationship"):
        info = rel.get_info(recursive=False)
        if rel.is_a("IfcRelDefinesByProperties"):
            definition = rel.RelatingPropertyDefinition
            props = [
                v
                for p in (getattr(definition, "HasProperties", None) or getattr(definition, "Quantities", None) or ())
                if (v := _value(p))
            ]
            unique_values += len(props)
            for obj in _entities(rel.RelatedObjects):
                for name, value in props:
                    values.append((node(obj), definition.Name or "", name, value))
            continue
        relating = [e for k, v in info.items() if k.startswith("Relating") for e in _entities(v)]
        related = [e for k, v in info.items() if k.startswith("Related") for e in _entities(v)]
        for a in relating:
            for b in related:
                edges.append((node(a), node(b), rel.is_a()))
    return {"nodes": nodes, "edges": edges, "values": values, "unique_values": unique_values}


def sqlite_bytes(graph: dict[str, Any]) -> int:
    """The graph as relational tables (nodes, edges, values) with indexes on both ends of an edge."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "graaf.sqlite"
        db = sqlite3.connect(path)
        db.executescript(
            """CREATE TABLE knopen (id INTEGER PRIMARY KEY, globalid TEXT, klasse TEXT, naam TEXT);
            CREATE TABLE relaties (van INTEGER, naar INTEGER, soort TEXT);
            CREATE TABLE waarden (knoop INTEGER, pset TEXT, naam TEXT, waarde TEXT);
            CREATE INDEX relaties_van ON relaties (van);
            CREATE INDEX relaties_naar ON relaties (naar);
            CREATE INDEX waarden_knoop ON waarden (knoop);"""
        )
        db.executemany("INSERT INTO knopen VALUES (?, ?, ?, ?)", [(k, *v) for k, v in graph["nodes"].items()])
        db.executemany("INSERT INTO relaties VALUES (?, ?, ?)", graph["edges"])
        db.executemany("INSERT INTO waarden VALUES (?, ?, ?, ?)", graph["values"])
        db.commit()
        db.execute("VACUUM")
        db.close()
        return path.stat().st_size


def _string_bytes(text: str | None) -> int:
    size = len((text or "").encode("utf-8"))
    return 0 if size <= INLINE_STRING else STRING_BLOCK * math.ceil(size / STRING_BLOCK_PAYLOAD)


def graph_store_bytes(graph: dict[str, Any]) -> int:
    """Lower bound in a record-based graph store: GlobalId, class and name, and every property value, as properties."""
    per_node: dict[int, list[str | None]] = {k: [g, c, n] for k, (g, c, n) in graph["nodes"].items()}
    for knoop, _pset, _naam, waarde in graph["values"]:
        per_node[knoop].append(waarde)
    total = NODE_RECORD * len(per_node) + RELATIONSHIP_RECORD * len(graph["edges"])
    for props in per_node.values():
        total += PROPERTY_RECORD * math.ceil(len(props) / BLOCKS_PER_PROPERTY_RECORD)
        total += sum(_string_bytes(p) for p in props)
    return total


def columnar_bytes(graph: dict[str, Any]) -> int:
    """The property values column by column, compressed (zlib), as a stand-in for a columnar file per version."""
    columns = list(zip(*graph["values"], strict=True)) if graph["values"] else []
    return sum(len(zlib.compress("\n".join(map(str, column)).encode("utf-8"), 9)) for column in columns)


def index_bytes(model: ifcopenshell.file) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "eigenschappen.sqlite"
        index_model(model, db)
        return db.stat().st_size


class Mesh(NamedTuple):
    """The triangulated geometry of one element in its own coordinates."""

    representation: str
    digest: str  # content hash, independent of the order of vertices and triangles
    size: int  # bytes as float32 vertices and uint32 indices
    ifc_class: str
    raw_digest: str  # hash of vertices and indices in the order the iterator gives them


def canonical_digest(verts: np.ndarray, faces: np.ndarray) -> str:
    """Hash of the set of triangles, with vertices rounded to QUANTUM: the same shape written in another order gives
    the same hash."""
    if not len(faces):
        return hashlib.sha256(b"").hexdigest()
    corners = np.ascontiguousarray(verts[faces])  # triangles x 3 corners x 3 coordinates, int64
    as_corner = corners.view(np.dtype((np.void, 3 * 8))).reshape(len(faces), 3)
    as_corner.sort(axis=1)
    triangles = np.ascontiguousarray(as_corner).view(np.dtype((np.void, 9 * 8))).ravel()
    triangles.sort()
    return hashlib.sha256(triangles.tobytes()).hexdigest()


def meshes(model: ifcopenshell.file) -> dict[str, Mesh]:
    """Per GlobalId: the triangulated geometry of the element in its own coordinates."""
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", False)
    iterator = ifcopenshell.geom.iterator(settings, model)
    result: dict[str, Mesh] = {}
    if not iterator.initialize():
        return result
    while True:
        shape = iterator.get()
        geometry = shape.geometry
        verts = np.round(np.asarray(geometry.verts, dtype=np.float64) / QUANTUM).astype(np.int64).reshape(-1, 3)
        faces = np.asarray(geometry.faces, dtype=np.int64).reshape(-1, 3)
        result[shape.guid] = Mesh(
            geometry.id,
            canonical_digest(verts, faces),
            4 * (verts.size + faces.size),
            shape.type,
            hashlib.sha256(verts.tobytes() + faces.astype(np.int32).tobytes()).hexdigest(),
        )
        if not iterator.next():
            break
    return result


def mesh_summary(per_element: dict[str, Mesh]) -> dict[str, int]:
    unique = {m.digest: m.size for m in per_element.values()}
    return {
        "elementen": len(per_element),
        "representaties": len({m.representation for m in per_element.values()}),
        "unieke_meshes": len(unique),
        "unieke_meshes_ruwe_hash": len({m.raw_digest for m in per_element.values()}),
        "bytes_per_element": sum(m.size for m in per_element.values()),
        "bytes_uniek": sum(unique.values()),
    }


def second_version(model: ifcopenshell.file, out: Path, move: float = 0.1, reshape: float = 0.03) -> dict[str, int]:
    """Write a second version: a fraction of the elements moved, a fraction of the extruded ones made deeper."""
    elements = [e for e in model.by_type("IfcElement") if e.Representation and e.ObjectPlacement]
    moved = reshaped = 0
    for element in elements[:: max(1, round(1 / move))]:
        placement = element.ObjectPlacement
        if placement.is_a("IfcLocalPlacement") and placement.RelativePlacement.is_a("IfcAxis2Placement3D"):
            relative = placement.RelativePlacement
            x, y, z = relative.Location.Coordinates
            location = model.createIfcCartesianPoint((x + 0.5, y, z))
            axes = model.createIfcAxis2Placement3D(location, relative.Axis, relative.RefDirection)
            element.ObjectPlacement = model.createIfcLocalPlacement(placement.PlacementRelTo, axes)
            moved += 1
    wanted = max(1, round(reshape * len(elements)))
    for element in elements:
        if reshaped >= wanted:
            break
        representations = []
        changed = False
        for rep in element.Representation.Representations:
            items = []
            for item in rep.Items:
                if item.is_a("IfcExtrudedAreaSolid"):
                    item = model.createIfcExtrudedAreaSolid(
                        item.SweptArea, item.Position, item.ExtrudedDirection, item.Depth * 1.25
                    )
                    changed = True
                items.append(item)
            representations.append(
                model.createIfcShapeRepresentation(
                    rep.ContextOfItems, rep.RepresentationIdentifier, rep.RepresentationType, items
                )
            )
        if changed:
            element.Representation = model.createIfcProductDefinitionShape(None, None, representations)
            reshaped += 1
    model.write(str(out))
    return {"verplaatst": moved, "vervormd": reshaped}


def compare(first: dict[str, Mesh], second: dict[str, Mesh], classes: int = 8) -> dict[str, Any]:
    """The second version against the first, per GlobalId and per mesh hash: what a store with one copy per hash adds,
    with the elements per IFC class (the most common `classes`).

    A moved element keeps its mesh (geometry in its own coordinates); only its placement changes.
    """
    known = {m.digest for m in first.values()}
    unique = {m.digest: m.size for m in second.values()}
    common = [g for g in second if g in first]
    per_class: dict[str, Counter[str]] = defaultdict(Counter)
    for g, m in second.items():
        if g not in first:
            per_class[m.ifc_class]["nieuw"] += 1
        else:
            per_class[m.ifc_class]["zelfde" if first[g].digest == m.digest else "andere"] += 1
    for g, m in first.items():
        if g not in second:
            per_class[m.ifc_class]["weg"] += 1
    largest = sorted(per_class, key=lambda k: -sum(per_class[k].values()))[:classes]
    return {
        "elementen_v1": len(first),
        "elementen_v2": len(second),
        "zelfde_mesh": sum(1 for g in common if first[g].digest == second[g].digest),
        "zelfde_mesh_ruwe_hash": sum(1 for g in common if first[g].raw_digest == second[g].raw_digest),
        "andere_mesh": sum(1 for g in common if first[g].digest != second[g].digest),
        "nieuw": len(second) - len(common),
        "weg": sum(1 for g in first if g not in second),
        "unieke_meshes_v2": len(unique),
        "nieuwe_meshes_v2": sum(1 for d in unique if d not in known),
        "bytes_uniek_v2": sum(unique.values()),
        "bytes_nieuw_v2": sum(size for d, size in unique.items() if d not in known),
        "per_klasse": {k: dict(per_class[k]) for k in largest},
    }


def versions(path: Path, previous: Path | None = None) -> dict[str, Any]:
    """Two versions: `previous` and `path`, or `path` and a second version made by `second_version`."""
    if previous:
        return compare(meshes(ifcopenshell.open(str(previous))), meshes(ifcopenshell.open(str(path))))
    first = meshes(ifcopenshell.open(str(path)))
    with tempfile.TemporaryDirectory() as tmp:
        changed = second_version(ifcopenshell.open(str(path)), Path(tmp) / "v2.ifc")
        second = meshes(ifcopenshell.open(str(Path(tmp) / "v2.ifc")))
    return {**changed, **compare(first, second)}


def study(path: Path, frag: bool = False, previous: Path | None = None) -> dict[str, Any]:
    process = psutil.Process()
    before = process.memory_info().rss
    t0 = time.monotonic()
    model = ifcopenshell.open(str(path))
    opened = {"seconden": round(time.monotonic() - t0, 2), "rss_bytes": process.memory_info().rss - before}
    graph = semantic_graph(model)
    result: dict[str, Any] = {
        "bestand": path.name,
        "step": step_counts(path),
        "openen": opened,
        "graaf": {
            "knopen": len(graph["nodes"]),
            "relaties": len(graph["edges"]),
            "waarden": len(graph["values"]),
            "waarden_uniek": graph["unique_values"],
            "sqlite_bytes": sqlite_bytes(graph),
            "graafopslag_bytes_ondergrens": graph_store_bytes(graph),
            "waarden_kolommen_bytes": columnar_bytes(graph),
        },
        "index_bytes": index_bytes(model),
        "geometrie": mesh_summary(meshes(model)),
        "versies": versions(path, previous),
    }
    step = result["step"]
    result["naieve_graaf_bytes_ondergrens"] = NODE_RECORD * step["entities"] + RELATIONSHIP_RECORD * step["references"]
    if frag:
        from openbim_kern.converter import convert_to_frag

        with tempfile.TemporaryDirectory() as tmp:
            result["frag_bytes"] = convert_to_frag(path, Path(tmp) / "m.frag").out_bytes
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Opslagproef: graaf, index en geometrie per element.")
    parser.add_argument("ifc", type=Path)
    parser.add_argument("--uit", type=Path, help="JSON-rapport")
    parser.add_argument("--frag", action="store_true", help="ook het .frag-bestand maken en meten")
    parser.add_argument("--vorige", type=Path, help="de vorige versie van hetzelfde model")
    args = parser.parse_args(argv)
    result = study(args.ifc, frag=args.frag, previous=args.vorige)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.uit:
        args.uit.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
