"""Make a variant of an IFC model for tests and trials: keep or drop classes of elements, and give part of the elements
a new GlobalId (as some exporters do in a new version).

    python scripts/variant.py <in.ifc> <out.ifc> [--alleen IfcWall,IfcSlab] [--zonder IfcDuctSegment]
                              [--nieuwe-globalids 0.3] [--zaad 1]

`--alleen` and `--zonder` take IFC classes (subclasses count too); the spatial structure always stays. Which elements
get a new GlobalId is fixed by `--zaad`, so a trial can be repeated.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.root
import ifcopenshell.guid


def _classes(text: str | None) -> list[str] | None:
    return [c.strip() for c in text.split(",") if c.strip()] if text else None


def variant(
    source: Path,
    out: Path,
    alleen: list[str] | None = None,
    zonder: list[str] | None = None,
    nieuwe_globalids: float = 0.0,
    zaad: int = 1,
) -> Path:
    model = ifcopenshell.open(str(source))
    weg = [
        e.id()
        for e in model.by_type("IfcElement")
        if (alleen and not any(e.is_a(c) for c in alleen)) or any(e.is_a(c) for c in zonder or [])
    ]
    for id_ in weg:
        # Removing a wall also removes its openings: those are gone before their turn.
        try:
            element = model.by_id(id_)
        except RuntimeError:
            continue
        ifcopenshell.api.root.remove_product(model, product=element)
    if nieuwe_globalids > 0:
        kies = random.Random(zaad)
        elementen = sorted(model.by_type("IfcElement"), key=lambda e: e.GlobalId)
        for element in kies.sample(elementen, round(len(elementen) * min(nieuwe_globalids, 1.0))):
            element.GlobalId = ifcopenshell.guid.new()
    model.write(str(out))
    return out


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bron", type=Path)
    parser.add_argument("uit", type=Path)
    parser.add_argument("--alleen", help="komma-gescheiden IFC-klassen die blijven")
    parser.add_argument("--zonder", help="komma-gescheiden IFC-klassen die weg gaan")
    parser.add_argument("--nieuwe-globalids", type=float, default=0.0, help="deel van de elementen met nieuwe GlobalId")
    parser.add_argument("--zaad", type=int, default=1)
    args = parser.parse_args(argv)
    variant(args.bron, args.uit, _classes(args.alleen), _classes(args.zonder), args.nieuwe_globalids, args.zaad)


if __name__ == "__main__":
    main()
