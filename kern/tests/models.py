"""Synthetic IFC test models built with ifcopenshell.api (no customer data)."""

from __future__ import annotations

import math
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import numpy as np

STOREYS = [("00 begane grond", 0.0), ("01 eerste verdieping", 3.0)]
WALL_HEIGHT = 2.8
WALL_THICKNESS = 0.2


def _matrix(x: float, y: float, z: float, angle_deg: float = 0.0) -> np.ndarray:
    """4x4 placement: translation (metres) with a rotation about Z."""
    a = math.radians(angle_deg)
    m = np.eye(4)
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = math.cos(a), -math.sin(a), math.sin(a), math.cos(a)
    m[:3, 3] = (x, y, z)
    return m


def _build(schema: str, *, classify: bool, georef: bool) -> ifcopenshell.file:
    api = ifcopenshell.api
    f = ifcopenshell.api.run("project.create_file", version=schema)
    if schema == "IFC2X3":
        # IFC2X3 requires owner history on every rooted entity.
        person = f.create_entity("IfcPerson", FamilyName="Test")
        org = f.create_entity("IfcOrganization", Name="Test")
        user = f.create_entity("IfcPersonAndOrganization", ThePerson=person, TheOrganization=org)
        app = f.create_entity(
            "IfcApplication",
            ApplicationDeveloper=org,
            Version="1",
            ApplicationFullName="Test",
            ApplicationIdentifier="t",
        )
        ifcopenshell.api.owner.settings.get_user = lambda ifc: user
        ifcopenshell.api.owner.settings.get_application = lambda ifc: app
    project = api.run("root.create_entity", f, ifc_class="IfcProject", name="Testproject")
    api.run("unit.assign_unit", f, length={"is_metric": True, "raw": "METERS"})

    model_ctx = api.run("context.add_context", f, context_type="Model")
    body = api.run(
        "context.add_context",
        f,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_ctx,
    )

    site = api.run("root.create_entity", f, ifc_class="IfcSite", name="Terrein")
    building = api.run("root.create_entity", f, ifc_class="IfcBuilding", name="Gebouw")
    api.run("aggregate.assign_object", f, products=[site], relating_object=project)
    api.run("aggregate.assign_object", f, products=[building], relating_object=site)
    for obj in (site, building):
        api.run("geometry.edit_object_placement", f, product=obj)

    material = api.run("material.add_material", f, name="Beton")
    classification = None
    if classify:
        classification = api.run("classification.add_classification", f, classification="NL-SfB")

    def place(element, matrix):
        api.run("geometry.edit_object_placement", f, product=element, matrix=matrix)

    def box(element, length, thickness, height, matrix):
        rep = api.run(
            "geometry.add_wall_representation",
            f,
            context=body,
            length=length,
            height=height,
            thickness=thickness,
        )
        api.run("geometry.assign_representation", f, product=element, representation=rep)
        place(element, matrix)

    for index, (storey_name, elevation) in enumerate(STOREYS):
        storey = api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name=storey_name)
        storey.Elevation = elevation
        api.run("aggregate.assign_object", f, products=[storey], relating_object=building)
        place(storey, _matrix(0, 0, elevation))

        # Three walls with distinct placements; local X is the wall axis.
        layout = [
            ("Wand A", 10.0, _matrix(0, 0, elevation)),
            ("Wand B", 10.0, _matrix(0, 6, elevation)),
            ("Wand C", 6.0, _matrix(10, 0, elevation, 90)),
        ]
        walls = []
        for number, (name, length, matrix) in enumerate(layout):
            wall = api.run("root.create_entity", f, ifc_class="IfcWall", name=f"{name} {index}")
            box(wall, length, WALL_THICKNESS, WALL_HEIGHT, matrix)
            api.run("spatial.assign_container", f, products=[wall], relating_structure=storey)
            api.run("material.assign_material", f, products=[wall], material=material)
            if number == 0:
                pset = api.run("pset.add_pset", f, product=wall, name="Pset_WallCommon")
                api.run("pset.edit_pset", f, pset=pset, properties={"FireRating": "60"})
            if classification is not None:
                api.run(
                    "classification.add_reference",
                    f,
                    products=[wall],
                    identification="21.12",
                    name="Buitenwanden",
                    classification=classification,
                )
            walls.append(wall)

        if index == 0:
            # Door in a real void: opening element cuts wall A, the door fills it.
            opening = api.run("root.create_entity", f, ifc_class="IfcOpeningElement", name="Opening deur")
            box(opening, 1.0, WALL_THICKNESS + 0.2, 2.1, _matrix(4.0, -0.1, elevation))
            api.run("feature.add_feature", f, feature=opening, element=walls[0])
            door = api.run("root.create_entity", f, ifc_class="IfcDoor", name="Deur")
            door.OverallWidth, door.OverallHeight = 1.0, 2.1
            box(door, 1.0, WALL_THICKNESS, 2.1, _matrix(4.0, 0.0, elevation))
            api.run("spatial.assign_container", f, products=[door], relating_structure=storey)
            api.run("feature.add_filling", f, opening=opening, element=door)

            # Duct runs along global Y from y=5 to y=7 and crosses wall B (y 6.0..6.2).
            duct = api.run(
                "root.create_entity",
                f,
                ifc_class="IfcDuctSegment" if schema != "IFC2X3" else "IfcFlowSegment",
                name="Kanaal",
            )
            box(duct, 2.0, 0.4, 0.4, _matrix(5.0, 5.0, elevation + 2.0, 90))
            api.run("spatial.assign_container", f, products=[duct], relating_structure=storey)

            slab = api.run("root.create_entity", f, ifc_class="IfcSlab", name="Vloer")
            box(slab, 10.0, 6.0, 0.2, _matrix(0, 0, elevation - 0.2))
            api.run("spatial.assign_container", f, products=[slab], relating_structure=storey)

    if georef:
        api.run("georeference.add_georeferencing", f, ifc_class="IfcMapConversion")
        api.run(
            "georeference.edit_georeferencing",
            f,
            projected_crs={"Name": "EPSG:28992"},
            coordinate_operation={"Eastings": 155000.0, "Northings": 463000.0, "OrthogonalHeight": 0.0},
        )
    return f


