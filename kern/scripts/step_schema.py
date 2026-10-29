"""Write the schema table of the converter (converter/schema.json) from the IFC schemas of IfcOpenShell.

    python scripts/step_schema.py [<uit.json>]

Cleaning an IFC merges identical records; that is only safe where the schema allows a record to be shared. Per
schema and per entity the table lists the attributes (by their index in the record) where that is not so:

- `single_owner`: an inverse attribute of the referenced entity allows at most one referrer through this attribute
  (IfcStyledItem.Item: a representation item has at most one style). A record referenced through such an attribute
  keeps its own identity.
- `unique`: the attribute is a SET, or a LIST OF UNIQUE: merging two records it refers to would put the same record
  in it twice.

web-ifc knows the inverse attributes but not their bounds, so the table comes from IfcOpenShell; the type lists of the
converter (elements, spatial structure, IfcRoot) still come from web-ifc.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ifcopenshell.ifcopenshell_wrapper as wrapper

SCHEMAS = ("IFC2X3", "IFC4", "IFC4X3", "IFC4X3_ADD2")
TABLE = Path(__file__).resolve().parents[1] / "converter" / "schema.json"
# LIST OF UNIQUE is not visible through the wrapper of IfcOpenShell; these are the lists of entities in the IFC schemas
# declared that way.
UNIQUE_LISTS = {"IfcPolyLoop": ("Polygon",), "IfcPath": ("EdgeList",)}


def _subtypes(entity: wrapper.entity) -> list[wrapper.entity]:
    found = [entity]
    for sub in entity.subtypes():
        found.extend(_subtypes(sub))
    return found


def _is_set(attribute: wrapper.attribute) -> bool:
    kind = attribute.type_of_attribute()
    while kind.as_named_type() is not None:  # a defined type such as IfcComplexNumber
        declared = kind.as_named_type().declared_type()
        if declared.as_type_declaration() is None:
            return False
        kind = declared.as_type_declaration().declared_type()
    aggregate = kind.as_aggregation_type()
    return aggregate is not None and aggregate.type_of_aggregation_string() == "set"


def schema_table(name: str) -> dict[str, dict[str, list[int]]]:
    schema = wrapper.schema_by_name(name)
    entities = [d for d in schema.declarations() if d.as_entity() is not None]
    single: dict[str, set[int]] = {}
    for entity in entities:
        supertype = entity.supertype()
        inherited = {i.name() for i in supertype.all_inverse_attributes()} if supertype else set()
        for inverse in entity.all_inverse_attributes():
            if inverse.name() in inherited:
                continue
            if inverse.type_of_aggregation_string() and inverse.bound2() != 1:
                continue
            referrer = inverse.entity_reference()
            index = referrer.attribute_index(inverse.attribute_reference())
            for sub in _subtypes(referrer):
                single.setdefault(sub.name().upper(), set()).add(index)
    unique: dict[str, set[int]] = {}
    for entity in entities:
        lists = {attr for ancestor in _ancestors(entity) for attr in UNIQUE_LISTS.get(ancestor, ())}
        for index, attribute in enumerate(entity.all_attributes()):
            if _is_set(attribute) or attribute.name() in lists:
                unique.setdefault(entity.name().upper(), set()).add(index)
    return {
        "single_owner": {k: sorted(v) for k, v in sorted(single.items())},
        "unique": {k: sorted(v) for k, v in sorted(unique.items())},
    }


def _ancestors(entity: wrapper.entity) -> list[str]:
    names = []
    while entity is not None:
        names.append(entity.name())
        entity = entity.supertype()
    return names


def table() -> dict:
    return {"schemas": {name: schema_table(name) for name in SCHEMAS}}


def render(data: dict) -> str:
    """The table as JSON with one entity per line, so a change in a schema reads well in a diff."""
    lines = ['{"schemas": {']
    for s, (name, parts) in enumerate(data["schemas"].items()):
        lines.append(f'  "{name}": {{')
        for p, (part, rows) in enumerate(parts.items()):
            lines.append(f'    "{part}": {{')
            items = list(rows.items())
            for i, (entity, indices) in enumerate(items):
                comma = "," if i < len(items) - 1 else ""
                lines.append(f'      "{entity}": {json.dumps(indices)}{comma}')
            lines.append("    }" + ("," if p < len(parts) - 1 else ""))
        lines.append("  }" + ("," if s < len(data["schemas"]) - 1 else ""))
    lines.append("}}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("uit", type=Path, nargs="?", default=TABLE, help="het JSON-bestand (standaard de omzetter)")
    args = parser.parse_args(argv)
    args.uit.write_text(render(table()), encoding="utf-8", newline="\n")
    print(args.uit)


if __name__ == "__main__":
    main()
