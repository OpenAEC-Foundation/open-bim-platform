"""Tool `botsingen`: a round of clash checks between sets of model versions (openbim_kern.clash)."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from ..clash import ClashCheck, ClashModel, run_checks
from ..sources import Source, deliver, fetch_source
from .registry import tool

MAX_IFC_BYTES = 8 * 1024**3


def _no_progress(_: float) -> None:
    pass


class BotsingBron(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sleutel: str
    versie: str
    bron: Source
    klassen: list[str] | None = None


class BotsingControle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regel: str = ""
    set_a: list[BotsingBron]
    set_b: list[BotsingBron]
    soort: Literal["hard", "afstand", "dubbel"]
    tolerantie: float = Field(default=0.0, ge=0, le=1)
    ernst: Literal["klein", "groot", "kritiek"] | None = None
    alleen_tussen_modellen: bool = False


class BotsingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    controles: list[BotsingControle] = Field(min_length=1, max_length=30)
    doel: HttpUrl


class BotsingUit(BaseModel):
    aantal: int


@tool(
    "botsingen",
    "Voer een ronde controles uit op modelversies: per controle hard (dieper dan de tolerantie), afstand (dichterbij "
    "dan de tolerantie) of dubbel (twee gelijke elementen op elkaar); de lijst gaat als JSON naar het doel.",
    lang=True,
    rij="botsing",
)
def botsingen(invoer: BotsingIn, progress: Callable[[float], None] = _no_progress) -> BotsingUit:
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

        checks = [
            ClashCheck(
                regel=c.regel,
                set_a=models(c.set_a),
                set_b=models(c.set_b),
                soort=c.soort,
                tolerantie=c.tolerantie,
                ernst=c.ernst,
                alleen_tussen_modellen=c.alleen_tussen_modellen,
            )
            for c in invoer.controles
        ]
        found = run_checks(checks, progress)
        out = work / "botsingen.json"
        out.write_text(json.dumps([c.model_dump(mode="json") for c in found]), encoding="utf-8")
        deliver(out, str(invoer.doel))
        progress(1.0)
        return BotsingUit(aantal=len(found))
    finally:
        shutil.rmtree(work, ignore_errors=True)
