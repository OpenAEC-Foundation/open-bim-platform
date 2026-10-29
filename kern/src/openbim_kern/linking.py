"""Link the elements of a model version to those of the previous version (the identity over versions).

First on GlobalId; for what is left, a fallback on the identity table of the index (openbim_kern.index.identity):
class, type, name, storey and placement origin, then class, type and name (an element that moved). A fallback key
links only when it occurs exactly once in each whole version: identical elements are not guessed, and a removed
element is not linked to a new one that happens to share its name. The match rate is the share of the previous
version's elements that was found back.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from pydantic import BaseModel

from .errors import KernError


class Paar(BaseModel):
    van: str
    naar: str


class Koppeling(BaseModel):
    elementen_vorige: int
    op_globalid: int
    terugval: list[Paar]
    niet_gevonden: list[str]
    matchrate: float


def _identities(db: Path, rol: str) -> dict[str, tuple]:
    with closing(sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)) as con:
        try:
            rows = con.execute("SELECT globalid, ifc_class, type_name, name, storey_name, x, y, z FROM identiteit")
        except sqlite3.OperationalError as fout:
            # An index of a conversion from before the identity table: the version has to be converted again.
            raise KernError(
                f"{rol}_index_verouderd",
                f"De index van de {rol} versie heeft geen identiteitstabel.",
                f"Zet de {rol} versie opnieuw om en koppel daarna opnieuw.",
            ) from fout
        return {gid: rest for gid, *rest in rows}


def _match_unique(
    old: dict[str, tuple], new: dict[str, tuple], key, old_all: dict[str, tuple], new_all: dict[str, tuple]
) -> list[Paar]:
    """Pairs of remaining elements whose key occurs exactly once in each whole version."""
    old_keys = Counter(key(v) for v in old_all.values())
    new_keys = Counter(key(v) for v in new_all.values())
    new_by_key = {key(v): gid for gid, v in new.items() if new_keys[key(v)] == 1}
    return [
        Paar(van=gid, naar=new_by_key[key(v)])
        for gid, v in old.items()
        if old_keys[key(v)] == 1 and key(v) in new_by_key
    ]


def link_versions(old_db: Path, new_db: Path) -> Koppeling:
    old, new = _identities(old_db, "vorige"), _identities(new_db, "nieuwe")
    on_globalid = old.keys() & new.keys()
    old_left = {g: v for g, v in old.items() if g not in on_globalid}
    new_left = {g: v for g, v in new.items() if g not in on_globalid}
    fallback: list[Paar] = []
    for key in (lambda v: tuple(v), lambda v: tuple(v[:3])):
        pairs = _match_unique(old_left, new_left, key, old, new)
        fallback += pairs
        for pair in pairs:
            del old_left[pair.van]
            del new_left[pair.naar]
    found = len(on_globalid) + len(fallback)
    return Koppeling(
        elementen_vorige=len(old),
        op_globalid=len(on_globalid),
        terugval=fallback,
        niet_gevonden=sorted(old_left),
        matchrate=found / len(old) if old else 1.0,
    )
