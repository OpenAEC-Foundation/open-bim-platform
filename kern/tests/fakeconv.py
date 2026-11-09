"""Fake converter for tests. Same CLI as convert.mjs; behaviour is driven by environment variables.

FAKE_FAIL_ONCE_MARKER  path; when it does not exist yet, create it and fail with a WebAssembly.Exception.
FAKE_ERROR             message written to stderr; exit code 1.
FAKE_HOLD_MB           allocate this many MB and hold them for a while.
FAKE_SLEEP_S           seconds to sleep before finishing.
FAKE_PARTIAL           when set, write a partial output file before failing.
FAKE_V8_OOM            when set, die like Node does when the V8 heap is full (fatal error, native stack, exit 134).
"""

import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    mode, *args = sys.argv[1:]
    marker = os.environ.get("FAKE_FAIL_ONCE_MARKER")
    if marker and not Path(marker).exists():
        Path(marker).write_text("x")
        if mode == "frag" and os.environ.get("FAKE_PARTIAL"):
            Path(args[1]).write_bytes(b"partial")
        print("RuntimeError: WebAssembly.Exception: boom", file=sys.stderr)
        return 1
    if os.environ.get("FAKE_V8_OOM"):
        print("FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory", file=sys.stderr)
        print("----- Native stack trace -----", file=sys.stderr)
        print(" 1: 0x942e80  [node]", file=sys.stderr)
        print("11: 0x72bd21e369b6 ", file=sys.stderr)
        return 134
    hold = int(os.environ.get("FAKE_HOLD_MB", "0"))
    block = bytearray(hold * 1024 * 1024)
    for i in range(0, len(block), 4096):
        block[i] = 1  # touch the pages so they count towards RSS
    if hold:
        time.sleep(30)
    time.sleep(float(os.environ.get("FAKE_SLEEP_S", "0")))
    err = os.environ.get("FAKE_ERROR")
    if err:
        if mode == "frag" and os.environ.get("FAKE_PARTIAL"):
            Path(args[1]).write_bytes(b"partial")
        print("first line", file=sys.stderr)
        print(err, file=sys.stderr)
        return 1
    if mode == "frag":
        data = Path(args[0]).read_bytes()
        Path(args[1]).write_bytes(data)
        print(json.dumps({"in_bytes": len(data), "out_bytes": len(data), "sec": 0.01}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
