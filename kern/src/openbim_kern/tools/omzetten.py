"""Tool `omzetten`: IFC to fragments plus property index, spatial tree and summary; large files are split first."""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ifcopenshell
import psutil
from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator

from .. import CONVERTER_VERSION
from ..converter import convert_to_frag, split_ifc
from ..errors import KernError
from ..index.properties import count_elements, index_model
from ..index.spatial import merge_bounds, merge_spatial_trees, spatial_tree, summarize
from ..paths import data_dir
from ..sources import Source, deliver, fetch_source
from .registry import tool

GB = 1_000_000_000
MAX_SOURCE_BYTES = 20 * GB
BASE_TARGETS = ("index.json", "eigenschappen.sqlite", "ruimtelijk.json")
_TARGET_NAME = re.compile(r"index\.json|eigenschappen\.sqlite|ruimtelijk\.json|model\.frag|deel-[1-9][0-9]*\.frag")


class OmzetVerzoek(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bron: Source
    doelen: dict[str, HttpUrl]

    @field_validator("doelen")
    @classmethod
    def _known_names(cls, value: dict[str, HttpUrl]) -> dict[str, HttpUrl]:
        unknown = sorted(name for name in value if not _TARGET_NAME.fullmatch(name))
        if unknown:
            raise ValueError(f"onbekende doelen: {', '.join(unknown)}")
        return value


class Deel(BaseModel):
    naam: str
    bytes: int
    verdiepingen: list[str]


class OmzetUitkomst(BaseModel):
    omzetter: str
    delen: list[Deel]
    duur_s: float
    piek_geheugen: int


def _no_progress(_: float) -> None:
    pass


def planned_parts(size: int) -> int:
    """0 when the file is converted whole, otherwise the number of parts to split it into."""
    if size <= int(os.environ.get("OPENBIM_SPLITS_VANAF_BYTES", 1_500_000_000)):
        return 0
    return max(1, math.ceil(size / int(os.environ.get("OPENBIM_DEEL_BYTES", GB))))


@tool(
    "omzetten",
    "Zet een IFC-bestand om naar fragments voor de viewer, met eigenschappen-index, ruimtelijke boom en "
    "samenvatting; grote bestanden worden eerst gesplitst.",
    lang=True,
    rij="omzetten",
)
def omzetten(invoer: OmzetVerzoek, progress: Callable[[float], None] = _no_progress) -> OmzetUitkomst:
    t0 = time.monotonic()
    if invoer.bron.grootte is not None:
        _check_targets(invoer.doelen, planned_parts(invoer.bron.grootte))
    root = data_dir() / "werk"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix="omzetten-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        ifc = work / "bron.ifc"
        os.replace(fetch_source(invoer.bron, work / "bron", MAX_SOURCE_BYTES), ifc)
        _check_targets(invoer.doelen, planned_parts(ifc.stat().st_size))
        progress(0.05)
        result = convert_model(ifc, work, progress)
        for name in result.files:
            deliver(work / "uit" / name, str(invoer.doelen[name]))
        progress(1.0)
    return _outcome(result, t0)


def convert_to_folder(ifc: Path, folder: Path) -> OmzetUitkomst:
    """Convert a local IFC file into folder (the CLI); output files of an earlier run are replaced."""
    t0 = time.monotonic()
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder, prefix=".omzetten-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        result = convert_model(ifc, work)
        for name in result.files:
            os.replace(work / "uit" / name, folder / name)
    return _outcome(result, t0)


@dataclass
class Converted:
    delen: list[Deel]
    files: list[str]  # output files in delivery order: index.json, which marks the output as complete, last
    peak_rss: int  # of the converter processes
    seconds: dict[str, float] = field(default_factory=dict)  # per stage: splitsen, fragments, index


def convert_model(ifc: Path, work: Path, progress: Callable[[float], None] = _no_progress) -> Converted:
    """Split when large, convert to fragments and build the index, tree and summary: all output in work / "uit".

    The one conversion path, for the tool and the CLI alike.
    """
    seconds = {"splitsen": 0.0, "fragments": 0.0, "index": 0.0}
    parts = planned_parts(ifc.stat().st_size)
    if parts:
        t0 = time.monotonic()
        inputs = split_ifc(ifc, parts, work / "delen")
        seconds["splitsen"] = time.monotonic() - t0
        names = [f"deel-{i}.frag" for i in range(1, len(inputs) + 1)]
    else:
        inputs, names = [ifc], ["model.frag"]
    progress(0.1)

    out = work / "uit"
    db = out / "eigenschappen.sqlite"
    delen: list[Deel] = []
    summaries: list[dict[str, Any]] = []
    trees: list[dict[str, Any]] = []
    peak = 0
    for i, (part, name) in enumerate(zip(inputs, names, strict=True)):
        t0 = time.monotonic()
        stats = convert_to_frag(part, out / name)
        seconds["fragments"] += time.monotonic() - t0
        peak = max(peak, stats.peak_rss)
        t0 = time.monotonic()
        model = _open(part)
        index_model(model, db)
        summaries.append(summarize(model))
        trees.append(spatial_tree(model))
        del model  # one part in memory at a time
        seconds["index"] += time.monotonic() - t0
        delen.append(
            Deel(naam=name, bytes=stats.out_bytes, verdiepingen=list(summaries[-1]["aantallen_per_verdieping"]))
        )
        progress(0.1 + 0.8 * (i + 1) / len(inputs))

    index = {
        **summaries[0],
        "begrenzing": merge_bounds([s["begrenzing"] for s in summaries]),
        **count_elements(db),
        "omzetter": CONVERTER_VERSION,
        "delen": [d.model_dump() for d in delen],
    }
    _write_json(out / "ruimtelijk.json", merge_spatial_trees(trees))
    _write_json(out / "index.json", index)
    return Converted(
        delen=delen,
        files=[*names, "eigenschappen.sqlite", "ruimtelijk.json", "index.json"],
        peak_rss=peak,
        seconds=seconds,
    )


def _outcome(result: Converted, t0: float) -> OmzetUitkomst:
    return OmzetUitkomst(
        omzetter=CONVERTER_VERSION,
        delen=result.delen,
        duur_s=time.monotonic() - t0,
        piek_geheugen=max(result.peak_rss, own_peak_rss()),
    )


def _check_targets(doelen: dict[str, HttpUrl], parts: int) -> None:
    frag = "deel-1.frag" if parts else "model.frag"
    missing = [name for name in (*BASE_TARGETS, frag) if name not in doelen]
    if missing:
        raise KernError(
            "doel_ontbreekt",
            f"Er ontbreekt een doeladres voor: {', '.join(missing)}.",
            "Geef in doelen een schrijfadres mee voor elk uitvoerbestand.",
            status=422,
        )
    available = 0
    while f"deel-{available + 1}.frag" in doelen:
        available += 1
    if parts > available:
        raise KernError(
            "te_veel_delen",
            f"Het model wordt in {parts} delen gesplitst, maar er zijn doeladressen voor {available} delen.",
            f"Geef in doelen schrijfadressen mee voor deel-1.frag tot en met deel-{parts}.frag.",
            status=422,
        )


def _open(ifc: Path) -> ifcopenshell.file:
    try:
        return ifcopenshell.open(str(ifc))
    except Exception as exc:  # noqa: BLE001 - any read error of the file is reported the same way
        raise KernError(
            "omzetten_mislukt",
            f"Het IFC-bestand kon niet worden gelezen: {exc}.",
            "Controleer of het IFC-bestand volledig en geldig is, exporteer het zo nodig opnieuw en probeer opnieuw.",
            status=422,
        ) from exc


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def own_peak_rss() -> int:
    """Peak memory of this process (the property index runs in it)."""
    info = psutil.Process().memory_info()
    if hasattr(info, "peak_wset"):  # Windows
        return info.peak_wset
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024
