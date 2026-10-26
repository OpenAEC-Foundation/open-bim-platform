"""Fetch input sources and deliver output over http(s); never touches local paths from requests."""

import contextlib
import hashlib
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, HttpUrl

from openbim_kern.errors import KernError

CHUNK_BYTES = 8 * 1024 * 1024
_TIMEOUT = httpx.Timeout(30.0, read=300.0)


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    sha256: str | None = None
    grootte: int | None = None


def _unreachable(url: str, detail: str) -> KernError:
    return KernError(
        "bron_onbereikbaar",
        f"De bron {url} kon niet worden opgehaald: {detail}.",
        "Controleer het adres en of de bron bereikbaar is, en probeer opnieuw.",
        status=502,
    )


def _invalid(melding: str) -> KernError:
    return KernError(
        "bron_ongeldig",
        melding,
        "Lever de bron opnieuw aan en controleer de opgegeven sha256 en grootte.",
        status=422,
    )


def fetch_source(source: Source, workdir: Path, max_bytes: int) -> Path:
    """Stream the source into workdir, verify size and sha256, then rename to the final name.

    On any failure no file is left behind in workdir.
    """
    url = str(source.url)
    workdir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=workdir, prefix="bron-", suffix=".part")
    tmp = Path(tmp_name)
    try:
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "wb") as out:
            try:
                with httpx.stream("GET", url, timeout=_TIMEOUT, follow_redirects=True) as response:
                    if response.status_code >= 400:
                        raise _unreachable(url, f"HTTP-status {response.status_code}")
                    for chunk in response.iter_bytes(CHUNK_BYTES):
                        size += len(chunk)
                        if size > max_bytes:
                            raise KernError(
                                "bron_te_groot",
                                f"De bron {url} is groter dan de toegestane {max_bytes} bytes.",
                                "Lever een kleinere bron aan.",
                                status=413,
                            )
                        digest.update(chunk)
                        out.write(chunk)
            except httpx.RemoteProtocolError as exc:
                raise _invalid(f"De download van {url} is afgebroken: {exc}.") from exc
            except httpx.TransportError as exc:
                raise _unreachable(url, str(exc) or type(exc).__name__) from exc
        if source.grootte is not None and size != source.grootte:
            raise _invalid(f"De grootte van {url} is {size} bytes, verwacht {source.grootte}.")
        if source.sha256 is not None and digest.hexdigest() != source.sha256.lower():
            raise _invalid(f"De sha256 van {url} komt niet overeen met de opgegeven waarde.")
        final = workdir / f"bron-{digest.hexdigest()[:16]}.bin"
        os.replace(tmp, final)
        return final
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _read_blocks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            yield chunk


def deliver(path: Path, url: str) -> None:
    """Stream the file to url with HTTP PUT."""
    try:
        response = httpx.put(
            url,
            content=_read_blocks(path),
            headers={"Content-Length": str(path.stat().st_size)},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise _target_error(url, str(exc) or type(exc).__name__) from exc
    if response.status_code >= 400:
        raise _target_error(url, f"HTTP-status {response.status_code}")


def _target_error(url: str, detail: str) -> KernError:
    return KernError(
        "doel_onbereikbaar",
        f"De uitvoer kon niet naar {url} worden afgeleverd: {detail}.",
        "Controleer het doeladres en of het PUT accepteert, en probeer opnieuw.",
        status=502,
    )
