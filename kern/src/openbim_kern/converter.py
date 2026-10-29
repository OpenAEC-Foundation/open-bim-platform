"""Run the Node converter (converter/convert.mjs) in a subprocess under a memory and time watchdog."""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

from openbim_kern.errors import KernError
from openbim_kern.processes import kill_tree, tree_rss

GB = 1_000_000_000
CONVERT_SCRIPT = Path(__file__).resolve().parents[2] / "converter" / "convert.mjs"
MAX_RETRIES = 2
# Memory per byte of IFC, on top of 1 GB: converting stays below 3. Cleaning and splitting keep a compact index of
# every record (~52 and ~38 bytes); on 1 GB they peaked at 0.9 and 0.75 times the size, more for files of short
# records (docs/metingen/2026-opschonen-en-splitsen.md).
CONVERT_MEMORY_FACTOR = 3
CLEAN_MEMORY_FACTOR = 2.5
SPLIT_MEMORY_FACTOR = 2
RETRY_MARKER = "WebAssembly.Exception"
# What Node writes when the V8 heap is full; it then aborts with a native stack trace instead of our message.
HEAP_FULL_MARKER = "JavaScript heap out of memory"
_POLL_S = 0.5
_MAX_DETAIL = 500


@dataclass
class ConvertStats:
    in_bytes: int
    out_bytes: int
    seconds: float
    peak_rss: int
    attempts: int


@dataclass
class CleanStats:
    in_bytes: int
    out_bytes: int
    records_in: int
    records_out: int
    merged: int  # duplicates left out
    orphans: int  # records nothing referred to
    seconds: float
    peak_rss: int
    report: dict[str, Any] = field(default_factory=dict)  # the cleaner's own report, counts per type included


@dataclass
class SplitStats:
    parts: list[Path]
    seconds: float
    peak_rss: int
    report: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Run:
    stdout: str
    peak_rss: int
    attempts: int


def convert_to_frag(ifc: Path, out: Path) -> ConvertStats:
    """Convert an IFC file to fragments at `out`.

    The output appears only on success; `seconds` covers all attempts.
    """
    t0 = time.monotonic()
    in_bytes = ifc.stat().st_size
    out.parent.mkdir(parents=True, exist_ok=True)
    # A fresh name the converter creates itself, so the output gets the usual file mode (mkstemp gives 0600).
    tmp = out.with_name(f".{out.stem}-{uuid.uuid4().hex}.part")
    try:
        run = _run_converter(["frag", str(ifc), str(tmp)], ifc)
        report = _last_json(run.stdout, ifc)
        out_bytes = tmp.stat().st_size
        if "out_bytes" not in report or out_bytes == 0:
            raise _failed(ifc, "de omzetter leverde geen fragments-bestand op")
        os.replace(tmp, out)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()
    return ConvertStats(
        in_bytes=in_bytes,
        out_bytes=out_bytes,
        seconds=time.monotonic() - t0,
        peak_rss=_peak(run, report),
        attempts=run.attempts,
    )


def clean_ifc(ifc: Path, out: Path) -> CleanStats:
    """Write a losslessly cleaned copy of an IFC file to `out`: identical records merged, orphaned ones left out.

    The source is not touched; the output appears only on success.
    """
    t0 = time.monotonic()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.stem}-{uuid.uuid4().hex}.part")
    try:
        run = _run_converter(["clean", str(ifc), str(tmp)], ifc, CLEAN_MEMORY_FACTOR)
        report = _last_json(run.stdout, ifc)
        keys = ("in_bytes", "records_in", "records_out", "merged", "orphans")
        if not all(isinstance(report.get(k), int) for k in keys) or not tmp.is_file():
            raise _failed(ifc, "het opschonen leverde geen IFC-bestand op")
        out_bytes = tmp.stat().st_size
        os.replace(tmp, out)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()
    return CleanStats(
        in_bytes=report["in_bytes"],
        out_bytes=out_bytes,
        records_in=report["records_in"],
        records_out=report["records_out"],
        merged=report["merged"],
        orphans=report["orphans"],
        seconds=time.monotonic() - t0,
        peak_rss=_peak(run, report),
        report=report,
    )


def split_ifc(ifc: Path, parts: int, outdir: Path) -> list[Path]:
    """Split an IFC file into at most `parts` files `deel-1.ifc`, ... in outdir, each with the spatial structure.

    Empty groups are left out, so fewer files than `parts` can come back. On failure outdir gets no new files.
    """
    return split_with_stats(ifc, parts, outdir).parts


def split_with_stats(ifc: Path, parts: int, outdir: Path) -> SplitStats:
    """split_ifc, with the time and the peak memory of the splitter."""
    if parts < 1:
        raise ValueError("parts must be at least 1")
    t0 = time.monotonic()
    outdir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=outdir, prefix=".splits-"))
    try:
        run = _run_converter(["split", str(ifc), str(parts), str(work)], ifc, SPLIT_MEMORY_FACTOR)
        report = _last_json(run.stdout, ifc)
        names = report.get("delen")
        if not isinstance(names, list) or not names:
            raise _failed(ifc, "de splitser leverde geen delen op")
        result = []
        for name in names:
            if not isinstance(name, str) or Path(name).name != name or not (work / name).is_file():
                raise _failed(ifc, f"de splitser gaf een ongeldig deel terug: {name!r}")
            result.append(outdir / name)
        for name, target in zip(names, result, strict=True):
            os.replace(work / name, target)
        return SplitStats(parts=result, seconds=time.monotonic() - t0, peak_rss=_peak(run, report), report=report)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _run_converter(args: list[str], ifc: Path, memory_factor: float = CONVERT_MEMORY_FACTOR) -> _Run:
    """Run the converter, retrying at most MAX_RETRIES times when it died on a WebAssembly exception."""
    size = ifc.stat().st_size
    memory_limit = _memory_limit(size, memory_factor)
    time_limit = _time_limit(size)
    peak = 0
    attempts = 0
    while True:
        attempts += 1
        returncode, stdout, stderr, rss = _run_once([*_command(), *args], ifc, memory_limit, time_limit)
        peak = max(peak, rss)
        if returncode == 0:
            return _Run(stdout=stdout, peak_rss=peak, attempts=attempts)
        if RETRY_MARKER in stderr and attempts <= MAX_RETRIES:
            continue
        if HEAP_FULL_MARKER in stderr:
            raise _too_much_memory(ifc, memory_limit)
        raise _failed(ifc, _last_line(stderr) or f"de omzetter stopte met exitcode {returncode}")


