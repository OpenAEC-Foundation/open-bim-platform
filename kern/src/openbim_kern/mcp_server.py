"""MCP over Streamable HTTP, generated from REGISTRY: the same tools, schemas and errors as the /v1 routes."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import BaseModel, ConfigDict
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from . import __version__
from .calls import SITE_HEADER, call_tool, get_spec, is_authorized, parse_input, unauthorized
from .errors import KernError
from .jobs.store import Job, JobStore
from .tools.registry import REGISTRY

JOB_STATUS_TOOL = "taak_stand"


class TaakStandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taak: str


class TaakUit(BaseModel):
    taak: str


def build_server(job_store: Callable[[], JobStore]) -> Server:
    server: Server = Server("openbim-kern", version=__version__)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        tools = [
            types.Tool(
                name=spec.naam,
                description=spec.beschrijving,
                inputSchema=spec.invoer.model_json_schema(),
                # A long tool answers with a job; its outcome comes from taak_stand.
                outputSchema=(TaakUit if spec.lang else spec.uitvoer).model_json_schema(mode="serialization"),
            )
            for spec in REGISTRY.values()
        ]
        tools.append(
            types.Tool(
                name=JOB_STATUS_TOOL,
                description="Geef de stand, voortgang en uitkomst van een taak van een lange tool.",
                inputSchema=TaakStandIn.model_json_schema(),
                outputSchema=Job.model_json_schema(mode="serialization"),
            )
        )
        return tools

    # Input is validated with pydantic in call_tool, so errors read the same as over HTTP.
    @server.call_tool(validate_input=False)
    async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any] | types.CallToolResult:
        try:
            if name == JOB_STATUS_TOOL:
                invoer = parse_input(TaakStandIn, arguments)
                job = await anyio.to_thread.run_sync(job_store().get, invoer.taak)
                return job.model_dump(mode="json")
            request = server.request_context.request
            site = request.headers.get(SITE_HEADER) if request is not None else None
            _, result = await anyio.to_thread.run_sync(call_tool, get_spec(name), arguments, site, job_store)
            return result
        except KernError as exc:
            error = exc.to_dict()
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(error, ensure_ascii=False))],
                structuredContent=error,
                isError=True,
            )

    return server


class McpEndpoint:
    """ASGI endpoint for POST /mcp: the bearer check, then MCP (stateless, answers as JSON)."""

    def __init__(self, job_store: Callable[[], JobStore], keys: list[str]) -> None:
        self.manager = StreamableHTTPSessionManager(app=build_server(job_store), json_response=True, stateless=True)
        self.keys = keys

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not is_authorized(Headers(scope=scope).get("authorization"), self.keys):
            error = unauthorized()
            await JSONResponse(error.to_dict(), status_code=error.status)(scope, receive, send)
            return
        await self.manager.handle_request(scope, receive, send)
