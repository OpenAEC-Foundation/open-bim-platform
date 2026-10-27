"""FastAPI application: bearer auth, uniform error JSON and the /v1 routes."""

import hmac
import os
import re

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from . import __version__
from .errors import KernError
from .jobs.store import JobStore
from .paths import data_dir
from .tools import eigenschappen as _eigenschappen  # noqa: F401  (registers the tool)
from .tools import omzetten as _omzetten  # noqa: F401  (registers the tool)
from .tools.registry import REGISTRY


def _load_keys(keys: list[str] | None) -> list[str]:
    if keys is None:
        keys = os.environ.get("OPENBIM_KERN_SLEUTELS", "").split(",")
    keys = [k.strip() for k in keys if k and k.strip()]
    if not keys:
        raise RuntimeError("No API keys configured: set OPENBIM_KERN_SLEUTELS (comma separated).")
    return keys


def _validation_error(exc: ValidationError | RequestValidationError) -> KernError:
    details = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'lichaam'}: {e['msg']}" for e in exc.errors())
    return KernError(
        "ongeldige_invoer",
        f"De invoer is ongeldig: {details}",
        "Controleer de invoer tegen het invoerschema in GET /v1/tools.",
        422,
    )


SITE_HEADER = "X-OpenAEC-Klantsite"
DEFAULT_SITE = "lokaal"
_SITE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


def _site(request: Request) -> str:
    site = request.headers.get(SITE_HEADER, DEFAULT_SITE)
    if not _SITE.fullmatch(site):
        raise KernError(
            "ongeldige_invoer",
            f"De kop {SITE_HEADER} is ongeldig.",
            "Gebruik letters, cijfers, punt, streep of liggend streepje (hoogstens 100 tekens).",
            422,
        )
    return site


def create_app(keys: list[str] | None = None, store: JobStore | None = None) -> FastAPI:
    """The kern service; jobs of long tools go to `store` (default: taken.sqlite in the data directory)."""
    valid_keys = _load_keys(keys)
    stores: list[JobStore] = [store] if store is not None else []

    def job_store() -> JobStore:
        if not stores:  # created on first use, so an app without long tools touches no disk
            stores.append(JobStore(data_dir() / "taken.sqlite"))
        return stores[0]

    app = FastAPI(
        title="Open BIM Platform kern",
        version=__version__,
        openapi_url="/v1/openapi.json",
        docs_url=None,
        redoc_url=None,
    )

    def require_key(request: Request) -> None:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() == "bearer" and token:
            # Compare against every key (no early exit) in constant time.
            matches = [hmac.compare_digest(token.encode(), k.encode()) for k in valid_keys]
            if any(matches):
                return
        raise KernError(
            "geen_toegang",
            "Ontbrekende of ongeldige API-sleutel.",
            "Stuur de header 'Authorization: Bearer <sleutel>' mee.",
            401,
        )

    @app.exception_handler(KernError)
    async def _kern_error(_: Request, exc: KernError) -> JSONResponse:
        return JSONResponse(exc.to_dict(), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        err = _validation_error(exc)
        return JSONResponse(err.to_dict(), status_code=err.status)

    @app.get("/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "versie": __version__}

    @app.get("/v1/tools", dependencies=[Depends(require_key)])
    def list_tools() -> list[dict]:
        return [
            {
                "naam": t.naam,
                "beschrijving": t.beschrijving,
                "lang": t.lang,
                "invoer_schema": t.invoer.model_json_schema(),
                "uitvoer_schema": t.uitvoer.model_json_schema(),
            }
            for t in REGISTRY.values()
        ]

    @app.post("/v1/tools/{naam}", dependencies=[Depends(require_key)])
    async def run_tool(naam: str, request: Request) -> JSONResponse:
        spec = REGISTRY.get(naam)
        if spec is None:
            raise KernError(
                "tool_onbekend",
                f"Er is geen tool met de naam '{naam}'.",
                "Raadpleeg GET /v1/tools voor de beschikbare tools.",
                404,
            )
        try:
            body = await request.json()
        except ValueError:
            raise KernError(
                "ongeldige_invoer", "Het lichaam is geen geldige JSON.", "Stuur een JSON-object.", 422
            ) from None
        try:
            invoer = spec.invoer.model_validate(body)
        except ValidationError as exc:
            raise _validation_error(exc) from None
        if spec.lang:
            payload = invoer.model_dump(mode="json")
            taak = await run_in_threadpool(job_store().submit, naam, payload, _site(request))
            return JSONResponse({"taak": taak}, status_code=202)
        uitvoer = await run_in_threadpool(spec.fn, invoer)
        return JSONResponse(spec.uitvoer.model_validate(uitvoer).model_dump(mode="json"))

    @app.get("/v1/taken/{taak}", dependencies=[Depends(require_key)])
    def get_job(taak: str) -> JSONResponse:
        return JSONResponse(job_store().get(taak).model_dump(mode="json"))

    @app.delete("/v1/taken/{taak}", dependencies=[Depends(require_key)])
    def cancel_job(taak: str) -> dict[str, str]:
        job_store().cancel(taak)
        return {"status": job_store().get(taak).status}

    return app
