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
from dataclasses import dataclass
from pathlib import Path

import psutil

from openbim_kern.errors import KernError
from openbim_kern.processes import kill_tree, tree_rss

GB = 1_000_000_000
CONVERT_SCRIPT = Path(__file__).resolve().parents[2] / "converter" / "convert.mjs"
MAX_RETRIES = 2
RETRY_MARKER = "WebAssembly.Exception"
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
        peak_rss=run.peak_rss,
        attempts=run.attempts,
    )


def split_ifc(ifc: Path, parts: int, outdir: Path) -> list[Path]:
    """Split an IFC file into at most `parts` files `deel-1.ifc`, ... in outdir, each with the spatial structure.

    Empty groups are left out, so fewer files than `parts` can come back. On failure outdir gets no new files.
    """
    if parts < 1:
        raise ValueError("parts must be at least 1")
    outdir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=outdir, prefix=".splits-"))
    try:
        run = _run_converter(["split", str(ifc), str(parts), str(work)], ifc)
        names = _last_json(run.stdout, ifc).get("delen")
        if not isinstance(names, list) or not names:
            raise _failed(ifc, "de splitser leverde geen delen op")
        result = []
        for name in names:
            if not isinstance(name, str) or Path(name).name != name or not (work / name).is_file():
                raise _failed(ifc, f"de splitser gaf een ongeldig deel terug: {name!r}")
            result.append(outdir / name)
        for name, target in zip(names, result, strict=True):
            os.replace(work / name, target)
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _run_converter(args: list[str], ifc: Path) -> _Run:
    """Run the converter, retrying at most MAX_RETRIES times when it died on a WebAssembly exception."""
    size = ifc.stat().st_size
    memory_limit = _memory_limit(size)
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
        raise _failed(ifc, _last_line(stderr) or f"de omzetter stopte met exitcode {returncode}")


def _run_once(cmd: list[str], ifc: Path, memory_limit: int, time_limit: float) -> tuple[int, str, str, int]:
    """Run one converter process; returns (returncode, stdout, stderr, peak RSS of the process tree)."""
    # Output goes to files rather than pipes, so a process with a lot of output can never block on a full pipe.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
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
                    raise KernError(
                        "omzetten_te_veel_geheugen",
                        f"Het omzetten van {ifc.name} gebruikte meer dan {memory_limit} bytes geheugen en is gestopt.",
                        "Lever het model in kleinere delen aan of verhoog de geheugengrens van de rekenkern.",
                        status=413,
                    )
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


def _command() -> list[str]:
    """OPENBIM_OMZETTER_CMD as a JSON list or a shell-style string; default `node converter/convert.mjs`."""
    raw = os.environ.get("OPENBIM_OMZETTER_CMD", "").strip()
    if not raw:
        return [shutil.which("node") or "node", str(CONVERT_SCRIPT)]
    cmd = json.loads(raw) if raw.startswith("[") else shlex.split(raw)
    if not isinstance(cmd, list) or not cmd or not all(isinstance(part, str) for part in cmd):
        raise ValueError("OPENBIM_OMZETTER_CMD must be a non-empty command")
    return cmd


def _memory_limit(size: int) -> int:
    override = os.environ.get("OPENBIM_GEHEUGEN_GRENS_BYTES")
    return int(override) if override else 3 * size + GB


def _time_limit(size: int) -> float:
    override = os.environ.get("OPENBIM_TIJD_GRENS_S")
    return float(override) if override else max(300.0, 1800.0 * size / GB)


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:_MAX_DETAIL] if lines else ""


def _last_json(stdout: str, ifc: Path) -> dict:
    try:
        report = json.loads(_last_line(stdout) or "null")
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
