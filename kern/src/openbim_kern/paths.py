"""Local directories of the kern: cache and per-call work directories, under OPENBIM_KERN_DATA."""

import os
import tempfile
from pathlib import Path


def data_dir() -> Path:
    configured = os.environ.get("OPENBIM_KERN_DATA")
    return Path(configured) if configured else Path(tempfile.gettempdir()) / "openbim-kern"
