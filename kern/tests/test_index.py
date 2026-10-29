import sqlite3

import ifcopenshell

from openbim_kern.index.properties import build_property_index, count_elements, read_properties
from openbim_kern.index.spatial import build_spatial_tree, build_summary


def first_wall_globalid(ifc_path):
    walls = ifcopenshell.open(str(ifc_path)).by_type("IfcWall")
    return next(w.GlobalId for w in walls if w.Name.startswith("Wand A 0"))


def depth_of_storeys(tree, depth=0):
    if tree["klasse"] == "IfcBuildingStorey":
        return depth
    for child in tree["kinderen"]:
        found = depth_of_storeys(child, depth + 1)
        if found is not None:
            return found
    return None


def test_index_small(ifc_small, tmp_path):
    build_property_index(ifc_small, tmp_path / "e.sqlite")
    wall = first_wall_globalid(ifc_small)
    p = read_properties(tmp_path / "e.sqlite", [wall])[wall]
    assert p["klasse"] == "IfcWall" and p["psets"]["Pset_WallCommon"]["FireRating"] == "60"
    assert p["materialen"] == ["Beton"] and p["classificaties"][0]["code"] == "21.12"
    assert p["classificaties"][0]["systeem"] == "NL-SfB"
    assert p["verdieping"] is not None


def test_index_2x3(ifc_2x3, tmp_path):
    build_property_index(ifc_2x3, tmp_path / "e.sqlite")
    wall = first_wall_globalid(ifc_2x3)
    p = read_properties(tmp_path / "e.sqlite", [wall])[wall]
    assert p["psets"]["Pset_WallCommon"]["FireRating"] == "60"
    assert p["classificaties"] == []


def test_index_is_per_source(ifc_small, ifc_2x3, tmp_path):
    build_property_index(ifc_small, tmp_path / "a.sqlite")
    build_property_index(ifc_2x3, tmp_path / "b.sqlite")
    wall_a = first_wall_globalid(ifc_small)
    wall_b = first_wall_globalid(ifc_2x3)
    assert wall_a in read_properties(tmp_path / "a.sqlite", [wall_a])
    assert read_properties(tmp_path / "a.sqlite", [wall_b]) == {}
    assert read_properties(tmp_path / "b.sqlite", [wall_a]) == {}
    assert wall_b in read_properties(tmp_path / "b.sqlite", [wall_b])


def test_index_twice_is_idempotent(ifc_small, tmp_path):
    db = tmp_path / "e.sqlite"
    build_property_index(ifc_small, db)
    build_property_index(ifc_small, db)
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT count(*) FROM elements WHERE ifc_class='IfcWall'").fetchone()[0] == 6
        assert con.execute("SELECT count(*) FROM classifications").fetchone()[0] == 6
        assert con.execute("SELECT count(*) FROM materials").fetchone()[0] == 6
    wall = first_wall_globalid(ifc_small)
    p = read_properties(db, [wall])[wall]
    assert p["materialen"] == ["Beton"] and len(p["classificaties"]) == 1


def test_read_unknown_globalid_absent(ifc_small, tmp_path):
    build_property_index(ifc_small, tmp_path / "e.sqlite")
    assert read_properties(tmp_path / "e.sqlite", ["nope"]) == {}


def test_summary_georef(ifc_georef):
    s = build_summary(ifc_georef)
    assert s["georeferentie"]["eastings"] == 155000 and s["georeferentie"]["crs"] == "EPSG:28992"


def test_summary_without_georef(ifc_small):
    assert build_summary(ifc_small)["georeferentie"] is None


def test_summary_counts(ifc_small):
    s = build_summary(ifc_small)
    assert s["aantallen_per_klasse"]["IfcWall"] == 6 and len(s["aantallen_per_verdieping"]) == 2
    assert s["schema"] == "IFC4"
    assert s["lengte_eenheid"]
    assert s["begrenzing"]["min"] != s["begrenzing"]["max"]


def test_spatial_tree(ifc_small):
    t = build_spatial_tree(ifc_small)
    assert t["klasse"] == "IfcProject" and depth_of_storeys(t) == 3


def test_index_spatial_objects(ifc_small, tmp_path):
    import ifcopenshell

    build_property_index(ifc_small, tmp_path / "e.sqlite")
    model = ifcopenshell.open(str(ifc_small))
    storey = model.by_type("IfcBuildingStorey")[0]
    site = model.by_type("IfcSite")[0]
    project = model.by_type("IfcProject")[0]
    got = read_properties(tmp_path / "e.sqlite", [storey.GlobalId, site.GlobalId, project.GlobalId])
    assert got[storey.GlobalId]["klasse"] == "IfcBuildingStorey"
    assert got[storey.GlobalId]["verdieping"] == storey.GlobalId
    assert got[site.GlobalId]["klasse"] == "IfcSite" and got[site.GlobalId]["verdieping"] is None
    assert got[project.GlobalId]["klasse"] == "IfcProject"


def test_summary_counts_spatial(ifc_small):
    s = build_summary(ifc_small)["aantallen_per_klasse"]
    assert s["IfcBuildingStorey"] == 2 and s["IfcSite"] == 1


def test_index_types(ifc_small, tmp_path):
    # Types are indexed too, so a reader can show the name of an element's type and the properties of the type.
    import ifcopenshell.api

    model = ifcopenshell.open(str(ifc_small))
    wall = model.by_type("IfcWall")[0]
    wall_type = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWallType", name="Binnenwand 100")
    ifcopenshell.api.run("type.assign_type", model, related_objects=[wall], relating_type=wall_type)
    pset = ifcopenshell.api.run("pset.add_pset", model, product=wall_type, name="Pset_WallCommon")
    ifcopenshell.api.run("pset.edit_pset", model, pset=pset, properties={"AcousticRating": "R40"})
    model.write(str(tmp_path / "m.ifc"))
    build_property_index(tmp_path / "m.ifc", tmp_path / "e.sqlite")
    got = read_properties(tmp_path / "e.sqlite", [wall.GlobalId, wall_type.GlobalId])
    assert got[wall.GlobalId]["type"] == wall_type.GlobalId
    assert got[wall_type.GlobalId]["klasse"] == "IfcWallType"
    assert got[wall_type.GlobalId]["naam"] == "Binnenwand 100"
    assert got[wall_type.GlobalId]["psets"]["Pset_WallCommon"]["AcousticRating"] == "R40"
    # Types are not elements: the counts per class leave them out.
    assert "IfcWallType" not in count_elements(tmp_path / "e.sqlite")["aantallen_per_klasse"]


def test_read_an_index_without_types(ifc_small, tmp_path):
    # An index made before types were indexed still reads; a type GlobalId is then simply absent.
    db = tmp_path / "e.sqlite"
    build_property_index(ifc_small, db)
    with sqlite3.connect(db) as con:
        con.execute("DROP TABLE IF EXISTS types")
    assert read_properties(db, ["0000000000000000000000"]) == {}
    assert read_properties(db, [first_wall_globalid(ifc_small)])
