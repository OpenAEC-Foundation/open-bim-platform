"""Measure the conversion of the IFC models in a project folder (scripts/measure.py).

Each file is converted in its own process with the conversion of the tool `omzetten` (convert_model), so the peak
memory of IfcOpenShell is measured per file. The output lands in <map>/.afgeleid/ in the layout of the local server,
so `openbim-kern lokaal <map>` and the viewer can open the folder without converting again.
"""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import platform
import queue
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import psutil

from . import CONVERTER_VERSION
from .local.server import DERIVED, derived_rel, model_files
from .tools.omzetten import convert_model, own_peak_rss

# As in the viewer (viewer/src/model/budget.ts): estimated browser memory per fragments byte, and the budget.
BYTES_PER_FRAGMENTS_BYTE = 18
DEFAULT_BUDGET = 2 * 1024**3
MB = 1024**2
CHUNK_BYTES = 8 * MB


def measure(root: Path, log: Any = print) -> list[dict[str, Any]]:
    """Convert every model in the folder and return one row per file."""
    root = Path(root).resolve()
    context = multiprocessing.get_context("spawn")
    rows = []
    for ifc in model_files(root):
        sleutel = ifc.relative_to(root).as_posix()
        versie = _sha256(ifc)[:12]
        row: dict[str, Any] = {"bestand": sleutel, "versie": versie, "ifc_bytes": ifc.stat().st_size}
        (root / DERIVED).mkdir(exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=".meting-", dir=root / DERIVED))
        try:
            outcome = _run_child(context, ifc, work)
            if outcome["ok"]:
                target = root.joinpath(*PurePosixPath(derived_rel(sleutel, versie)).parts)
                target.mkdir(parents=True, exist_ok=True)
                for name in outcome["files"]:
                    os.replace(work / "uit" / name, target / name)
                row.update(
                    frag_bytes=sum(d["bytes"] for d in outcome["delen"]),
                    delen=len(outcome["delen"]),
                    seconden=outcome["seconden"],
                    fasen=outcome["fasen"],
                    piek_omzetter=outcome["piek_omzetter"],
                    piek_index=outcome["piek_index"],
                    sqlite_bytes=(target / "eigenschappen.sqlite").stat().st_size,
                )
            else:
                row["fout"] = outcome["fout"]
        finally:
            shutil.rmtree(work, ignore_errors=True)
        rows.append(row)
        log(_progress(row))
    return rows


def _run_child(context: Any, ifc: Path, work: Path) -> dict[str, Any]:
    results = context.Queue()
    process = context.Process(target=_measure_one, args=(str(ifc), str(work), results))
    process.start()
    try:
        while True:
            try:
                return results.get(timeout=1)
            except queue.Empty:
                if not process.is_alive():
                    return {"ok": False, "fout": f"het meetproces stopte (exitcode {process.exitcode})"}
    finally:
        process.join()


def _measure_one(ifc: str, work: str, results: Any) -> None:
    """Body of the measuring process."""
    t0 = time.monotonic()
    try:
        converted = convert_model(Path(ifc), Path(work))
        results.put(
            {
                "ok": True,
                "seconden": time.monotonic() - t0,
                "fasen": converted.seconds,
                "piek_omzetter": converted.peak_rss,
                "piek_index": own_peak_rss(),
                "delen": [d.model_dump() for d in converted.delen],
                "files": converted.files,
            }
        )
    except Exception as exc:  # noqa: BLE001 - every failure becomes a row in the report
        results.put({"ok": False, "fout": f"{type(exc).__name__}: {exc}"})


def browser_plan(rows: list[dict[str, Any]], budget: int = DEFAULT_BUDGET) -> tuple[int, int]:
    """(models loaded at start, models converted), by the viewer's rule.

    In order, the first model always, until one does not fit.
    """
    ready = [r for r in rows if "frag_bytes" in r]
    used = loaded = 0
    for row in ready:
        cost = BYTES_PER_FRAGMENTS_BYTE * row["frag_bytes"]
        if loaded and used + cost > budget:
            break
        used += cost
        loaded += 1
    return loaded, len(ready)


