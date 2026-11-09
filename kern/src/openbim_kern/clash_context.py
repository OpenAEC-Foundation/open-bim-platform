"""Where a clash sits and what it is: the bucket (`emmer`), the severity, the category, the grid cell and the room.

`classify` is pure and explains itself: every rule has a code in `emmer_reden`. `ModelContext` answers the questions
that classification and place need from one opened model: relations between two elements, systems, families, names,
storeys, the grid and the spaces. Everything here is best effort: the callers treat an error as an empty answer.
"""

from __future__ import annotations

import logging
import math
from typing import NamedTuple

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as element_util
import ifcopenshell.util.placement
import ifcopenshell.util.system
import ifcopenshell.util.unit
import numpy as np

from .index.properties import storey_of

LOG = logging.getLogger(__name__)

# Depth (metres) under which a hard clash is only a touch.
DEPTH_CONTACT_M = 0.005
# From this depth a hard clash is "groot" or "kritiek", under it "klein".
DEPTH_SEVERE_M = 0.02
# Under this depth an installation in one system, or two structural elements, form a joint.
DEPTH_JOINT_M = 0.05

STRUCTURAL_CLASSES = ("IfcBeam", "IfcColumn", "IfcFooting", "IfcPile", "IfcMember", "IfcSlab")


class Indeling(NamedTuple):
    emmer: str
    emmer_reden: str | None
    ernst: str
    categorie: str


def classify(
    soort: str,
    afstand: float,
    relatie: str | None,
    zelfde_systeem: bool,
    familie_a: str,
    familie_b: str,
    vaste_ernst: str | None,
) -> Indeling:
    """Bucket, reason, severity and category of one clash. The first rule that fits wins.

    For `dubbel` the `afstand` is a box dimension, not a depth, so no depth rule applies to it.
    """
    depth = abs(afstand)
    categorie = " × ".join(sorted((familie_a, familie_b)))
    emmer, reden = "beoordelen", None
    if soort != "dubbel":
        if relatie in ("vulling", "samenstel", "verbonden"):
            emmer, reden = "aangrenzend", relatie
        elif familie_a == familie_b == "installaties" and zelfde_systeem and depth < DEPTH_JOINT_M:
            emmer, reden = "aangrenzend", "zelfde_systeem"
        elif soort == "hard" and familie_a == familie_b == "constructie" and depth < DEPTH_JOINT_M:
            emmer, reden = "aangrenzend", "aansluiting"
        elif soort == "hard" and depth < DEPTH_CONTACT_M:
            emmer, reden = "contact", "contact"
    if emmer != "beoordelen":
        ernst = "klein"
    elif vaste_ernst:
        ernst = vaste_ernst
    elif soort == "dubbel":
        ernst = "groot"
    elif soort == "afstand":
        ernst = "klein"
    elif depth >= DEPTH_SEVERE_M:
        ernst = "kritiek" if {familie_a, familie_b} == {"constructie", "installaties"} else "groot"
    else:
        ernst = "klein"
    return Indeling(emmer, reden, ernst, categorie)


