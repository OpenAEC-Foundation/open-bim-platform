"""Command line `openbim-kern`: serve the kern, run the worker, or convert a local IFC file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from .errors import KernError

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Open BIM Platform: de BIM-kern.")


@app.command(help="Start de rekenkern: HTTP (/v1) en MCP (/mcp). Sleutels uit OPENBIM_KERN_SLEUTELS.")
def serve(
    poort: Annotated[int, typer.Option("--poort", help="Poort om op te luisteren.")] = 8730,
    host: Annotated[str, typer.Option("--host", help="Adres om op te luisteren; 0.0.0.0 in een container.")] = (
        "127.0.0.1"
    ),
) -> None:
    from .app import create_app

    uvicorn.run(create_app(), host=host, port=poort)


@app.command(help="Voer de lange taken uit de wachtrij uit, elk in een eigen proces.")
def werker(
    eenmalig: Annotated[bool, typer.Option("--eenmalig", help="Stop zodra er niets meer wacht of draait.")] = False,
) -> None:
    from .jobs.store import default_store
    from .jobs.worker import queues_from_env, run_worker

    run_worker(default_store(), queues_from_env(), once=eenmalig)


@app.command(
    help="Zet een lokaal IFC-bestand om naar uitmap: model.frag (of deel-<n>.frag), eigenschappen.sqlite, "
    "ruimtelijk.json en index.json. Alleen voor lokaal gebruik; deze opdracht leest en schrijft schijf."
)
def omzetten(
    ifc: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Het IFC-bestand.")],
    uitmap: Annotated[Path, typer.Argument(file_okay=False, help="Map voor de uitvoer.")],
) -> None:
    from .tools.omzetten import convert_to_folder

    try:
        uitkomst = convert_to_folder(ifc, uitmap)
    except KernError as exc:
        typer.echo(f"{exc.melding}\n{exc.remedie}", err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(uitkomst.model_dump(mode="json"), ensure_ascii=False))
