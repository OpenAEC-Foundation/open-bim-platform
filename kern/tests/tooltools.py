"""Importable test tools (importable so a spawned worker can resolve them by reference)."""

from pydantic import BaseModel, ConfigDict


class EchoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tekst: str


class EchoOut(BaseModel):
    tekst: str


def echo(invoer: EchoIn) -> EchoOut:
    return EchoOut(tekst=invoer.tekst)
