"""FastAPI application: bearer auth, uniform error JSON and the /v1 routes."""

import hmac
import os

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from . import __version__
from .errors import KernError
from .tools import eigenschappen as _eigenschappen  # noqa: F401  (registers the tool)
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


def create_app(keys: list[str] | None = None) -> FastAPI:
    valid_keys = _load_keys(keys)
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
        return JSONResponse(exc.to_dict(), status_code=exc.status)

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
        if spec.lang:
            raise KernError(
                "tool_lang",
                f"De tool '{naam}' is een lange tool en draait als taak.",
                "Lange tools worden nog niet ondersteund via deze route.",
                501,
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
        uitvoer = await run_in_threadpool(spec.fn, invoer)
        return JSONResponse(spec.uitvoer.model_validate(uitvoer).model_dump(mode="json"))

    return app
