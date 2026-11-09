"""Splitting on the STEP index (converter/split.mjs): each product in one part, relations cut to the part."""

from collections import Counter, defaultdict
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import pytest
from test_clean import DUPLICATES, _rows, ids, references

from openbim_kern.converter import split_ifc, split_with_stats
from openbim_kern.index.properties import build_property_index, index_model

SPATIAL = ("IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey")


@pytest.fixture(scope="module")
def ifc_ports(tmp_path_factory):
    """IFC4: ducts with two nested ports each and a shared type with a material, on one storey."""
    api = ifcopenshell.api
    f = api.run("project.create_file", version="IFC4")
    project = api.run("root.create_entity", f, ifc_class="IfcProject", name="Poorten")
    api.run("unit.assign_unit", f, length={"is_metric": True, "raw": "METERS"})
    api.run("context.add_context", f, context_type="Model")
    site = api.run("root.create_entity", f, ifc_class="IfcSite", name="Terrein")
    building = api.run("root.create_entity", f, ifc_class="IfcBuilding", name="Gebouw")
    storey = api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="00")
    api.run("aggregate.assign_object", f, products=[site], relating_object=project)
    api.run("aggregate.assign_object", f, products=[building], relating_object=site)
    api.run("aggregate.assign_object", f, products=[storey], relating_object=building)
    duct_type = api.run("root.create_entity", f, ifc_class="IfcDuctSegmentType", name="Kanaal 400")
    material = api.run("material.add_material", f, name="Staal")
    api.run("material.assign_material", f, products=[duct_type], material=material)
    for i in range(12):
        duct = api.run("root.create_entity", f, ifc_class="IfcDuctSegment", name=f"Kanaal {i}")
        api.run("geometry.edit_object_placement", f, product=duct)
        api.run("spatial.assign_container", f, products=[duct], relating_structure=storey)
        api.run("type.assign_type", f, related_objects=[duct], relating_type=duct_type)
        for _ in range(2):
            api.run("system.add_port", f, element=duct)
    path = tmp_path_factory.mktemp("poorten") / "poorten.ifc"
    f.write(str(path))
    return path


def products(model) -> set[str]:
    """The products that go into exactly one part: all but the spatial structure (spaces do)."""
    spatial = ("IfcSpatialStructureElement",)
    return {p.GlobalId for p in model.by_type("IfcProduct") if not p.is_a(*spatial) or p.is_a("IfcSpace")}


def open_parts(source: Path, n: int, outdir: Path) -> list[ifcopenshell.file]:
    return [ifcopenshell.open(str(p)) for p in split_ifc(source, n, outdir)]


@pytest.mark.parametrize("fixture", ["ifc_small", "ifc_2x3", "dubbel", "ifc_ports"])
def test_every_product_in_exactly_one_part(fixture, request, tmp_path):
    source = DUPLICATES if fixture == "dubbel" else request.getfixturevalue(fixture)
    parts = open_parts(source, 3, tmp_path)
    assert len(parts) == 3
    counts = Counter(gid for part in parts for gid in products(part))
    assert counts == Counter(products(ifcopenshell.open(str(source))))
    spatial = {e.GlobalId for t in SPATIAL for e in ifcopenshell.open(str(source)).by_type(t)}
    assert all(spatial <= {e.GlobalId for t in SPATIAL for e in part.by_type(t)} for part in parts)


@pytest.mark.parametrize("fixture", ["ifc_small", "dubbel", "ifc_ports"])
def test_parts_have_no_dangling_references(fixture, request, tmp_path):
    source = DUPLICATES if fixture == "dubbel" else request.getfixturevalue(fixture)
    for part in split_ifc(source, 3, tmp_path):
        assert references(part) <= ids(part), part.name


def _related(model) -> dict[str, set[str]]:
    """Per relationship (by GlobalId) the GlobalIds of everything in its lists."""
    found = defaultdict(set)
    for rel in model.by_type("IfcRelationship"):
        for value in rel:
            if isinstance(value, tuple):
                found[rel.GlobalId].update(e.GlobalId for e in value if hasattr(e, "GlobalId"))
    return found


