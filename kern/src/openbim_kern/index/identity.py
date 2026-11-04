"""Identity of elements for linking versions: class, type, name, storey and placement origin.

When an exporter hands out new GlobalIds, a later version is linked to the previous one on this identity
(openbim_kern.linking). Coordinates are in metres, rounded to a millimetre, so a model in millimetres and one in metres
give the same key.
"""

from __future__ import annotations

import sqlite3

import ifcopenshell
import ifcopenshell.util.element as element_util
import ifcopenshell.util.placement
import ifcopenshell.util.unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS identiteit (
    globalid TEXT PRIMARY KEY, ifc_class TEXT, type_name TEXT, name TEXT, storey_name TEXT, x REAL, y REAL, z REAL);
"""


def index_identity(model: ifcopenshell.file, con: sqlite3.Connection) -> None:
    """Fill the table `identiteit` for every IfcProduct with an object placement."""
    from .properties import _storey  # properties calls this module while indexing

    con.executescript(SCHEMA)
    scale = ifcopenshell.util.unit.calculate_unit_scale(model)
    for product in model.by_type("IfcProduct"):
        if not product.ObjectPlacement:
            continue
        origin = ifcopenshell.util.placement.get_local_placement(product.ObjectPlacement)[:3, 3] * scale
        type_ = element_util.get_type(product) if product.is_a("IfcObject") else None
        storey = _storey(product)
        con.execute(
            "INSERT OR IGNORE INTO identiteit VALUES (?,?,?,?,?,?,?,?)",
            (
                product.GlobalId,
                product.is_a(),
                type_.Name if type_ else None,
                product.Name,
                storey.Name if storey else None,
                *(round(float(v), 3) for v in origin),
            ),
        )
