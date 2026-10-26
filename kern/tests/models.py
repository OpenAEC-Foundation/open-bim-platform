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


def ifc_truncated(path: Path, source: Path | None = None) -> Path:
    """The first half of the bytes of `ifc_small` (a corrupt file); builds one when no source is given."""
    path = Path(path)
    data = (source if source is not None else ifc_small(path.with_name("_full_for_truncation.ifc"))).read_bytes()
    if source is None:
        path.with_name("_full_for_truncation.ifc").unlink()
    path.write_bytes(data[: len(data) // 2])
    return path
