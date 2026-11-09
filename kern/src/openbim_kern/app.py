"""FastAPI application: bearer auth, uniform error JSON, the /v1 routes and MCP on /mcp."""

import contextlib
import os
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from . import __version__
from .calls import SITE_HEADER, call_tool, get_spec, is_authorized, unauthorized, validation_error
from .errors import KernError
from .jobs.store import JobStore, default_store
from .mcp_server import McpEndpoint
from .tools import botsingen as _botsingen  # noqa: F401  (registers the tool)
from .tools import eigenschappen as _eigenschappen  # noqa: F401  (registers the tool)
from .tools import koppelen as _koppelen  # noqa: F401  (registers the tool)
from .tools import omzetten as _omzetten  # noqa: F401  (registers the tool)
from .tools.registry import REGISTRY


def _load_keys(keys: list[str] | None) -> list[str]:
    if keys is None:
        keys = os.environ.get("OPENBIM_KERN_SLEUTELS", "").split(",")
    keys = [k.strip() for k in keys if k and k.strip()]
    if not keys:
        raise RuntimeError("No API keys configured: set OPENBIM_KERN_SLEUTELS (comma separated).")
    return keys


def create_app(keys: list[str] | None = None, store: JobStore | None = None) -> FastAPI:
    """The kern service; jobs of long tools go to `store` (default: taken.sqlite in the data directory)."""
    valid_keys = _load_keys(keys)
    stores: list[JobStore] = [store] if store is not None else []

    def job_store() -> JobStore:
        if not stores:  # created on first use, so an app without long tools touches no disk
            stores.append(default_store())
        return stores[0]

    mcp = McpEndpoint(job_store, valid_keys)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with mcp.manager.run():
            yield

    app = FastAPI(
        title="Open BIM Platform kern",
        version=__version__,
        openapi_url="/v1/openapi.json",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_route("/mcp", mcp, methods=["GET", "POST", "DELETE"], include_in_schema=False)

    def require_key(request: Request) -> None:
        if not is_authorized(request.headers.get("authorization"), valid_keys):
            raise unauthorized()

    @app.exception_handler(KernError)
    async def _kern_error(_: Request, exc: KernError) -> JSONResponse:
        return JSONResponse(exc.to_dict(), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        err = validation_error(exc)
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
        spec = get_spec(naam)
        try:
            body = await request.json()
        except ValueError:
            raise KernError(
                "ongeldige_invoer", "Het lichaam is geen geldige JSON.", "Stuur een JSON-object.", 422
            ) from None
        site = request.headers.get(SITE_HEADER)
        status, result = await run_in_threadpool(call_tool, spec, body, site, job_store)
        return JSONResponse(result, status_code=status)

    @app.get("/v1/taken/{taak}", dependencies=[Depends(require_key)])
    def get_job(taak: str) -> JSONResponse:
        return JSONResponse(job_store().get(taak).model_dump(mode="json"))

    @app.delete("/v1/taken/{taak}", dependencies=[Depends(require_key)])
    def cancel_job(taak: str) -> dict[str, str]:
        job_store().cancel(taak)
        return {"status": job_store().get(taak).status}

    return app