def render(rows: list[dict[str, Any]], root: Path) -> str:
    ok = [r for r in rows if "frag_bytes" in r]
    total_ifc = sum(r["ifc_bytes"] for r in rows)
    total_frag = sum(r["frag_bytes"] for r in ok)
    loaded, ready = browser_plan(rows)
    memory = psutil.virtual_memory().total
    lines = [
        "# Meting omzetten",
        "",
        f"- Map: `{root}` ({len(rows)} bestanden, {total_ifc / 1e9:.2f} GB IFC)",
        f"- Omzetter: `{CONVERTER_VERSION}`",
        f"- Machine: {platform.platform()}, {psutil.cpu_count(logical=False)} kernen, "
        f"{memory / 1024**3:.0f} GB geheugen",
        f"- Datum: {datetime.now().isoformat(timespec='minutes')}",
        "",
        "| bestand | MB IFC | MB .frag | MB index | s | piek omzetter (MB) | piek IfcOpenShell (MB) | delen "
        "| s splitsen | s fragments | s index |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        if "fout" in r:
            lines.append(f"| `{r['bestand']}` | {r['ifc_bytes'] / MB:.0f} | fout: {r['fout']} |||||||||")
            continue
        f = r["fasen"]
        lines.append(
            f"| `{r['bestand']}` | {r['ifc_bytes'] / MB:.0f} | {r['frag_bytes'] / MB:.1f} "
            f"| {r['sqlite_bytes'] / MB:.1f} "
            f"| {r['seconden']:.1f} | {r['piek_omzetter'] / MB:.0f} | {r['piek_index'] / MB:.0f} | {r['delen']} "
            f"| {f['splitsen']:.1f} | {f['fragments']:.1f} | {f['index']:.1f} |"
        )
    if ok:
        lines.append(
            f"| **Totaal** | {total_ifc / MB:.0f} | {total_frag / MB:.1f} "
            f"| {sum(r['sqlite_bytes'] for r in ok) / MB:.1f} | {sum(r['seconden'] for r in ok):.1f} "
            f"| {max(r['piek_omzetter'] for r in ok) / MB:.0f} (max) "
            f"| {max(r['piek_index'] for r in ok) / MB:.0f} (max) "
            f"| {sum(r['delen'] for r in ok)} | {sum(r['fasen']['splitsen'] for r in ok):.1f} "
            f"| {sum(r['fasen']['fragments'] for r in ok):.1f} | {sum(r['fasen']['index'] for r in ok):.1f} |"
        )
    lines += [
        "",
        f"Geschatte browserpost ({BYTES_PER_FRAGMENTS_BYTE} × .frag): "
        f"{BYTES_PER_FRAGMENTS_BYTE * total_frag / 1024**3:.2f} GB voor alle {ready} omgezette modellen. "
        f"Binnen het budget van {DEFAULT_BUDGET / 1024**3:.0f} GB laadt de viewer bij het openen "
        f"{loaded} van de {ready} "
        "modellen (in de volgorde van de map); de rest staat klaar om aan te zetten.",
    ]
    failed = [r for r in rows if "fout" in r]
    if failed:
        lines += ["", f"{len(failed)} bestand(en) konden niet worden omgezet; zie de tabel."]
    return "\n".join(lines) + "\n"


def _progress(row: dict[str, Any]) -> str:
    if "fout" in row:
        return f"{row['bestand']}: fout: {row['fout']}"
    return (
        f"{row['bestand']}: {row['ifc_bytes'] / MB:.0f} MB IFC -> {row['frag_bytes'] / MB:.1f} MB .frag "
        f"in {row['seconden']:.1f} s ({row['delen']} delen)"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
