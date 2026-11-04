"""Tool `botsingen`: clash detection between two sets of model versions (openbim_kern.clash)."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from ..clash import ClashModel, find_clashes
from ..sources import Source, deliver, fetch_source
from .registry import tool

MAX_IFC_BYTES = 8 * 1024**3


class BotsingBron(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sleutel: str
    versie: str
    bron: Source
    klassen: list[str] | None = None


class BotsingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_a: list[BotsingBron]
    set_b: list[BotsingBron]
    soort: Literal["hard", "afstand"]
    tolerantie: float = Field(ge=0, le=1)
    doel: HttpUrl


class BotsingUit(BaseModel):
    aantal: int


@tool(
    "botsingen",
    "Zoek botsingen tussen twee sets modelversies: hard (dieper dan de tolerantie) of afstand (dichterbij dan de "
    "tolerantie); de lijst gaat als JSON naar het doel.",
    lang=True,
    rij="botsing",
)
def botsingen(invoer: BotsingIn) -> BotsingUit:
    work = Path(tempfile.mkdtemp(prefix="botsingen-"))
    try:
        paths: dict[str, Path] = {}

        def models(bronnen: list[BotsingBron]) -> list[ClashModel]:
            result = []
            for b in bronnen:
                key = f"{b.sleutel}@{b.versie}"
                if key not in paths:
                    paths[key] = fetch_source(b.bron, work / str(len(paths)), MAX_IFC_BYTES)
                result.append(ClashModel(sleutel=b.sleutel, versie=b.versie, pad=paths[key], klassen=b.klassen))
            return result

        found = find_clashes(models(invoer.set_a), models(invoer.set_b), invoer.soort, invoer.tolerantie)
        out = work / "botsingen.json"
        out.write_text(json.dumps([c.model_dump(mode="json") for c in found]), encoding="utf-8")
        deliver(out, str(invoer.doel))
        return BotsingUit(aantal=len(found))
    finally:
        shutil.rmtree(work, ignore_errors=True)
