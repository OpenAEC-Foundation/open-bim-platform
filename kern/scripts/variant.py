"""Make a variant of an IFC model for tests and trials: keep or drop classes of elements, and give part of the elements
a new GlobalId (as some exporters do in a new version).

    python scripts/variant.py <in.ifc> <out.ifc> [--alleen IfcWall,IfcSlab] [--zonder IfcDuctSegment]
                              [--zonder-naam "Wand B 0"] [--kopie IfcDuctSegment:0,0,3]
                              [--nieuwe-globalids 0.3] [--zaad 1]

`--alleen` and `--zonder` take IFC classes (subclasses count too); the spatial structure always stays. `--zonder-naam`
drops the elements with exactly that name. `--kopie` adds a copy of every element of a class, moved over x,y,z metres
(with a new GlobalId), so a model can get a second clash. Which elements get a new GlobalId is fixed by `--zaad`, so a
trial can be repeated.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.guid
import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np


def _classes(text: str | None) -> list[str] | None:
    return [c.strip() for c in text.split(",") if c.strip()] if text else None


def variant(
    source: Path,
    out: Path,
    alleen: list[str] | None = None,
    zonder: list[str] | None = None,
    zonder_naam: list[str] | None = None,
    kopie: tuple[str, tuple[float, float, float]] | None = None,
    nieuwe_globalids: float = 0.0,
    zaad: int = 1,
) -> Path:
    model = ifcopenshell.open(str(source))
    weg = [
        e.id()
        for e in model.by_type("IfcElement")
        if (alleen and not any(e.is_a(c) for c in alleen))
        or any(e.is_a(c) for c in zonder or [])
        or e.Name in (zonder_naam or [])
    ]
    for id_ in weg:
        # Removing a wall also removes its openings: those are gone before their turn.
        try:
            element = model.by_id(id_)
        except RuntimeError:
            continue
        ifcopenshell.api.root.remove_product(model, product=element)
    if kopie:
        klasse, (dx, dy, dz) = kopie
        for element in list(model.by_type(klasse)):
            nieuw = ifcopenshell.api.root.copy_class(model, product=element)
            if element.Representation is not None and nieuw.Representation is None:
                nieuw.Representation = ifcopenshell.util.element.copy_deep(
                    model, element.Representation, exclude_callback=lambda e: e.is_a("IfcGeometricRepresentationContext")
                )
            matrix = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
            matrix[:, 3] += np.array([dx, dy, dz, 0.0])
            ifcopenshell.api.geometry.edit_object_placement(model, product=nieuw, matrix=matrix, is_si=False)
    if nieuwe_globalids > 0:
        kies = random.Random(zaad)
        elementen = sorted(model.by_type("IfcElement"), key=lambda e: e.GlobalId)
        for element in kies.sample(elementen, round(len(elementen) * min(nieuwe_globalids, 1.0))):
            element.GlobalId = ifcopenshell.guid.new()
    model.write(str(out))
    return out


def _verschuiving(text: str | None) -> tuple[str, tuple[float, float, float]] | None:
    if not text:
        return None
    klasse, _, delen = text.partition(":")
    dx, dy, dz = (float(d) for d in delen.split(","))
    return klasse, (dx, dy, dz)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bron", type=Path)
    parser.add_argument("uit", type=Path)
    parser.add_argument("--alleen", help="komma-gescheiden IFC-klassen die blijven")
    parser.add_argument("--zonder", help="komma-gescheiden IFC-klassen die weg gaan")
    parser.add_argument("--zonder-naam", help="komma-gescheiden namen van elementen die weg gaan")
    parser.add_argument("--kopie", help="Klasse:dx,dy,dz: een kopie van elk element van de klasse, verschoven (meters)")
    parser.add_argument("--nieuwe-globalids", type=float, default=0.0, help="deel van de elementen met nieuwe GlobalId")
    parser.add_argument("--zaad", type=int, default=1)
    args = parser.parse_args(argv)
    variant(
        args.bron,
        args.uit,
        _classes(args.alleen),
        _classes(args.zonder),
        _classes(args.zonder_naam),
        _verschuiving(args.kopie),
        args.nieuwe_globalids,
        args.zaad,
    )


if __name__ == "__main__":
    main()
