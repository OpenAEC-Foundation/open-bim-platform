import sqlite3

import ifcopenshell
import ifcopenshell.api
import numpy as np

from openbim_kern.index.properties import build_property_index


def identity_rows(db):
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        return {row["globalid"]: dict(row) for row in con.execute("SELECT * FROM identiteit")}


def first_wall_globalid(ifc_path):
    walls = ifcopenshell.open(str(ifc_path)).by_type("IfcWall")
    return next(w.GlobalId for w in walls if w.Name.startswith("Wand A 0"))


def wall_model(path, unit):
    """A project in `unit` with one wall placed at 5,25 m / 2 m / 0,5 m (placement given in metres)."""
    f = ifcopenshell.api.run("project.create_file", version="IFC4")
    ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject", name="Eenheden")
    ifcopenshell.api.run("unit.assign_unit", f, length={"is_metric": True, "raw": unit})
    wall = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcWall", name="Wand")
    matrix = np.eye(4)
    matrix[:3, 3] = (5.25, 2.0, 0.5)
    ifcopenshell.api.run("geometry.edit_object_placement", f, product=wall, matrix=matrix)
    f.write(str(path))
    return wall.GlobalId


def test_identity_has_placement_in_metres(ifc_small, tmp_path):
    build_property_index(ifc_small, tmp_path / "e.sqlite")
    rows = identity_rows(tmp_path / "e.sqlite")
    wall = rows[first_wall_globalid(ifc_small)]
    assert wall["ifc_class"] == "IfcWall" and wall["storey_name"] == "00 begane grond"
    assert all(round(v, 3) == v for v in (wall["x"], wall["y"], wall["z"]))


def test_identity_uses_metres_for_a_millimetre_model(tmp_path):
    gid_m = wall_model(tmp_path / "m.ifc", "METERS")
    gid_mm = wall_model(tmp_path / "mm.ifc", "MILLIMETERS")
    build_property_index(tmp_path / "m.ifc", tmp_path / "m.sqlite")
    build_property_index(tmp_path / "mm.ifc", tmp_path / "mm.sqlite")
    in_m = identity_rows(tmp_path / "m.sqlite")[gid_m]
    in_mm = identity_rows(tmp_path / "mm.sqlite")[gid_mm]
    assert (in_m["x"], in_m["y"], in_m["z"]) == (5.25, 2.0, 0.5)
    assert (in_mm["x"], in_mm["y"], in_mm["z"]) == (5.25, 2.0, 0.5)


def test_identity_names_the_type(ifc_small, tmp_path):
    model = ifcopenshell.open(str(ifc_small))
    wall = model.by_type("IfcWall")[0]
    wall_type = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWallType", name="Binnenwand 100")
    ifcopenshell.api.run("type.assign_type", model, related_objects=[wall], relating_type=wall_type)
    model.write(str(tmp_path / "m.ifc"))
    build_property_index(tmp_path / "m.ifc", tmp_path / "e.sqlite")
    rows = identity_rows(tmp_path / "e.sqlite")
    assert rows[wall.GlobalId]["type_name"] == "Binnenwand 100"
    assert rows[wall.GlobalId]["name"] == wall.Name
