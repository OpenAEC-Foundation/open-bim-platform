"""Tool `koppelen`: link a new model version to the previous one (openbim_kern.linking)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..linking import Koppeling, link_versions
from ..sources import Source, fetch_source
from .eigenschappen import MAX_INDEX_BYTES, _cached_index
from .registry import tool


class KoppelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vorige: Source
    nieuwe: Source


@tool(
    "koppelen",
    "Koppel de elementen van een nieuwe modelversie aan de vorige: op GlobalId, met een terugval op klasse, type, "
    "naam, verdieping en plaatsing, en een matchrate.",
    lang=True,
)
def koppelen(invoer: KoppelIn) -> Koppeling:
    work = Path(tempfile.mkdtemp(prefix="koppelen-"))
    try:
        old, new = (
            _cached_index(source) if source.sha256 else fetch_source(source, work / name, MAX_INDEX_BYTES)
            for name, source in (("vorige", invoer.vorige), ("nieuwe", invoer.nieuwe))
        )
        return link_versions(old, new)
    finally:
        shutil.rmtree(work, ignore_errors=True)
