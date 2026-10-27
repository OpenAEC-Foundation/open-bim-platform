"""Importable test tools (importable so a spawned worker can resolve them by reference)."""

import os
import time
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from openbim_kern.errors import KernError


class EchoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tekst: str


class EchoOut(BaseModel):
    tekst: str


def echo(invoer: EchoIn) -> EchoOut:
    return EchoOut(tekst=invoer.tekst)


class WachtIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seconden: float = 0.0


class WachtUit(BaseModel):
    klaar: bool


def _no_progress(_: float) -> None:
    pass


def traag(invoer: WachtIn, progress: Callable[[float], None] = _no_progress) -> WachtUit:
    """Sleep in ten steps, reporting progress after each."""
    for step in range(10):
        time.sleep(invoer.seconden / 10)
        progress((step + 1) / 10)
    return WachtUit(klaar=True)


def faalt(invoer: WachtIn) -> WachtUit:
    raise KernError("expres_mislukt", "Deze tool faalt altijd.", "Gebruik een andere tool.", 422)


def crasht(invoer: WachtIn) -> WachtUit:
    os._exit(3)