def _write(f: ifcopenshell.file, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    f.write(str(path))
    return path


def ifc_small(path: Path) -> Path:
    """IFC4 model: 2 storeys, 6 walls, a door in an opening, a slab and a duct through a wall."""
    return _write(_build("IFC4", classify=True, georef=False), path)


def ifc_2x3(path: Path) -> Path:
    """Same content as `ifc_small` in IFC2X3, without classification."""
    return _write(_build("IFC2X3", classify=False, georef=False), path)


def ifc_georef(path: Path) -> Path:
    """`ifc_small` plus an IfcMapConversion to EPSG:28992."""
    return _write(_build("IFC4", classify=True, georef=True), path)


def ifc_clash_context(path: Path) -> Path:
    """IFC4 model with one pair for every classification rule of a clash round (all on the ground floor).

    Each group sits in its own strip along Y, so the groups do not touch each other:
    - y 0: a load-bearing wall with an opening and a door in it, and a duct crossing the wall 200 mm (in the space
      "Gang 1");
    - y 3: an assembly of two overlapping members;
    - y 6: two walls joined by a path connection, overlapping 100 mm, and a virtual element across one of them;
    - y 12: two pipes in one distribution system, overlapping 30 mm;
    - y 15: a beam 30 mm into a column;
    - y 18: a slab with a duct 2 mm into it;
    - y 25: two walls exactly on top of each other (duplicates).
    There is a grid with axes A, B and 1, 2.
    """
    api = ifcopenshell.api
    f = api.run("project.create_file", version="IFC4")
    project = api.run("root.create_entity", f, ifc_class="IfcProject", name="Testproject")
    api.run("unit.assign_unit", f, length={"is_metric": True, "raw": "METERS"})
    model_ctx = api.run("context.add_context", f, context_type="Model")
    body = api.run(
        "context.add_context",
        f,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_ctx,
    )
    site = api.run("root.create_entity", f, ifc_class="IfcSite", name="Terrein")
    building = api.run("root.create_entity", f, ifc_class="IfcBuilding", name="Gebouw")
    api.run("aggregate.assign_object", f, products=[site], relating_object=project)
    api.run("aggregate.assign_object", f, products=[building], relating_object=site)
    for obj in (site, building):
        api.run("geometry.edit_object_placement", f, product=obj)
    storey = api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name=STOREYS[0][0])
    storey.Elevation = 0.0
    api.run("aggregate.assign_object", f, products=[storey], relating_object=building)
    api.run("geometry.edit_object_placement", f, product=storey)

    def make(ifc_class, name, x, y, z, length, thickness, height, *, angle=0.0, container=True):
        """A box element whose local X runs along `length`, placed at (x, y, z)."""
        element = api.run("root.create_entity", f, ifc_class=ifc_class, name=name)
        rep = api.run(
            "geometry.add_wall_representation", f, context=body, length=length, height=height, thickness=thickness
        )
        api.run("geometry.assign_representation", f, product=element, representation=rep)
        api.run("geometry.edit_object_placement", f, product=element, matrix=_matrix(x, y, z, angle))
        if container:
            api.run("spatial.assign_container", f, products=[element], relating_structure=storey)
        return element

    # y 0: dragende wand met opening en deur, en een kanaal er 200 mm doorheen.
    bearing = make("IfcWall", "Dragende wand", 0.0, 0.0, 0.0, 5.0, WALL_THICKNESS, WALL_HEIGHT)
    pset = api.run("pset.add_pset", f, product=bearing, name="Pset_WallCommon")
    api.run("pset.edit_pset", f, pset=pset, properties={"LoadBearing": True})
    opening = make("IfcOpeningElement", "Opening deur", 2.0, -0.1, 0.0, 1.0, WALL_THICKNESS + 0.2, 2.1, container=False)
    api.run("feature.add_feature", f, feature=opening, element=bearing)
    door = make("IfcDoor", "Deur", 2.0, 0.0, 0.0, 1.0, WALL_THICKNESS, 2.1)
    api.run("feature.add_filling", f, opening=opening, element=door)
    # Along global Y from y=-0.5 to 0.5; local Y of the box then runs along -X, so x ends up at 4.3..4.0.
    make("IfcDuctSegment", "Kanaal", 4.3, -0.5, 1.0, 1.0, 0.3, 0.3, angle=90.0)
    space = make("IfcSpace", "Gang", 3.5, -1.0, 0.0, 1.5, 2.0, 3.0, container=False)
    space.LongName = "Gang 1"
    api.run("aggregate.assign_object", f, products=[space], relating_object=storey)

    # y 3: samenstel van twee overlappende delen.
    assembly = api.run("root.create_entity", f, ifc_class="IfcElementAssembly", name="Samenstel")
    api.run("spatial.assign_container", f, products=[assembly], relating_structure=storey)
    parts = [
        make("IfcMember", "Deel 1", 0.0, 3.0, 1.0, 2.0, 0.1, 0.1, container=False),
        make("IfcMember", "Deel 2", 1.9, 3.05, 1.05, 2.0, 0.1, 0.1, container=False),
    ]
    api.run("aggregate.assign_object", f, products=parts, relating_object=assembly)

    # y 6: twee verbonden wanden die 100 mm overlappen, en een virtueel element dwars door de eerste.
    first = make("IfcWall", "Wand 1", 0.0, 6.0, 0.0, 3.0, WALL_THICKNESS, WALL_HEIGHT)
    second = make("IfcWall", "Wand 2", 3.1, 6.05, 0.1, 3.0, WALL_THICKNESS, WALL_HEIGHT, angle=90.0)
    f.create_entity(
        "IfcRelConnectsPathElements",
        GlobalId=ifcopenshell.guid.new(),
        RelatingElement=first,
        RelatedElement=second,
        RelatingConnectionType="ATEND",
        RelatedConnectionType="ATSTART",
        RelatingPriorities=[],
        RelatedPriorities=[],
    )
    make("IfcVirtualElement", "Virtueel", 1.0, 5.9, 0.0, 1.0, 0.4, 2.0)

    # y 12: twee leidingen in één systeem, 30 mm overlap.
    system = api.run("system.add_system", f, ifc_class="IfcDistributionSystem")
    system.Name = "Systeem 1"
    pipes = [
        make("IfcPipeSegment", "Leiding 1", 0.0, 12.0, 1.0, 2.0, 0.1, 0.1),
        make("IfcPipeSegment", "Leiding 2", 1.97, 12.05, 1.05, 2.0, 0.1, 0.1),
    ]
    api.run("system.assign_system", f, products=pipes, system=system)

    # y 15: een ligger die 30 mm in een kolom steekt.
    make("IfcColumn", "Kolom", 0.0, 15.0, 0.0, 0.3, 0.3, 3.0)
    make("IfcBeam", "Ligger", 0.27, 15.0, 2.5, 3.0, 0.3, 0.3)

    # y 18: een vloer met een kanaal dat er 2 mm in steekt.
    make("IfcSlab", "Vloer", 0.0, 18.0, -0.2, 4.0, 4.0, 0.2)
    make("IfcDuctSegment", "Kanaal bij vloer", 1.0, 19.0, -0.002, 2.0, 0.3, 0.3)

    # y 25: dubbel geplaatste wand.
    make("IfcWall", "Wand dubbel 1", 0.0, 25.0, 0.0, 4.0, WALL_THICKNESS, WALL_HEIGHT)
    make("IfcWall", "Wand dubbel 2", 0.0, 25.0, 0.0, 4.0, WALL_THICKNESS, WALL_HEIGHT)

    # Raster: assen A en B (langs Y), 1 en 2 (langs X).
    def axis(tag, start, end):
        points = [f.create_entity("IfcCartesianPoint", Coordinates=list(p)) for p in (start, end)]
        return f.create_entity(
            "IfcGridAxis", AxisTag=tag, AxisCurve=f.create_entity("IfcPolyline", Points=points), SameSense=True
        )

    grid = api.run("root.create_entity", f, ifc_class="IfcGrid", name="Raster")
    grid.UAxes = [axis("A", (0.0, -5.0), (0.0, 30.0)), axis("B", (5.0, -5.0), (5.0, 30.0))]
    grid.VAxes = [axis("1", (-5.0, 0.0), (10.0, 0.0)), axis("2", (-5.0, 10.0), (10.0, 10.0))]
    api.run("geometry.edit_object_placement", f, product=grid)
    api.run("spatial.assign_container", f, products=[grid], relating_structure=storey)
    return _write(f, path)


def ifc_truncated(path: Path, source: Path | None = None) -> Path:
    """The first half of the bytes of `ifc_small` (a corrupt file); builds one when no source is given."""
    path = Path(path)
    data = (source if source is not None else ifc_small(path.with_name("_full_for_truncation.ifc"))).read_bytes()
    if source is None:
        path.with_name("_full_for_truncation.ifc").unlink()
    path.write_bytes(data[: len(data) // 2])
    return path


def project_folder(root: Path) -> list[Path]:
    """A project folder with two models in discipline folders, with spaces and accents in the names."""
    root = Path(root)
    (root / "Constructie").mkdir(parents=True, exist_ok=True)
    (root / "Installaties").mkdir(parents=True, exist_ok=True)
    return [ifc_small(root / "Constructie" / "wand model.ifc"), ifc_2x3(root / "Installaties" / "kanaal één.ifc")]


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        sys.exit("usage: python -m tests.models <map>")
    for made in project_folder(Path(sys.argv[1])):
        print(made)
