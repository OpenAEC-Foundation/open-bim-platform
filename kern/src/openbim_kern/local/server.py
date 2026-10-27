"""Local development server for one project folder: plays the part of the platform app and of Storage.

It lists the IFC models in the folder, serves and receives files over HTTP, and has the kern convert them. The kern
fetches sources from it and delivers output to it, exactly as it would with signed addresses in the cloud.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import quote

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .. import CONVERTER_VERSION
from ..calls import validation_error
from ..errors import KernError
from ..tools.omzetten import BASE_TARGETS, planned_parts

DERIVED = ".afgeleid"
VITE_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
LOCAL_HOSTS = ["127.0.0.1", "localhost"]
CHUNK_BYTES = 8 * 1024 * 1024
_KERN_TIMEOUT = httpx.Timeout(30.0, read=300.0)
_VERSION = re.compile(r"[0-9a-f]{12}")
_PART = re.compile(r"model\.frag|deel-[1-9][0-9]*\.frag")


class LokaleBron(BaseModel):
    model_config = ConfigDict(extra="forbid")

    soort: Literal["bestand"]
    sleutel: str
    versie: str = Field(pattern=r"^[0-9a-f]{12}$")


class LokaalEigenschappenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bron: LokaleBron
    globalids: list[str] = Field(min_length=1, max_length=1000)


class BackgroundServer:
    """Serve an ASGI app with uvicorn on 127.0.0.1 in a daemon thread, for `openbim-kern lokaal` and tests."""

    def __init__(self, app: Any, port: int) -> None:
        self.url = f"http://127.0.0.1:{port}"
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, name=f"server-{port}", daemon=True)

    def __enter__(self) -> BackgroundServer:
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError(f"server for {self.url} did not start")
            time.sleep(0.02)
        return self

    def __exit__(self, *_: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=15)


class _Hashes:
    """sha256 per file, cached on (path, mtime, size)."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[int, int, str]] = {}
        self._lock = threading.Lock()

    def sha256(self, path: Path) -> str:
        stat = path.stat()
        key = str(path)
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None and hit[:2] == (stat.st_mtime_ns, stat.st_size):
            return hit[2]
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(CHUNK_BYTES):
                digest.update(chunk)
        with self._lock:
            self._cache[key] = (stat.st_mtime_ns, stat.st_size, digest.hexdigest())
        return digest.hexdigest()


def _invalid_path(pad: str) -> KernError:
    return KernError(
        "ongeldig_pad",
        f"Het pad '{pad}' valt buiten de projectmap of is niet toegestaan.",
        "Gebruik een relatief pad binnen de projectmap, zonder '..'; schrijven kan alleen onder .afgeleid/.",
        400,
    )


