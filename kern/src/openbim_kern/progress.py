"""Progress of a long tool: a function that gets the share done, from 0 to 1."""

from collections.abc import Callable

Progress = Callable[[float], None]


def no_progress(_: float) -> None:
    """For a caller that does not follow the progress."""