class ModelContext:
    """Questions about the elements, the grid and the spaces of one opened model."""

    def __init__(self, model: ifcopenshell.file, settings) -> None:
        self.model = model
        self.settings = settings
        self._axes: tuple[list, list] | None = None
        self._spaces: list[tuple[float, str, np.ndarray, np.ndarray]] | None = None

    # Elements

    def naam(self, gid: str) -> str | None:
        return self.model.by_guid(gid).Name

    def verdieping(self, gid: str) -> str | None:
        """Name of the storey of an element, as in the property index; a part of an assembly gets the assembly's."""
        storey = storey_of(self.model.by_guid(gid))
        return storey.Name if storey is not None else None

    def familie(self, gid: str) -> str:
        element = self.model.by_guid(gid)
        if element.is_a("IfcDistributionElement"):
            return "installaties"
        if any(element.is_a(c) for c in STRUCTURAL_CLASSES):
            return "constructie"
        if element.is_a("IfcWall") and element_util.get_pset(element, "Pset_WallCommon", "LoadBearing") is True:
            return "constructie"
        return "afwerking"

    def zelfde_systeem(self, gid_a: str, gid_b: str) -> bool:
        systems_a = {s.id() for s in ifcopenshell.util.system.get_element_systems(self.model.by_guid(gid_a))}
        return bool(
            systems_a & {s.id() for s in ifcopenshell.util.system.get_element_systems(self.model.by_guid(gid_b))}
        )

    def relatie(self, gid_a: str, gid_b: str) -> str | None:
        a, b = self.model.by_guid(gid_a), self.model.by_guid(gid_b)
        if self._fills(a, b) or self._fills(b, a):
            return "vulling"
        if self._aggregated(a, b):
            return "samenstel"
        if self._connected(a, b):
            return "verbonden"
        return None

    @staticmethod
    def _fills(filling, host) -> bool:
        """`filling` fills an opening that voids `host`."""
        for fills in getattr(filling, "FillsVoids", ()) or ():
            opening = fills.RelatingOpeningElement
            if any(v.RelatingBuildingElement == host for v in getattr(opening, "VoidsElements", ()) or ()):
                return True
        return False

    @staticmethod
    def _ancestors(element) -> list:
        chain = []
        node = element_util.get_aggregate(element)
        while node is not None and node not in chain:
            chain.append(node)
            node = element_util.get_aggregate(node)
        return chain

    def _aggregated(self, a, b) -> bool:
        """Parent and child, or children of one parent."""
        up_a, up_b = self._ancestors(a), self._ancestors(b)
        return b in up_a or a in up_b or bool(up_a and up_b and up_a[0] == up_b[0])

    @staticmethod
    def _connected(a, b) -> bool:
        for rel in (*(getattr(a, "ConnectedTo", ()) or ()), *(getattr(a, "ConnectedFrom", ()) or ())):
            if b in (rel.RelatingElement, rel.RelatedElement):
                return True
        return False

    # Place

    def raster(self, punt: tuple[float, float, float]) -> str | None:
        """Nearest grid axis per direction, as `C-4`; None without a grid."""
        if self._axes is None:
            try:
                self._axes = self._read_grid()
            except Exception as exc:
                LOG.warning("Reading the grid failed, clashes get no grid cell: %r", exc, exc_info=True)
                self._axes = ([], [])  # cache the failure: the reader must not run again for every clash
        tags = [t for t in (self._nearest(axes, punt) for axes in self._axes) if t]
        return "-".join(tags) if tags else None

    @staticmethod
    def _nearest(axes: list, punt) -> str | None:
        best, tag = math.inf, None
        for axis_tag, segments in axes:
            for start, end, infinite in segments:
                distance = _distance_xy(punt, start, end, infinite)
                if distance < best:
                    best, tag = distance, axis_tag
        return tag

    def _read_grid(self) -> tuple[list, list]:
        u_axes: list = []
        v_axes: list = []
        try:
            scale = float(ifcopenshell.util.unit.calculate_unit_scale(self.model))
        except Exception as exc:
            LOG.warning("No length unit for the grid, read in metres: %r", exc, exc_info=True)
            scale = 1.0
        angle = _angle_scale(self.model)
        for grid in self.model.by_type("IfcGrid"):
            try:
                matrix = ifcopenshell.util.placement.get_local_placement(grid.ObjectPlacement)
                for attribute, target in (("UAxes", u_axes), ("VAxes", v_axes)):
                    for axis in getattr(grid, attribute) or ():
                        segments = _curve_segments(axis.AxisCurve, matrix, scale, angle)
                        if segments:
                            target.append((axis.AxisTag, segments))
            except Exception as exc:
                LOG.warning("Grid %s skipped: %r", grid.Name, exc, exc_info=True)
                continue
        return u_axes, v_axes

    def ruimte(self, punt: tuple[float, float, float]) -> tuple[float, str] | None:
        """Volume and name of the smallest space whose bounding box holds the point."""
        if self._spaces is None:
            try:
                self._spaces = self._read_spaces()
            except Exception as exc:
                LOG.warning("Reading the spaces failed, clashes get no room: %r", exc, exc_info=True)
                self._spaces = []  # cache the failure: the geometry pass must not run again for every clash
        best: tuple[float, str] | None = None
        for volume, name, low, high in self._spaces:
            if (best is None or volume < best[0]) and np.all(low <= punt) and np.all(punt <= high):
                best = (volume, name)
        return best

    def _read_spaces(self) -> list[tuple[float, str, np.ndarray, np.ndarray]]:
        spaces = [s for s in self.model.by_type("IfcSpace") if s.Representation]
        found: list[tuple[float, str, np.ndarray, np.ndarray]] = []
        if not spaces:
            return found
        iterator = ifcopenshell.geom.iterator(self.settings, self.model, include=spaces)
        if not iterator.initialize():
            return found
        while True:
            shape = iterator.get()
            verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
            if len(verts):
                low, high = verts.min(axis=0), verts.max(axis=0)
                space = self.model.by_guid(shape.guid)
                found.append((float(np.prod(high - low)), space.LongName or space.Name or "", low, high))
            if not iterator.next():
                break
        return found