@pytest.mark.parametrize("fixture", ["ifc_small", "dubbel", "ifc_ports"])
def test_relationships_are_cut_to_the_part(fixture, request, tmp_path):
    source = DUPLICATES if fixture == "dubbel" else request.getfixturevalue(fixture)
    parts = open_parts(source, 3, tmp_path)
    union = defaultdict(set)
    for part in parts:
        mine = products(part)
        for rel in part.by_type("IfcRelContainedInSpatialStructure"):
            assert {e.GlobalId for e in rel.RelatedElements} <= mine
        for gid, related in _related(part).items():
            union[gid] |= related
    assert union == _related(ifcopenshell.open(str(source)))


@pytest.mark.parametrize("fixture", ["ifc_small", "ifc_2x3", "dubbel", "ifc_ports"])
def test_the_index_of_the_parts_is_that_of_the_model(fixture, request, tmp_path):
    """Elements, property sets, materials, classifications, types and storeys, as convert_model indexes the parts."""
    source = DUPLICATES if fixture == "dubbel" else request.getfixturevalue(fixture)
    build_property_index(source, tmp_path / "bron.sqlite")
    for part in open_parts(source, 3, tmp_path / "delen"):
        index_model(part, tmp_path / "delen.sqlite")
    assert _rows(tmp_path / "delen.sqlite") == _rows(tmp_path / "bron.sqlite")


def test_openings_fillings_and_ports_stay_with_their_element(ifc_small, ifc_ports, tmp_path):
    for part in open_parts(ifc_small, 4, tmp_path / "klein"):
        mine = products(part)
        for rel in part.by_type("IfcRelVoidsElement"):
            assert {rel.RelatingBuildingElement.GlobalId, rel.RelatedOpeningElement.GlobalId} <= mine
        for rel in part.by_type("IfcRelFillsElement"):
            assert {rel.RelatingOpeningElement.GlobalId, rel.RelatedBuildingElement.GlobalId} <= mine
    nested = 0
    for part in open_parts(ifc_ports, 4, tmp_path / "poorten"):
        for port in part.by_type("IfcDistributionPort"):
            (rel,) = port.Nests
            assert rel.RelatingObject.is_a("IfcDuctSegment")
            nested += 1
    assert nested == 24


def test_styles_and_layers_follow_the_geometry(tmp_path):
    source = ifcopenshell.open(str(DUPLICATES))

    def colours(model):
        return {
            w.GlobalId: sorted(
                s.Styles[0].Name
                for b in w.Representation.Representations
                for i in b.Items
                for s in model.get_inverse(i)
                if s.is_a("IfcStyledItem")
            )
            for w in model.by_type("IfcWall")
        }

    def layered(model):
        return {r.id() for layer in model.by_type("IfcPresentationLayerAssignment") for r in layer.AssignedItems}

    found, layers = {}, set()
    for part in open_parts(DUPLICATES, 5, tmp_path):
        found.update(colours(part))
        layers |= layered(part)
        assert len(part.by_type("IfcStyledItem")) == sum(len(c) for c in colours(part).values())
    assert found == colours(source)
    assert layers == layered(source)


def test_more_parts_than_products(tmp_path):
    parts = split_ifc(DUPLICATES, 20, tmp_path)
    assert len(parts) == 6  # five walls and a block, each a cluster of its own
    assert [p.name for p in parts] == [f"deel-{i}.ifc" for i in range(1, 7)]


def test_parts_are_balanced_by_size(enlarged, tmp_path):
    sizes = [p.stat().st_size for p in split_ifc(enlarged, 4, tmp_path)]
    assert max(sizes) < 1.1 * min(sizes)


def test_index_bytes_per_record(enlarged, tmp_path):
    report = split_with_stats(enlarged, 4, tmp_path).report
    assert 25 < report["index_bytes"] / report["records"] < 60
    assert report["index_bytes"] < enlarged.stat().st_size


def test_peak_memory(enlarged, tmp_path):
    """Peak memory above that for a tiny file: below the size of the file (the splitter of fragments took 6.4 times)."""
    base = split_with_stats(DUPLICATES, 2, tmp_path / "klein").peak_rss
    peak = split_with_stats(enlarged, 4, tmp_path / "groot").peak_rss
    size = enlarged.stat().st_size
    assert peak - base < 1.5 * size, (peak, base, size)
