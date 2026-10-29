"""Clash detection between two sets of models with IfcOpenShell's geometry tree.

`hard`: elements that penetrate each other deeper than the tolerance; `afstand`: elements closer than the tolerance
(clearance). Every file is read and triangulated once, also when it is in both sets; an element never clashes with
itself, and a pair is reported once.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import ifcopenshell
import ifcopenshell.geom
from pydantic import BaseModel


class ClashModel(BaseModel):
    sleutel: str
    versie: str
    pad: Path
    klassen: list[str] | None = None


class ElementRef(BaseModel):
    sleutel: str
    versie: str
    globalid: str


class Botsing(BaseModel):
    a: ElementRef
    b: ElementRef
    punt: tuple[float, float, float]
    afstand: float


def _elements(model: ifcopenshell.file, klassen: list[str] | None) -> list[ifcopenshell.entity_instance]:
    elements = [
        e for e in model.by_type("IfcElement") if e.Representation and not e.is_a("IfcFeatureElementSubtraction")
    ]
    return [e for e in elements if any(e.is_a(k) for k in klassen)] if klassen else elements


def find_clashes(
    set_a: list[ClashModel], set_b: list[ClashModel], soort: Literal["hard", "afstand"], tolerantie: float
) -> list[Botsing]:
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    tree = ifcopenshell.geom.tree()
    files: dict[Path, ifcopenshell.file] = {}
    for m in (*set_a, *set_b):
        if m.pad in files:
            continue
        files[m.pad] = model = ifcopenshell.open(str(m.pad))
        iterator = ifcopenshell.geom.iterator(settings, model)
        if iterator.initialize():
            while True:
                tree.add_element(iterator.get())
                if not iterator.next():
                    break

    def side(models: list[ClashModel]) -> tuple[list, dict[str, ElementRef]]:
        elements, refs = [], {}
        for m in models:
            for e in _elements(files[m.pad], m.klassen):
                elements.append(e)
                refs[e.GlobalId] = ElementRef(sleutel=m.sleutel, versie=m.versie, globalid=e.GlobalId)
        return elements, refs

    elements_a, refs_a = side(set_a)
    elements_b, refs_b = side(set_b)
    if not elements_a or not elements_b:
        return []
    if soort == "hard":
        raw = tree.clash_intersection_many(elements_a, elements_b, tolerance=tolerantie, check_all=True)
    else:
        raw = tree.clash_clearance_many(elements_a, elements_b, clearance=tolerantie, check_all=False)
    found: list[Botsing] = []
    seen: set[frozenset[str]] = set()
    for clash in raw:
        a, b = clash.a.get_argument(0), clash.b.get_argument(0)
        pair = frozenset((a, b))
        if a == b or pair in seen:
            continue
        seen.add(pair)
        midpoint = tuple(round((p + q) / 2, 4) for p, q in zip(clash.p1, clash.p2, strict=True))
        found.append(Botsing(a=refs_a[a], b=refs_b[b], punt=midpoint, afstand=round(float(clash.distance), 4)))
    return found