def _distance_xy(punt, start, end, infinite: bool) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.hypot(punt[0] - start[0], punt[1] - start[1])
    t = ((punt[0] - start[0]) * dx + (punt[1] - start[1]) * dy) / length2
    if not infinite:
        t = max(0.0, min(1.0, t))
    return math.hypot(punt[0] - (start[0] + t * dx), punt[1] - (start[1] + t * dy))


def _angle_scale(model: ifcopenshell.file) -> float:
    """Radians per plane angle unit of the model; degrees when the model declares no plane angle unit."""
    projects = model.by_type("IfcProject")
    units = projects[0].UnitsInContext if projects else None
    if units and any(getattr(u, "UnitType", None) == "PLANEANGLEUNIT" for u in units.Units):
        return float(ifcopenshell.util.unit.calculate_unit_scale(model, "PLANEANGLEUNIT"))
    return math.pi / 180


def _curve_segments(curve, matrix: np.ndarray, scale: float, angle: float) -> list[tuple[tuple, tuple, bool]]:
    """Straight pieces (start, end, infinite) of an axis curve in world metres; circular arcs are sampled.

    `scale` is metres per length unit of the model, `angle` radians per plane angle unit.
    """
    placed = matrix.copy()
    placed[:3, 3] *= scale

    def world(coords) -> tuple[float, float]:
        x, y = float(coords[0]) * scale, float(coords[1]) * scale
        z = float(coords[2]) * scale if len(coords) > 2 else 0.0
        out = placed @ np.array([x, y, z, 1.0])
        return (float(out[0]), float(out[1]))

    def pieces(points: list[tuple[float, float]], infinite: bool = False):
        return [(points[i], points[i + 1], infinite) for i in range(len(points) - 1)]

    if curve.is_a("IfcPolyline"):
        return pieces([world(p.Coordinates) for p in curve.Points])
    if curve.is_a("IfcIndexedPolyCurve"):
        return pieces([world(p) for p in curve.Points.CoordList])
    if curve.is_a("IfcLine"):
        start, direction = curve.Pnt.Coordinates, curve.Dir.Orientation.DirectionRatios
        end = [s + d for s, d in zip(start, direction, strict=False)]
        return [(world(start), world(end), True)]
    if curve.is_a("IfcTrimmedCurve"):
        if curve.BasisCurve.is_a("IfcCircle"):
            return pieces(_arc_points(curve, world, angle))
        return _curve_segments(curve.BasisCurve, matrix, scale, angle)
    return []


def _arc_points(trimmed, world, angle: float) -> list[tuple[float, float]]:
    """Sample a trimmed circle from Trim1 to Trim2; the trims are parameter values, in plane angle units of `angle`
    radians. Along the sense of the circle the arc runs anticlockwise, against it (SenseAgreement false) clockwise."""
    circle = trimmed.BasisCurve
    position = circle.Position
    centre_x, centre_y = (float(v) for v in position.Location.Coordinates[:2])
    ref = position.RefDirection.DirectionRatios if getattr(position, "RefDirection", None) else (1.0, 0.0)
    rotation = math.atan2(ref[1], ref[0])

    def parameter(trim) -> float | None:
        return next((float(i.wrappedValue) for i in trim if i.is_a("IfcParameterValue")), None)

    start, end = parameter(trimmed.Trim1), parameter(trimmed.Trim2)
    if start is None or end is None:
        return []
    start, end = start * angle, end * angle
    if trimmed.SenseAgreement is False:
        if end > start:
            end -= 2 * math.pi
    elif end < start:
        end += 2 * math.pi
    steps = 32
    angles = [start + (end - start) * i / steps + rotation for i in range(steps + 1)]
    return [world((centre_x + circle.Radius * math.cos(a), centre_y + circle.Radius * math.sin(a))) for a in angles]
