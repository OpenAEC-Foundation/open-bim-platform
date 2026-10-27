"""Job queue in SQLite: long tools run as jobs that a separate worker picks up."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..errors import KernError
from ..tools.registry import REGISTRY

MAX_WAITING_PER_SITE = 100
RETRY_AFTER_S = 30

Status = Literal["wacht", "bezig", "klaar", "fout", "afgebroken"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    taak TEXT NOT NULL UNIQUE,
    tool TEXT NOT NULL,
    rij TEXT NOT NULL,
    klantsite TEXT NOT NULL,
    invoer TEXT NOT NULL,
    status TEXT NOT NULL,
    voortgang REAL NOT NULL DEFAULT 0,
    uitkomst TEXT,
    fout TEXT,
    gemaakt TEXT NOT NULL,
    gestart TEXT,
    klaar TEXT);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs (status, rij, seq);
"""


class Job(BaseModel):
    taak: str
    tool: str
    status: Status
    voortgang: float
    uitkomst: dict[str, Any] | None
    fout: dict[str, str] | None
    klantsite: str
    gemaakt: str
    gestart: str | None
    klaar: str | None
    # Kept out of the HTTP answer: the input can hold signed addresses.
    rij: str = Field(exclude=True)
    invoer: dict[str, Any] = Field(exclude=True)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _job(row: sqlite3.Row) -> Job:
    return Job(
        taak=row["taak"],
        tool=row["tool"],
        status=row["status"],
        voortgang=row["voortgang"],
        uitkomst=json.loads(row["uitkomst"]) if row["uitkomst"] else None,
        fout=json.loads(row["fout"]) if row["fout"] else None,
        klantsite=row["klantsite"],
        gemaakt=row["gemaakt"],
        gestart=row["gestart"],
        klaar=row["klaar"],
        rij=row["rij"],
        invoer=json.loads(row["invoer"]),
    )


class JobStore:
    """Jobs in one SQLite database (WAL), shared by the HTTP service, the worker and the job processes."""

    def __init__(self, db: Path) -> None:
        self.db = Path(db)
        self.db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.db, timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
            except BaseException:
                con.execute("ROLLBACK")
                raise
            con.execute("COMMIT")

    def submit(self, tool: str, invoer: dict[str, Any], klantsite: str) -> str:
        """Queue a job for a registered long tool; refuses when the site already has too many waiting."""
        rij = REGISTRY[tool].rij
        taak = uuid.uuid4().hex
        with self._transaction() as con:
            (waiting,) = con.execute(
                "SELECT count(*) FROM jobs WHERE status='wacht' AND klantsite=?", (klantsite,)
            ).fetchone()
            if waiting >= MAX_WAITING_PER_SITE:
                raise KernError(
                    "te_druk",
                    f"Er wachten al {waiting} taken voor klantsite '{klantsite}'.",
                    f"Probeer het over {RETRY_AFTER_S} seconden opnieuw.",
                    503,
                    headers={"Retry-After": str(RETRY_AFTER_S)},
                )
            con.execute(
                "INSERT INTO jobs (taak, tool, rij, klantsite, invoer, status, gemaakt) VALUES (?,?,?,?,?,'wacht',?)",
                (taak, tool, rij, klantsite, json.dumps(invoer), _now()),
            )
        return taak

    def get(self, job_id: str) -> Job:
        with self._connect() as con:
            row = con.execute("SELECT * FROM jobs WHERE taak=?", (job_id,)).fetchone()
        if row is None:
            raise KernError(
                "taak_onbekend",
                f"Er is geen taak '{job_id}'.",
                "Gebruik het taaknummer uit het antwoord van POST /v1/tools/{naam}.",
                404,
            )
        return _job(row)

    def cancel(self, job_id: str) -> None:
        """Mark a waiting or running job as cancelled; the worker stops its process. Finished jobs stay as they are."""
        self.get(job_id)
        with self._connect() as con:
            con.execute(
                "UPDATE jobs SET status='afgebroken', klaar=? WHERE taak=? AND status IN ('wacht','bezig')",
                (_now(), job_id),
            )

    def claim(self, queue: str, max_running: int, max_per_site: int) -> Job | None:
        """Oldest waiting job of the queue, unless the queue is full or its site already runs max_per_site jobs."""
        with self._transaction() as con:
            (running,) = con.execute("SELECT count(*) FROM jobs WHERE status='bezig' AND rij=?", (queue,)).fetchone()
            if running >= max_running:
                return None
            row = con.execute(
                "SELECT taak FROM jobs WHERE status='wacht' AND rij=? AND klantsite NOT IN ("
                " SELECT klantsite FROM jobs WHERE status='bezig' GROUP BY klantsite HAVING count(*) >= ?)"
                " ORDER BY seq LIMIT 1",
                (queue, max_per_site),
            ).fetchone()
            if row is None:
                return None
            con.execute("UPDATE jobs SET status='bezig', gestart=? WHERE taak=?", (_now(), row["taak"]))
            claimed = con.execute("SELECT * FROM jobs WHERE taak=?", (row["taak"],)).fetchone()
        return _job(claimed)

    def set_progress(self, job_id: str, value: float) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE jobs SET voortgang=max(voortgang, ?) WHERE taak=? AND status='bezig'",
                (min(max(float(value), 0.0), 1.0), job_id),
            )

    def finish(self, job_id: str, uitkomst: dict[str, Any]) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE jobs SET status='klaar', voortgang=1, uitkomst=?, klaar=? WHERE taak=? AND status='bezig'",
                (json.dumps(uitkomst), _now(), job_id),
            )

    def fail(self, job_id: str, error: dict[str, str]) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE jobs SET status='fout', fout=?, klaar=? WHERE taak=? AND status='bezig'",
                (json.dumps(error), _now(), job_id),
            )

    def requeue_running(self) -> int:
        """Put jobs left running by a stopped worker back in the queue; returns how many."""
        with self._connect() as con:
            return con.execute(
                "UPDATE jobs SET status='wacht', gestart=NULL, voortgang=0 WHERE status='bezig'"
            ).rowcount
