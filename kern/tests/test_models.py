import ifcopenshell
import ifcopenshell.util.element as uel


def test_small_model_contents(ifc_small):
    m = ifcopenshell.open(ifc_small)
    assert m.schema == "IFC4" and len(m.by_type("IfcWall")) == 6 and len(m.by_type("IfcBuildingStorey")) == 2
    assert len({e.GlobalId for e in m.by_type("IfcRoot")}) == len(m.by_type("IfcRoot"))


def test_small_model_details(ifc_small):
    m = ifcopenshell.open(ifc_small)
    assert sorted(s.Name for s in m.by_type("IfcBuildingStorey")) == ["00 begane grond", "01 eerste verdieping"]
    assert len(m.by_type("IfcSlab")) == 1 and len(m.by_type("IfcDuctSegment")) == 1
    assert len(m.by_type("IfcDoor")) == 1 and len(m.by_type("IfcOpeningElement")) == 1
    ratings = [uel.get_pset(w, "Pset_WallCommon", "FireRating") for w in m.by_type("IfcWall")]
    assert ratings.count("60") == 2
    assert all(uel.get_material(w).Name == "Beton" for w in m.by_type("IfcWall"))
    refs = {r.Identification for r in m.by_type("IfcClassificationReference")}
    assert refs == {"21.12"}
    for e in m.by_type("IfcWall") + m.by_type("IfcSlab") + m.by_type("IfcDuctSegment"):
        assert e.Representation is not None


def test_2x3_model(ifc_2x3):
    m = ifcopenshell.open(ifc_2x3)
    assert m.schema == "IFC2X3" and len(m.by_type("IfcWall")) == 6
    assert (
        len(m.by_type("IfcSlab")) == 1 and len(m.by_type("IfcDoor")) == 1 and len(m.by_type("IfcOpeningElement")) == 1
    )
    assert len(m.by_type("IfcFlowSegment")) == 1  # IFC2X3 has no IfcDuctSegment
    assert not m.by_type("IfcClassification")


def test_georef_model(ifc_georef):
    m = ifcopenshell.open(ifc_georef)
    (conv,) = m.by_type("IfcMapConversion")
    assert (conv.Eastings, conv.Northings, conv.OrthogonalHeight) == (155000, 463000, 0)
    assert conv.TargetCRS.Name == "EPSG:28992"


def test_truncated_is_half(ifc_small, ifc_truncated):
    assert ifc_truncated.stat().st_size == ifc_small.stat().st_size // 2
    assert ifc_truncated.read_bytes() == ifc_small.read_bytes()[: ifc_truncated.stat().st_size]
