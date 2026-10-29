"""Child processes a test may have left behind."""

import psutil


def leftover_processes() -> list[psutil.Process]:
    """Children of the test process, except the resource tracker that multiprocessing keeps running on POSIX."""
    found = []
    for child in psutil.Process().children(recursive=True):
        try:
            if any("multiprocessing.resource_tracker" in part for part in child.cmdline()):
                continue
        except psutil.Error:
            continue  # gone meanwhile
        found.append(child)
    return found
