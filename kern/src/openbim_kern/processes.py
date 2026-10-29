"""Process-tree helpers: the memory of a process with its children, and stopping it with its children."""

import contextlib

import psutil


def tree_rss(root: psutil.Process) -> int:
    """Resident memory of the process and all its descendants; 0 when it is gone."""
    try:
        procs = [root, *root.children(recursive=True)]
    except psutil.Error:
        return 0
    total = 0
    for p in procs:
        with contextlib.suppress(psutil.Error):
            total += p.memory_info().rss
    return total


def kill_tree(root: psutil.Process) -> None:
    """Kill the process and all its descendants, and wait for them to go."""
    try:
        procs = [*root.children(recursive=True), root]
    except psutil.Error:
        procs = [root]
    for p in procs:
        with contextlib.suppress(psutil.Error):
            p.kill()
    psutil.wait_procs(procs, timeout=10)
