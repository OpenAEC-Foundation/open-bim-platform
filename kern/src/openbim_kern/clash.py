"""Clash detection between sets of models with the IfcOpenShell geometry tree.

A `ClashScene` reads and triangulates every file once; a `ClashCheck` is then one question to it:
`hard`: elements that penetrate each other deeper than the tolerance; `afstand`: elements closer than the tolerance
(clearance); `dubbel`: two elements of one class on top of each other (same bounding box, compared directly). An
element never clashes with itself, and a pair is reported once, by the first check that finds it (`run_checks`).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as element_util
import numpy as np
from pydantic import BaseModel

from .index.properties import _storey

Vec3 = tuple[float, float, float]

# Two elements are duplicates when each side of their bounding boxes differs at most this much (metres).
DUPLICATE_BOX_M = 0.010
# Order of the checks: the first check that finds a pair keeps it.
SOORT_ORDER = {"dubbel": 0, "hard": 1, "afstand": 2}
# Shares of the progress: loading the files, then the checks.
LOAD_SHARE = 0.5
CHECK_SHARE = 0.4


def _no_progress(_: float) -> None:
    pass


class ClashModel(BaseModel):
    sleutel: str
    versie: str
    pad: Path
    klassen: list[str] | None = None


class ClashCheck(BaseModel):
    regel: str = ""
    set_a: list[ClashModel]
    set_b: list[ClashModel]
    soort: Literal["hard", "afstand", "dubbel"]
    tolerantie: float = 0.0
    ernst: Literal["klein", "groot", "kritiek"] | None = None
    alleen_tussen_modellen: bool = False


class ElementRef(BaseModel):
    sleutel: str
    versie: str
    globalid: str
    klasse: str | None = None
    naam: str | None = None
    verdieping: str | None = None


class Botsing(BaseModel):
    a: ElementRef
    b: ElementRef
    punt: tuple[float, float, float]
    afstand: float
    soort: str = "hard"
    regel: str = ""
    emmer: str = "beoordelen"
    emmer_reden: str | None = None
    ernst: str | None = None
    categorie: str | None = None
    raster: str | None = None
    ruimte: str | None = None


def _elements(model: ifcopenshell.file, klassen: list[str] | None) -> list[ifcopenshell.entity_instance]:
    elements = [
        e
        for e in model.by_type("IfcElement")
        if e.Representation and not e.is_a("IfcFeatureElementSubtraction") and not e.is_a("IfcVirtualElement")
    ]
    return [e for e in elements if any(e.is_a(k) for k in klassen)] if klassen else elements


def _storey_name(element: ifcopenshell.entity_instance) -> str | None:
    """Name of the storey of an element, or of the assembly it is a part of."""
    node: ifcopenshell.entity_instance | None = element
    while node is not None:
        storey = _storey(node)
        if storey is not None:
            return storey.Name
        node = element_util.get_aggregate(node)
    return None


def _same_box(a: tuple[Vec3, Vec3], b: tuple[Vec3, Vec3]) -> bool:
    return all(abs(p - q) <= DUPLICATE_BOX_M for corner in range(2) for p, q in zip(a[corner], b[corner], strict=True))


class ClashScene:
    """The geometry tree, the opened files and the bounding box of every triangulated element."""

    def __init__(self, paths: list[Path], progress: Callable[[float], None] = _no_progress) -> None:
        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)
        self.tree = ifcopenshell.geom.tree()
        self.files: dict[Path, ifcopenshell.file] = {}
        self.boxes: dict[str, tuple[Vec3, Vec3]] = {}
        unique = list(dict.fromkeys(paths))
        sizes = {p: max(1, p.stat().st_size) for p in unique}
        total, done = sum(sizes.values()), 0
        for path in unique:
            self.files[path] = model = ifcopenshell.open(str(path))
            iterator = ifcopenshell.geom.iterator(settings, model)
            if iterator.initialize():
                last = -1
                while True:
                    shape = iterator.get()
                    self.tree.add_element(shape)
                    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
                    if len(verts):
                        low, high = verts.min(axis=0), verts.max(axis=0)
                        self.boxes[shape.guid] = (tuple(float(v) for v in low), tuple(float(v) for v in high))
                    percent = int(iterator.progress())
                    if percent != last:
                        last = percent
                        progress(LOAD_SHARE * (done + sizes[path] * percent / 100) / total)
                    if not iterator.next():
                        break
            done += sizes[path]
            progress(LOAD_SHARE * done / total)

    def _side(
        self, models: list[ClashModel]
    ) -> tuple[list[ifcopenshell.entity_instance], dict[str, tuple[ifcopenshell.entity_instance, ClashModel]]]:
        elements, owners = [], {}
        for m in models:
            for e in _elements(self.files[m.pad], m.klassen):
                elements.append(e)
                owners[e.GlobalId] = (e, m)
        return elements, owners

    @staticmethod
    def _ref(entity: ifcopenshell.entity_instance, model: ClashModel) -> ElementRef:
        return ElementRef(
            sleutel=model.sleutel,
            versie=model.versie,
            globalid=entity.GlobalId,
            klasse=entity.is_a(),
            naam=entity.Name,
            verdieping=_storey_name(entity),
        )

    def _duplicates(
        self,
        check: ClashCheck,
        owners_a: dict[str, tuple[ifcopenshell.entity_instance, ClashModel]],
        owners_b: dict[str, tuple[ifcopenshell.entity_instance, ClashModel]],
    ) -> list[Botsing]:
        """Pairs of one class whose bounding boxes agree within DUPLICATE_BOX_M on every side.

        Exact copies have faces that coincide, which the intersection test of the tree does not report, so this
        compares the boxes directly: the boxes of set B go in a grid keyed by class and corner, and each element of
        set A looks in the neighbouring cells.
        """
        cell = 5 * DUPLICATE_BOX_M
        grid: dict[tuple, list[str]] = {}
        for gid, (entity, _) in owners_b.items():
            if gid in self.boxes:
                key = (entity.is_a(), *(math.floor(v / cell) for v in self.boxes[gid][0]))
                grid.setdefault(key, []).append(gid)
        found: list[Botsing] = []
        seen: set[frozenset[str]] = set()
        for a, (entity_a, model_a) in owners_a.items():
            if a not in self.boxes:
                continue
            low, high = self.boxes[a]
            cx, cy, cz = (math.floor(v / cell) for v in low)
            for dx, dy, dz in itertools.product((-1, 0, 1), repeat=3):
                for b in grid.get((entity_a.is_a(), cx + dx, cy + dy, cz + dz), ()):
                    pair = frozenset((a, b))
                    entity_b, model_b = owners_b[b]
                    if a == b or pair in seen or not _same_box(self.boxes[a], self.boxes[b]):
                        continue
                    if check.alleen_tussen_modellen and model_a.sleutel == model_b.sleutel:
                        continue
                    seen.add(pair)
                    centre = tuple(round((p + q) / 2, 4) for p, q in zip(low, high, strict=True))
                    depth = round(min(q - p for p, q in zip(low, high, strict=True)), 4)
                    found.append(
                        Botsing(
                            a=self._ref(entity_a, model_a),
                            b=self._ref(entity_b, model_b),
                            punt=centre,
                            afstand=depth,
                            soort="dubbel",
                            regel=check.regel,
                        )
                    )
        return found

    def check(self, check: ClashCheck) -> list[Botsing]:
        elements_a, owners_a = self._side(check.set_a)
        elements_b, owners_b = self._side(check.set_b)
        if not elements_a or not elements_b:
            return []
        if check.soort == "dubbel":
            return self._duplicates(check, owners_a, owners_b)
        if check.soort == "afstand":
            raw = self.tree.clash_clearance_many(elements_a, elements_b, clearance=check.tolerantie, check_all=False)
        else:
            raw = self.tree.clash_intersection_many(elements_a, elements_b, tolerance=check.tolerantie, check_all=True)
        found: list[Botsing] = []
        seen: set[frozenset[str]] = set()
        for clash in raw:
            a, b = clash.a.get_argument(0), clash.b.get_argument(0)
            # The tree may give the pair the other way round: a from set B and b from set A.
            if a not in owners_a or b not in owners_b:
                a, b = b, a
            if a not in owners_a or b not in owners_b:
                continue
            pair = frozenset((a, b))
            if a == b or pair in seen:
                continue
            (entity_a, model_a), (entity_b, model_b) = owners_a[a], owners_b[b]
            if check.alleen_tussen_modellen and model_a.sleutel == model_b.sleutel:
                continue
            seen.add(pair)
            midpoint = tuple(round((p + q) / 2, 4) for p, q in zip(clash.p1, clash.p2, strict=True))
            found.append(
                Botsing(
                    a=self._ref(entity_a, model_a),
                    b=self._ref(entity_b, model_b),
                    punt=midpoint,
                    afstand=round(float(clash.distance), 4),
                    soort=check.soort,
                    regel=check.regel,
                )
            )
        return found


def run_checks(checks: list[ClashCheck], progress: Callable[[float], None] = _no_progress) -> list[Botsing]:
    """Run the checks on one scene: files read once, `dubbel` first, then `hard`, then `afstand`; a pair once."""
    scene = ClashScene([m.pad for c in checks for m in (*c.set_a, *c.set_b)], progress)
    found: list[Botsing] = []
    seen: set[frozenset[str]] = set()
    ordered = sorted(checks, key=lambda c: SOORT_ORDER[c.soort])
    for number, check in enumerate(ordered, start=1):
        for clash in scene.check(check):
            pair = frozenset((clash.a.globalid, clash.b.globalid))
            if pair not in seen:
                seen.add(pair)
                found.append(clash)
        progress(LOAD_SHARE + CHECK_SHARE * number / len(ordered))
    return found


def find_clashes(
    set_a: list[ClashModel],
    set_b: list[ClashModel],
    soort: Literal["hard", "afstand", "dubbel"],
    tolerantie: float,
) -> list[Botsing]:
    check = ClashCheck(set_a=set_a, set_b=set_b, soort=soort, tolerantie=tolerantie)
    return ClashScene([m.pad for m in (*set_a, *set_b)]).check(check)
