"""Tool registry: the single source for the HTTP routes and (later) the MCP server."""

import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

PROGRESS_PARAM = "progress"


@dataclass(frozen=True)
class ToolSpec:
    naam: str
    beschrijving: str
    invoer: type[BaseModel]
    uitvoer: type[BaseModel]
    lang: bool
    rij: str
    fn: Callable
    ref: str  # "module:qualname", importable so a worker process can resolve the tool


REGISTRY: dict[str, ToolSpec] = {}


def tool(naam: str, beschrijving: str, *, lang: bool = False, rij: str = "licht") -> Callable[[Callable], Callable]:
    """Register `fn(invoer) -> uitvoer` as tool `naam`. Input/output types come from the type hints.

    A `progress` keyword parameter (used by long tools) is not part of the input schema.
    """

    def decorator(fn: Callable) -> Callable:
        hints = typing.get_type_hints(fn)
        params = [p for p in inspect.signature(fn).parameters.values() if p.name != PROGRESS_PARAM]
        if not params:
            raise TypeError(f"tool {naam!r}: function needs an input parameter")
        invoer = hints.get(params[0].name)
        uitvoer = hints.get("return")
        for kind, typ in (("input", invoer), ("output", uitvoer)):
            if not (inspect.isclass(typ) and issubclass(typ, BaseModel)):
                raise TypeError(f"tool {naam!r}: {kind} type must be a pydantic model, got {typ!r}")
        if invoer.model_config.get("extra") != "forbid":
            raise TypeError(f"tool {naam!r}: input model must set extra='forbid'")
        if naam in REGISTRY:
            raise ValueError(f"tool {naam!r} already registered")
        REGISTRY[naam] = ToolSpec(
            naam=naam,
            beschrijving=beschrijving,
            invoer=invoer,
            uitvoer=uitvoer,
            lang=lang,
            rij=rij,
            fn=fn,
            ref=f"{fn.__module__}:{fn.__qualname__}",
        )
        return fn

    return decorator
