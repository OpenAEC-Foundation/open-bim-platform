"""Worker: runs queued jobs, each in its own process, and stops the processes of cancelled jobs."""

from __future__ import annotations

import contextlib
import inspect
import multiprocessing
import os
import threading
import time
from multiprocessing.context import SpawnContext, SpawnProcess
from pathlib import Path
from typing import Any

import psutil

from ..errors import KernError
from ..processes import kill_tree
from ..tools import botsingen as _botsingen  # noqa: F401  (registers the tool)
from ..tools import eigenschappen as _eigenschappen  # noqa: F401  (registers the tool)
from ..tools import koppelen as _koppelen  # noqa: F401  (registers the tool)
from ..tools import omzetten as _omzetten  # noqa: F401  (registers the tool)
from ..tools.registry import PROGRESS_PARAM, REGISTRY, ToolSpec
from .store import Job, JobStore

POLL_S = 0.2


def queues_from_env() -> dict[str, int]:
    """Concurrent jobs per queue: OPENBIM_RIJ_OMZETTEN (default 1), OPENBIM_RIJ_LICHT (default 4) and
    OPENBIM_RIJ_BOTSING (default 1)."""
    return {
        "omzetten": int(os.environ.get("OPENBIM_RIJ_OMZETTEN", 1)),
        "licht": int(os.environ.get("OPENBIM_RIJ_LICHT", 4)),
        "botsing": int(os.environ.get("OPENBIM_RIJ_BOTSING", 1)),
    }


def run_worker(
    store: JobStore,
    queues: dict[str, int],
    max_per_site: int = 2,
    once: bool = False,
    stop: threading.Event | None = None,
) -> None:
    """Run queued jobs until `stop` is set; with once=True until no job is waiting or running.

    One worker per database: at start, jobs left running by an earlier worker are queued again.
    """
    store.requeue_running()
    ctx = multiprocessing.get_context("spawn")
    running: dict[str, SpawnProcess] = {}
    try:
        while stop is None or not stop.is_set():
            _reap(store, running)
            for queue, limit in queues.items():
                while (job := store.claim(queue, limit, max_per_site)) is not None:
                    _start(ctx, store, job, running)
            if once and not running:
                return
            if stop is None:
                time.sleep(POLL_S)
            else:
                stop.wait(POLL_S)
    finally:
        # Stopped (or failed) ourselves: stop the jobs too; they are queued again at the next start.
        for proc in running.values():
            _stop(proc)


def _start(ctx: SpawnContext, store: JobStore, job: Job, running: dict[str, SpawnProcess]) -> None:
    spec = REGISTRY.get(job.tool)
    if spec is None:
        store.fail(
            job.taak,
            {
                "error_code": "tool_onbekend",
                "melding": f"De werker kent de tool '{job.tool}' niet.",
                "remedie": "Start de werker met dezelfde versie van de kern als de dienst.",
            },
        )
        return
    proc = ctx.Process(
        target=_run_job, args=(str(store.db), job.taak, spec, job.invoer), name=f"taak-{job.taak}", daemon=True
    )
    proc.start()
    running[job.taak] = proc


def _reap(store: JobStore, running: dict[str, SpawnProcess]) -> None:
    """Forget finished processes and stop those of cancelled jobs."""
    for taak, proc in list(running.items()):
        if proc.is_alive():
            if store.get(taak).status == "afgebroken":
                _stop(proc)
                del running[taak]
            continue
        proc.join()
        del running[taak]
        if store.get(taak).status == "bezig":  # the process ended without reporting
            store.fail(
                taak,
                {
                    "error_code": "taak_gestopt",
                    "melding": f"De taak is onverwacht gestopt (exitcode {proc.exitcode}).",
                    "remedie": "Start de taak opnieuw; meld het als het blijft gebeuren.",
                },
            )


def _stop(proc: SpawnProcess) -> None:
    with contextlib.suppress(psutil.NoSuchProcess):
        kill_tree(psutil.Process(proc.pid))
    proc.join()


def _run_job(db: str, taak: str, spec: ToolSpec, invoer: dict[str, Any]) -> None:
    """Body of a job process: run the tool and record the outcome or the error."""
    store = JobStore(Path(db))
    try:
        kwargs = {}
        if PROGRESS_PARAM in inspect.signature(spec.fn).parameters:
            kwargs[PROGRESS_PARAM] = lambda value: store.set_progress(taak, value)
        result = spec.fn(spec.invoer.model_validate(invoer), **kwargs)
        store.finish(taak, spec.uitvoer.model_validate(result).model_dump(mode="json"))
    except KernError as exc:
        store.fail(taak, exc.to_dict())
    except Exception as exc:  # noqa: BLE001 - every failure of a tool becomes the job's error
        store.fail(
            taak,
            {
                "error_code": "interne_fout",
                "melding": f"De taak is mislukt door een interne fout: {type(exc).__name__}: {exc}.",
                "remedie": "Start de taak opnieuw; meld het als het blijft gebeuren.",
            },
        )