class _Project:
    def __init__(self, root: Path, kern_url: str, kern_key: str, poort: int) -> None:
        self.root = root.resolve()
        self.files_url = f"http://127.0.0.1:{poort}/lokaal/bestanden/"
        self.kern_url = kern_url
        self.kern = httpx.Client(
            base_url=kern_url, headers={"Authorization": f"Bearer {kern_key}"}, timeout=_KERN_TIMEOUT
        )
        self.hashes = _Hashes()

    # Paths

    def resolve(self, pad: str, *, writable: bool = False) -> Path:
        """The file for a relative path in the project folder; refuses anything that could leave it."""
        pure = PurePosixPath(pad)
        if (
            not pad
            or pure.is_absolute()
            or "\\" in pad
            or ":" in pad
            or ".." in pure.parts
            or (writable and (len(pure.parts) < 2 or pure.parts[0] != DERIVED))
        ):
            raise _invalid_path(pad)
        path = self.root.joinpath(*pure.parts).resolve()
        if not path.is_relative_to(self.root):
            raise _invalid_path(pad)
        return path

    def model_files(self) -> list[Path]:
        found = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            found.extend(
                Path(dirpath) / name
                for name in sorted(filenames)
                if name.lower().endswith(".ifc") and not name.startswith(".")
            )
        return found

    def key(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def derived_rel(self, sleutel: str, versie: str) -> str:
        return f"{DERIVED}/{sleutel}/{versie}/{CONVERTER_VERSION}"

    def derived_dir(self, sleutel: str, versie: str) -> Path:
        return self.root.joinpath(*PurePosixPath(self.derived_rel(sleutel, versie)).parts)

    def url(self, relative: str) -> str:
        return self.files_url + quote(relative)

    # The kern

    def call_kern(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self.kern.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise KernError(
                "kern_onbereikbaar",
                f"De BIM-kern op {self.kern_url} is niet bereikbaar: {exc}.",
                "Start de kern (openbim-kern lokaal start hem mee) en probeer opnieuw.",
                502,
            ) from exc

    def job(self, derived: Path) -> dict[str, Any] | None:
        """The kern's job for this derived folder, if one was queued and the kern still knows it."""
        marker = derived / "taak.json"
        if not marker.is_file():
            return None
        taak = json.loads(marker.read_text(encoding="utf-8"))["taak"]
        r = self.call_kern("GET", f"/v1/taken/{taak}")
        if r.status_code == 404:
            return None
        if not r.is_success:
            raise _kern_error(r)
        return r.json()

    # Models

    def model(self, path: Path) -> dict[str, Any]:
        sleutel = self.key(path)
        versie = self.hashes.sha256(path)[:12]
        derived = self.derived_dir(sleutel, versie)
        index_file = derived / "index.json"
        index = json.loads(index_file.read_text(encoding="utf-8")) if index_file.is_file() else None
        status, fout = "wacht", None
        if index is not None:
            status = "klaar"
        elif (job := self.job(derived)) is not None:
            if job["status"] == "fout":
                status, fout = "fout", job["fout"]
            elif job["status"] == "bezig":
                status = "bezig"
        parts = PurePosixPath(sleutel).parts
        return {
            "bron": {"soort": "bestand", "sleutel": sleutel, "versie": versie},
            "naam": path.stem,
            "discipline": parts[0] if len(parts) > 1 else "",
            "status": status,
            "fout": fout,
            "delen": [{"naam": d["naam"], "bytes": d["bytes"]} for d in index["delen"]] if index else [],
            "index": index,
        }

    def queue_conversions(self) -> list[dict[str, str]]:
        """Queue an omzetten job for every model without derived data and without a job in progress."""
        queued = []
        for path in self.model_files():
            sleutel = self.key(path)
            sha = self.hashes.sha256(path)
            derived = self.derived_dir(sleutel, sha[:12])
            if (derived / "index.json").is_file():
                continue
            job = self.job(derived)
            if job is not None and job["status"] in ("wacht", "bezig"):
                continue
            size = path.stat().st_size
            parts = planned_parts(size)
            frags = [f"deel-{i}.frag" for i in range(1, parts + 1)] if parts else ["model.frag"]
            target = self.derived_rel(sleutel, sha[:12])
            body = {
                "bron": {"url": self.url(sleutel), "sha256": sha, "grootte": size},
                "doelen": {name: self.url(f"{target}/{name}") for name in [*BASE_TARGETS, *frags]},
            }
            r = self.call_kern("POST", "/v1/tools/omzetten", json=body)
            if r.status_code != 202:
                raise _kern_error(r)
            taak = r.json()["taak"]
            derived.mkdir(parents=True, exist_ok=True)
            _write_atomic(derived / "taak.json", json.dumps({"taak": taak}).encode())
            queued.append({"sleutel": sleutel, "taak": taak})
        return queued

    def part(self, sleutel: str, versie: str, deel: str) -> Path:
        """A converted part of a model version (what the viewer loads), without knowing the storage layout."""
        if not _VERSION.fullmatch(versie) or not _PART.fullmatch(deel):
            raise KernError(
                "ongeldige_invoer",
                "De versie of de naam van het deel is ongeldig.",
                "Gebruik versie en delen[].naam uit GET /lokaal/project.",
                422,
            )
        self.resolve(sleutel)  # refuses paths outside the folder
        derived = self.derived_dir(sleutel, versie)
        if not (derived / "index.json").is_file():
            raise KernError(
                "nog_niet_klaar",
                f"Versie {versie} van {sleutel} is nog niet omgezet.",
                "Zet het model om met POST /lokaal/omzetten en wacht tot de status klaar is.",
                409,
            )
        path = derived / deel
        if not path.is_file():
            raise KernError(
                "deel_onbekend",
                f"Het model {sleutel} heeft geen deel '{deel}'.",
                "Gebruik delen[].naam uit GET /lokaal/project.",
                404,
            )
        return path

    def properties(self, invoer: LokaalEigenschappenIn) -> httpx.Response:
        bron = invoer.bron
        path = self.resolve(bron.sleutel)
        if not path.is_file() or path not in self.model_files():
            raise KernError(
                "model_onbekend",
                f"Er is geen model '{bron.sleutel}' in de projectmap.",
                "Gebruik een bron uit GET /lokaal/project.",
                404,
            )
        derived = self.derived_dir(bron.sleutel, bron.versie)
        if not (derived / "index.json").is_file():
            raise KernError(
                "nog_niet_klaar",
                f"Versie {bron.versie} van {bron.sleutel} is nog niet omgezet.",
                "Zet het model om met POST /lokaal/omzetten en wacht tot de status klaar is.",
                409,
            )
        db = derived / "eigenschappen.sqlite"
        index = {"url": self.url(f"{self.derived_rel(bron.sleutel, bron.versie)}/{db.name}")}
        index["sha256"] = self.hashes.sha256(db)
        return self.call_kern("POST", "/v1/tools/eigenschappen", json={"index": index, "globalids": invoer.globalids})


def _kern_error(r: httpx.Response) -> KernError:
    try:
        body = r.json()
        return KernError(body["error_code"], body["melding"], body["remedie"], r.status_code)
    except (ValueError, KeyError, TypeError):
        return KernError(
            "kern_fout",
            f"De BIM-kern gaf een onverwacht antwoord (HTTP-status {r.status_code}).",
            "Bekijk de uitvoer van de kern.",
            502,
        )


def _write_atomic(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".schrijf-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def create_local_app(root: Path, kern_url: str, kern_key: str, poort: int = 8740) -> FastAPI:
    """The local server for the project folder `root`, reached at http://127.0.0.1:<poort>; no authentication."""
    project = _Project(root, kern_url, kern_key, poort)
    app = FastAPI(title="Open BIM Platform lokaal", docs_url=None, redoc_url=None, openapi_url=None)
    # Only local hosts: a web page cannot reach the folder through a rebound domain name.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)
    app.add_middleware(
        CORSMiddleware, allow_origins=VITE_ORIGINS, allow_methods=["GET", "POST", "PUT"], allow_headers=["*"]
    )

    @app.exception_handler(KernError)
    async def _kern_error_json(_: Request, exc: KernError) -> JSONResponse:
        return JSONResponse(exc.to_dict(), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        err = validation_error(exc)
        return JSONResponse(err.to_dict(), status_code=err.status)

    @app.get("/lokaal/project")
    def get_project() -> dict[str, Any]:
        return {
            "project": project.root.name,
            "werkwijze": "bestanden",
            "modellen": [project.model(path) for path in project.model_files()],
        }

    @app.get("/lokaal/bestanden/{pad:path}")
    def get_file(pad: str) -> FileResponse:
        path = project.resolve(pad)
        if not path.is_file():
            raise KernError(
                "bestand_onbekend", f"Het bestand '{pad}' bestaat niet.", "Controleer het pad in de projectmap.", 404
            )
        return FileResponse(path)

    @app.put("/lokaal/bestanden/{pad:path}")
    async def put_file(pad: str, request: Request) -> dict[str, int]:
        path = project.resolve(pad, writable=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".ontvang-", suffix=".part")
        size = 0
        try:
            with os.fdopen(fd, "wb") as out:
                async for chunk in request.stream():
                    out.write(chunk)
                    size += len(chunk)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        return {"bytes": size}

    @app.get("/lokaal/laad")
    def get_part(sleutel: str, versie: str, deel: str) -> FileResponse:
        return FileResponse(project.part(sleutel, versie, deel), media_type="application/octet-stream")

    @app.post("/lokaal/omzetten")
    def post_omzetten() -> dict[str, list[dict[str, str]]]:
        return {"taken": project.queue_conversions()}

    @app.post("/lokaal/eigenschappen")
    def post_eigenschappen(invoer: LokaalEigenschappenIn) -> JSONResponse:
        r = project.properties(invoer)
        if not r.is_success:
            raise _kern_error(r)
        return JSONResponse(r.json())

    return app
