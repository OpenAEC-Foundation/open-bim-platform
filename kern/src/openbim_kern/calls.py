"""One way to call a tool, shared by HTTP and MCP, so that both give the same answer and the same errors."""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from .errors import KernError
from .jobs.store import JobStore
from .tools.registry import REGISTRY, ToolSpec

SITE_HEADER = "X-OpenAEC-Klantsite"
DEFAULT_SITE = "lokaal"
_SITE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


def is_authorized(header: str | None, keys: list[str]) -> bool:
    """True for 'Bearer <key>' with one of the keys; compares against every key in constant time."""
    scheme, _, token = (header or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    matches = [hmac.compare_digest(token.encode(), k.encode()) for k in keys]
    return any(matches)


def unauthorized() -> KernError:
    return KernError(
        "geen_toegang",
        "Ontbrekende of ongeldige API-sleutel.",
        "Stuur de header 'Authorization: Bearer <sleutel>' mee.",
        401,
    )


def validation_error(exc: Any) -> KernError:
    """KernError for a pydantic ValidationError or FastAPI RequestValidationError (both have .errors())."""
    details = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'lichaam'}: {e['msg']}" for e in exc.errors())
    return KernError(
        "ongeldige_invoer",
        f"De invoer is ongeldig: {details}",
        "Controleer de invoer tegen het invoerschema in GET /v1/tools.",
        422,
    )


def parse_site(value: str | None) -> str:
    site = DEFAULT_SITE if value is None else value
    if not _SITE.fullmatch(site):
        raise KernError(
            "ongeldige_invoer",
            f"De kop {SITE_HEADER} is ongeldig.",
            "Gebruik letters, cijfers, punt, streep of liggend streepje (hoogstens 100 tekens).",
            422,
        )
    return site


def get_spec(naam: str) -> ToolSpec:
    spec = REGISTRY.get(naam)
    if spec is None:
        raise KernError(
            "tool_onbekend",
            f"Er is geen tool met de naam '{naam}'.",
            "Raadpleeg GET /v1/tools voor de beschikbare tools.",
            404,
        )
    return spec


def parse_input[M: BaseModel](model: type[M], data: Any) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise validation_error(exc) from None


def call_tool(
    spec: ToolSpec, data: Any, site: str | None, job_store: Callable[[], JobStore]
) -> tuple[int, dict[str, Any]]:
    """Validate the input, then run the tool (200 with its output) or queue a long tool as a job (202 with taak).

    Blocking: callers in async code run it in a thread.
    """
    invoer = parse_input(spec.invoer, data)
    if spec.lang:
        taak = job_store().submit(spec.naam, invoer.model_dump(mode="json"), parse_site(site))
        return 202, {"taak": taak}
    return 200, spec.uitvoer.model_validate(spec.fn(invoer)).model_dump(mode="json")
