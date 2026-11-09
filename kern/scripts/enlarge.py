"""Make a large, valid IFC file for measurements: the building elements of a model with their geometry, repeated.

    python scripts/enlarge.py <in.ifc> <factor> <out.ifc>

The source (a modest model) is analysed with IfcOpenShell; the output is written record by record, so a file of
several GB never sits in memory. Project, spatial structure, representation contexts, units and owner history are
shared by all copies; every element, everything it refers to and every relationship that names it is written `factor`
times, with shifted ids and new GlobalIds. The copies overlap in space: what matters here is the size of the file.
"""

from __future__ import annotations

import argparse
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid

SHARED_TYPES = (
    "IfcProject",
    "IfcSite",
    "IfcBuilding",
    "IfcBuildingStorey",
    "IfcRepresentationContext",
    "IfcUnitAssignment",
    "IfcOwnerHistory",
)
_RECORD = re.compile(r"#(\d+)\s*=\s*([A-Za-z0-9_]+)\s*\(")
_REF = re.compile(r"#(\d+)")
_GUIDS = uuid.UUID("6f1d3c4e-8a5b-4c2d-9e7f-0a1b2c3d4e5f")


def enlarge(source: Path, factor: int, out: Path) -> Path:
    if factor < 1:
        raise ValueError("factor must be at least 1")
    source, out = Path(source), Path(out)
    model = ifcopenshell.open(str(source))
    shared = _closure(model, [e for t in SHARED_TYPES for e in model.by_type(t)])
    roots = list(model.by_type("IfcElement"))
    for element in model.by_type("IfcElement"):
        roots.extend(r for r in model.get_inverse(element) if r.is_a("IfcRelationship"))
    copied = _closure(model, roots) - shared
    rooted = {i for i in copied if model.by_id(i).is_a("IfcRoot")}
    offset = max(_record_ids(source))
    del model

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="latin-1", newline="\n") as dst:
        for line in _header(source):
            dst.write(line + "\n")
        for record in _records(source):
            dst.write(record + "\n")
        for k in range(1, factor):
            for record in _records(source):
                match = _RECORD.match(record)
                if match and int(match.group(1)) in copied:
                    dst.write(_copy(record, k * offset, copied, int(match.group(1)) in rooted, k) + "\n")
        dst.write("ENDSEC;\nEND-ISO-10303-21;\n")
    return out


def _closure(model: ifcopenshell.file, roots: list) -> set[int]:
    """Ids of the roots and of everything they refer to, directly or not."""
    found: set[int] = set()
    for root in roots:
        if root.id() in found:
            continue
        found.update(e.id() for e in model.traverse(root) if e.id())
    return found


def _header(path: Path) -> Iterator[str]:
    with path.open("r", encoding="latin-1") as handle:
        for line in handle:
            yield line.rstrip("\r\n")
            if line.strip() == "DATA;":
                return


def _records(path: Path) -> Iterator[str]:
    """The records of the DATA section, one per item (a record can span several lines)."""
    with path.open("r", encoding="latin-1") as handle:
        in_data = False
        parts: list[str] = []
        for line in handle:
            text = line.strip()
            if not in_data:
                in_data = text == "DATA;"
                continue
            if not parts and text in ("", "ENDSEC;"):
                if text == "ENDSEC;":
                    return
                continue
            parts.append(text)
            if text.endswith(";"):
                yield "".join(parts)
                parts = []


def _record_ids(path: Path) -> Iterator[int]:
    for record in _records(path):
        match = _RECORD.match(record)
        if match:
            yield int(match.group(1))


def _copy(record: str, shift: int, copied: set[int], rooted: bool, k: int) -> str:
    """The record of copy k: ids of copied entities shifted, a new GlobalId for rooted ones; strings untouched."""
    # Splitting on quotes leaves the parts outside strings at even positions ('' inside a string keeps the parity).
    parts = record.split("'")
    for i in range(0, len(parts), 2):
        parts[i] = _REF.sub(
            lambda m: f"#{int(m.group(1)) + shift}" if int(m.group(1)) in copied else m.group(0), parts[i]
        )
    if rooted and len(parts) > 1:
        parts[1] = ifcopenshell.guid.compress(uuid.uuid5(_GUIDS, f"{parts[1]}/{k}").hex)
    return "'".join(parts)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="het bron-IFC")
    parser.add_argument("factor", type=int, help="hoe vaak de elementen voorkomen")
    parser.add_argument("out", type=Path, help="het nieuwe IFC")
    args = parser.parse_args(argv)
    out = enlarge(args.source, args.factor, args.out)
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
