"""SQLite property index over an IFC file: build it once, read selected elements cheaply."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.util.classification
import ifcopenshell.util.element as element_util
from typing_extensions import TypedDict

from ..errors import KernError

SCHEMA = """
CREATE TABLE IF NOT EXISTS elements (
    globalid TEXT PRIMARY KEY, ifc_class TEXT, name TEXT, type_globalid TEXT, storey_globalid TEXT);
CREATE TABLE IF NOT EXISTS properties (
    globalid TEXT, set_name TEXT, name TEXT, value TEXT, unit TEXT, kind TEXT,
    UNIQUE (globalid, set_name, name, kind));
CREATE TABLE IF NOT EXISTS materials (globalid TEXT, material TEXT, UNIQUE (globalid, material));
CREATE TABLE IF NOT EXISTS classifications (
    globalid TEXT, system TEXT, code TEXT, name TEXT, UNIQUE (globalid, system, code));
CREATE TABLE IF NOT EXISTS types (globalid TEXT PRIMARY KEY, ifc_class TEXT, name TEXT);
"""


class ElementProperties(TypedDict):
    klasse: str
    naam: str | None
    type: str | None
    verdieping: str | None
    psets: dict[str, dict[str, Any]]
    hoeveelheden: dict[str, dict[str, Any]]
    materialen: list[str]
    classificaties: list[dict[str, str | None]]


def _json_safe(value: Any) -> Any:
    if isinstance(value, ifcopenshell.entity_instance):
        return value.wrappedValue if hasattr(value, "wrappedValue") else value.is_a()
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _storey(element: ifcopenshell.entity_instance) -> ifcopenshell.entity_instance | None:
    """Storey of an element; a storey is its own storey, project/site/building have none."""
    if element.is_a("IfcBuildingStorey"):
        return element
    if not element.is_a("IfcElement") and not element.is_a("IfcSpace"):
        return None
    node = element_util.get_container(element)
    while node is not None and not node.is_a("IfcBuildingStorey"):
        node = element_util.get_aggregate(node)
    return node


def _materials(element: ifcopenshell.entity_instance) -> list[str]:
    if element_util.get_material(element) is None:
        return []
    names: list[str] = []
    for item in element_util.get_materials(element):
        name = getattr(item, "Name", None)
        if name and name not in names:
            names.append(name)
    return names


def _classifications(element: ifcopenshell.entity_instance) -> list[tuple[str | None, str, str | None]]:
    found = []
    for ref in ifcopenshell.util.classification.get_references(element):
        code = getattr(ref, "Identification", None) or getattr(ref, "ItemReference", None)
        if code is None:
            continue
        system = ifcopenshell.util.classification.get_classification(ref)
        found.append((getattr(system, "Name", None) if system else None, code, getattr(ref, "Name", None)))
    return found


def build_property_index(ifc: Path, db: Path) -> None:
    """Create or extend the index database from an IFC file; see index_model."""
    index_model(ifcopenshell.open(str(ifc)), db)


def index_model(model: ifcopenshell.file, db: Path) -> None:
    """Create or extend the index database.

    Rows are inserted with INSERT OR IGNORE so the parts of a split file can fill one database.
    """
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as con:
        con.executescript(SCHEMA)
        indexed = [*model.by_type("IfcProject"), *model.by_type("IfcProduct")]
        # Types in a table of their own: a reader can show the name and properties of an element's type, and the
        # counts per class (elements) leave them out.
        for type_ in model.by_type("IfcTypeObject"):
            con.execute("INSERT OR IGNORE INTO types VALUES (?,?,?)", (type_.GlobalId, type_.is_a(), type_.Name))
            _index_sets(con, type_)
        for el in indexed:
            gid = el.GlobalId
            type_ = element_util.get_type(el) if el.is_a("IfcObject") else None
            storey = _storey(el)
            con.execute(
                "INSERT OR IGNORE INTO elements VALUES (?,?,?,?,?)",
                (gid, el.is_a(), el.Name, type_.GlobalId if type_ else None, storey.GlobalId if storey else None),
            )
            _index_sets(con, el)
            for material in _materials(el):
                con.execute("INSERT OR IGNORE INTO materials VALUES (?,?)", (gid, material))
            for system, code, name in _classifications(el):
                con.execute("INSERT OR IGNORE INTO classifications VALUES (?,?,?,?)", (gid, system, code, name))
        con.commit()


def _index_sets(con: sqlite3.Connection, entity: ifcopenshell.entity_instance) -> None:
    """The property and quantity sets of an element or type."""
    for kind, kwargs in (("pset", {"psets_only": True}), ("qto", {"qtos_only": True})):
        for set_name, props in element_util.get_psets(entity, **kwargs).items():
            for name, value in props.items():
                if name == "id":
                    continue
                con.execute(
                    "INSERT OR IGNORE INTO properties VALUES (?,?,?,?,?,?)",
                    (entity.GlobalId, set_name, name, json.dumps(_json_safe(value)), None, kind),
                )


def count_elements(db: Path) -> dict[str, dict[str, int]]:
    """Counts per class and per storey over the distinct GlobalIds in the index.

    Same meaning as the counts of build_summary: every IfcProduct per class, and per storey the elements in it (not
    the storey itself or its spaces). The parts of a split file share their spatial structure, and counting GlobalIds
    counts it once.
    """
    with closing(sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)) as con:
        per_class = con.execute(
            "SELECT ifc_class, count(*) FROM elements WHERE ifc_class != 'IfcProject' GROUP BY ifc_class"
        )
        per_storey = con.execute(
            "SELECT storey_globalid, count(*) FROM elements WHERE storey_globalid IS NOT NULL"
            " AND storey_globalid != globalid AND ifc_class != 'IfcSpace' GROUP BY storey_globalid"
        )
        return {
            "aantallen_per_klasse": dict(per_class.fetchall()),
            "aantallen_per_verdieping": dict(per_storey.fetchall()),
        }


def read_properties(db: Path, globalids: list[str]) -> dict[str, ElementProperties]:
    """Properties of the given elements; unknown GlobalIds are absent from the result."""
    try:
        return _read(db, globalids)
    except sqlite3.Error as exc:
        raise KernError(
            "index_ongeldig",
            f"De index is geen geldige eigenschappen-index: {exc}.",
            "Lever een index aan die met build_property_index is gemaakt.",
            status=422,
        ) from exc


def _read(db: Path, globalids: list[str]) -> dict[str, ElementProperties]:
    result: dict[str, ElementProperties] = {}
    with closing(sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)) as con:
        # An index from before types were indexed has no table `types`.
        has_types = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='types'").fetchone()
        for gid in dict.fromkeys(globalids):
            row = con.execute(
                "SELECT ifc_class, name, type_globalid, storey_globalid FROM elements WHERE globalid=?", (gid,)
            ).fetchone()
            if row is None and has_types:
                row = con.execute("SELECT ifc_class, name, NULL, NULL FROM types WHERE globalid=?", (gid,)).fetchone()
            if row is None:
                continue
            psets: dict[str, dict[str, Any]] = {}
            qtos: dict[str, dict[str, Any]] = {}
            for set_name, name, value, kind in con.execute(
                "SELECT set_name, name, value, kind FROM properties WHERE globalid=? ORDER BY rowid", (gid,)
            ):
                (psets if kind == "pset" else qtos).setdefault(set_name, {})[name] = json.loads(value)
            materials = con.execute("SELECT material FROM materials WHERE globalid=? ORDER BY rowid", (gid,))
            classes = con.execute(
                "SELECT system, code, name FROM classifications WHERE globalid=? ORDER BY rowid", (gid,)
            )
            result[gid] = ElementProperties(
                klasse=row[0],
                naam=row[1],
                type=row[2],
                verdieping=row[3],
                psets=psets,
                hoeveelheden=qtos,
                materialen=[m for (m,) in materials],
                classificaties=[{"systeem": s, "code": c, "naam": n} for s, c, n in classes],
            )
    return result