def _run_once(cmd: list[str], ifc: Path, memory_limit: int, time_limit: float) -> tuple[int, str, str, int]:
    """Run one converter process; returns (returncode, stdout, stderr, peak RSS of the process tree)."""
    # Output goes to files rather than pipes, so a process with a lot of output can never block on a full pipe.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=_environment(memory_limit)
            )
        except OSError as exc:
            raise KernError(
                "omzetten_mislukt",
                f"De omzetter kon niet worden gestart: {exc}.",
                "Controleer de installatie van Node en de omzetter (OPENBIM_OMZETTER_CMD).",
                status=500,
            ) from exc
        root = psutil.Process(proc.pid)
        deadline = time.monotonic() + time_limit
        peak = 0
        try:
            while True:
                rss = tree_rss(root)
                peak = max(peak, rss)
                if rss > memory_limit:
                    raise _too_much_memory(ifc, memory_limit)
                if time.monotonic() > deadline:
                    raise KernError(
                        "omzetten_tijd_op",
                        f"Het omzetten van {ifc.name} duurde langer dan {time_limit:.0f} s en is gestopt.",
                        "Lever het model in kleinere delen aan of verhoog de tijdslimiet van de rekenkern.",
                        status=413,
                    )
                try:
                    returncode = proc.wait(timeout=_POLL_S)
                    break
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if proc.poll() is None:
                kill_tree(root)
                proc.wait()
        out.seek(0)
        err.seek(0)
        return (
            returncode,
            out.read().decode("utf-8", errors="replace"),
            err.read().decode("utf-8", errors="replace"),
            peak,
        )


def _peak(run: _Run, report: dict) -> int:
    """The higher of the sampled peak and the one the converter reports for itself (exact, for the last attempt)."""
    reported = report.get("max_rss")
    return max(run.peak_rss, reported if isinstance(reported, int) else 0)


def _too_much_memory(ifc: Path, memory_limit: int) -> KernError:
    return KernError(
        "omzetten_te_veel_geheugen",
        f"Het omzetten van {ifc.name} gebruikte meer dan {memory_limit} bytes geheugen en is gestopt.",
        "Lever het model in kleinere delen aan of verhoog de geheugengrens van de rekenkern.",
        status=413,
    )


def _environment(memory_limit: int) -> dict[str, str]:
    """The converter's environment: the V8 heap may grow to the memory limit of the watchdog, which stays the guard.

    By itself Node stops at about 4 GB of heap, too little to split an IFC of a few GB.
    """
    env = dict(os.environ)
    heap = f"--max-old-space-size={memory_limit // 2**20}"
    env["NODE_OPTIONS"] = f"{env.get('NODE_OPTIONS', '')} {heap}".strip()
    return env


def _command() -> list[str]:
    """OPENBIM_OMZETTER_CMD as a JSON list or a shell-style string; default `node converter/convert.mjs`."""
    raw = os.environ.get("OPENBIM_OMZETTER_CMD", "").strip()
    if not raw:
        return [shutil.which("node") or "node", str(CONVERT_SCRIPT)]
    cmd = json.loads(raw) if raw.startswith("[") else shlex.split(raw)
    if not isinstance(cmd, list) or not cmd or not all(isinstance(part, str) for part in cmd):
        raise ValueError("OPENBIM_OMZETTER_CMD must be a non-empty command")
    return cmd


def _memory_limit(size: int, factor: float = CONVERT_MEMORY_FACTOR) -> int:
    override = os.environ.get("OPENBIM_GEHEUGEN_GRENS_BYTES")
    return int(override) if override else int(factor * size) + GB


def _time_limit(size: int) -> float:
    override = os.environ.get("OPENBIM_TIJD_GRENS_S")
    return float(override) if override else max(300.0, 1800.0 * size / GB)


def _last_line(text: str, limit: int | None = _MAX_DETAIL) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:limit] if lines else ""


def _last_json(stdout: str, ifc: Path) -> dict:
    try:
        report = json.loads(_last_line(stdout, None) or "null")
    except json.JSONDecodeError:
        report = None
    if not isinstance(report, dict):
        raise _failed(ifc, "de omzetter gaf geen geldig verslag terug")
    return report


def _failed(ifc: Path, detail: str) -> KernError:
    return KernError(
        "omzetten_mislukt",
        f"Het omzetten van {ifc.name} is mislukt: {detail.rstrip('.')}.",
        "Controleer of het IFC-bestand volledig en geldig is, exporteer het zo nodig opnieuw en probeer opnieuw.",
        status=422,
    )
