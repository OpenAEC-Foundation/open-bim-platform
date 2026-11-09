"""Tool `omzetten`: IFC to fragments plus property index, spatial tree and summary.

The source is cleaned first (losslessly: duplicates merged, orphans left out) and large files are split; the cleaned
IFC and the parts are derived files in the work folder, the source stays as it was.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ifcopenshell
import psutil
from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator

from .. import CONVERTER_VERSION
from ..converter import clean_ifc, convert_to_frag, split_with_stats
from ..errors import KernError
from ..index.properties import count_elements, index_model
from ..index.spatial import merge_bounds, merge_spatial_trees, spatial_tree, summarize
from ..paths import data_dir
from ..progress import Progress, no_progress
from ..sources import Source, deliver, fetch_source
from .registry import tool

GB = 1_000_000_000
MAX_SOURCE_BYTES = 20 * GB
BASE_TARGETS = ("index.json", "eigenschappen.sqlite", "ruimtelijk.json")
_TARGET_NAME = re.compile(r"index\.json|eigenschappen\.sqlite|ruimtelijk\.json|model\.frag|deel-[1-9][0-9]*\.frag")
# Where the stages of one part end, as a share of its time (measured, see docs/metingen/2026-fase-0.md):
# fragments, opening the file, the property index; the summary and the spatial tree take the rest.
_FRAGMENTS_END = 0.30
_OPENED_END = 0.42
_INDEX_END = 0.92


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
def omzetten(invoer: OmzetVerzoek, progress: Progress = no_progress) -> OmzetUitkomst:
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
        sizes = {name: (work / "uit" / name).stat().st_size for name in result.files}
        sent = 0
        for name in result.files:
            deliver(work / "uit" / name, str(invoer.doelen[name]))
            sent += sizes[name]
            progress(0.9 + 0.1 * sent / max(1, sum(sizes.values())))
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
    seconds: dict[str, float] = field(default_factory=dict)  # per stage: opschonen, splitsen, fragments, index
    peaks: dict[str, int] = field(default_factory=dict)  # peak memory per converter stage
    cleaning: dict[str, Any] = field(default_factory=dict)  # what cleaning did, or why it was skipped


def convert_model(ifc: Path, work: Path, progress: Progress = no_progress) -> Converted:
    """Clean, split when large, convert to fragments and build the index, tree and summary: output in work / "uit".

    The one conversion path, for the tool and the CLI alike. When cleaning fails the source is converted as it is.
    """
    seconds = {"opschonen": 0.0, "splitsen": 0.0, "fragments": 0.0, "index": 0.0}
    peaks = {"opschonen": 0, "splitsen": 0, "fragments": 0}
    # Whether to split follows the size of the source, as the targets were planned for it.
    parts = planned_parts(ifc.stat().st_size)
    t0 = time.monotonic()
    source, cleaning = _clean(ifc, work / "opgeschoond.ifc")
    seconds["opschonen"] = time.monotonic() - t0
    peaks["opschonen"] = cleaning.pop("piek", 0)
    progress(0.07)
    if parts:
        split = split_with_stats(source, parts, work / "delen")
        seconds["splitsen"] = split.seconds
        peaks["splitsen"] = split.peak_rss
        inputs = split.parts
        names = [f"deel-{i}.frag" for i in range(1, len(inputs) + 1)]
    else:
        inputs, names = [source], ["model.frag"]
    progress(0.1)

    out = work / "uit"
    db = out / "eigenschappen.sqlite"
    delen: list[Deel] = []
    summaries: list[dict[str, Any]] = []
    trees: list[dict[str, Any]] = []
    for i, (part, name) in enumerate(zip(inputs, names, strict=True)):

        def in_part(share: float, part_number: int = i) -> None:
            progress(0.1 + 0.8 * (part_number + share) / len(inputs))

        t0 = time.monotonic()
        stats = convert_to_frag(part, out / name, lambda done: in_part(_FRAGMENTS_END * done))
        seconds["fragments"] += time.monotonic() - t0
        peaks["fragments"] = max(peaks["fragments"], stats.peak_rss)
        t0 = time.monotonic()
        model = _open(part)
        in_part(_OPENED_END)
        index_model(model, db, lambda done: in_part(_OPENED_END + (_INDEX_END - _OPENED_END) * done))
        summaries.append(summarize(model))
        trees.append(spatial_tree(model))
        del model  # one part in memory at a time
        seconds["index"] += time.monotonic() - t0
        delen.append(
            Deel(naam=name, bytes=stats.out_bytes, verdiepingen=list(summaries[-1]["aantallen_per_verdieping"]))
        )
        in_part(1.0)

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
        peak_rss=max(peaks.values()),
        seconds=seconds,
        peaks=peaks,
        cleaning=cleaning,
    )


def _clean(ifc: Path, out: Path) -> tuple[Path, dict[str, Any]]:
    """The cleaned copy of the source and what cleaning did; the source itself when cleaning failed."""
    try:
        stats = clean_ifc(ifc, out)
    except KernError as exc:
        return ifc, {"overgeslagen": exc.melding}
    return out, {
        "bytes_voor": stats.in_bytes,
        "bytes_na": stats.out_bytes,
        "regels_voor": stats.records_in,
        "regels_na": stats.records_out,
        "samengevoegd": stats.merged,
        "verweesd": stats.orphans,
        "per_klasse_samengevoegd": stats.report.get("merged_by_type", {}),
        "per_klasse_verweesd": stats.report.get("orphans_by_type", {}),
        "piek": stats.peak_rss,
    }


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
