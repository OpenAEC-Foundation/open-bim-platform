"""Tool `eigenschappen`: read element properties from a prebuilt index database."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..errors import KernError
from ..index.properties import ElementProperties, read_properties
from ..sources import Source, fetch_source
from .registry import tool

MAX_INDEX_BYTES = 4 * 1024**3


class EigenschappenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: Source
    globalids: list[str] = Field(min_length=1, max_length=1000)


class EigenschappenUit(BaseModel):
    elementen: dict[str, ElementProperties]


def data_dir() -> Path:
    configured = os.environ.get("OPENBIM_KERN_DATA")
    return Path(configured) if configured else Path(tempfile.gettempdir()) / "openbim-kern"


def _cached_index(source: Source) -> Path:
    """Index file for the source, cached under the data dir by sha256 (fetched once)."""
    cache = data_dir() / "cache" / "index"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{source.sha256.lower()}.sqlite"
    if not target.is_file():
        work = Path(tempfile.mkdtemp(dir=cache, prefix="haal-"))
        try:
            os.replace(fetch_source(source, work, MAX_INDEX_BYTES), target)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return target


@tool("eigenschappen", "Geef de eigenschappen, hoeveelheden, materialen en classificaties van elementen uit een index.")
def eigenschappen(invoer: EigenschappenIn) -> EigenschappenUit:
    if invoer.index.sha256:
        db = _cached_index(invoer.index)
        try:
            return EigenschappenUit(elementen=read_properties(db, invoer.globalids))
        except KernError:
            db.unlink(missing_ok=True)  # never keep a cached file that is not a valid index
            raise
    work = Path(tempfile.mkdtemp(prefix="eigenschappen-"))
    try:
        db = fetch_source(invoer.index, work, MAX_INDEX_BYTES)
        return EigenschappenUit(elementen=read_properties(db, invoer.globalids))
    finally:
        shutil.rmtree(work, ignore_errors=True)
