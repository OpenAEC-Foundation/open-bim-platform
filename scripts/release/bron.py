"""bron.json for every release asset: version, tag, commit, licence and source, as the SuperCloud contract asks.

    python bron.py <out> --version 2026.44.1 --tag v2026.44.1 --commit <40 hex>

Standard library only: kern/Dockerfile runs it too.
"""

import argparse
import json
import re

LICENCE = "LGPL-3.0-or-later"
SOURCE = "https://github.com/OpenAEC-Foundation/open-bim-platform"


def source_info(version: str, tag: str, commit: str) -> dict:
    """The fields of bron.json; a release tag must be `v<version>` and the commit a full SHA."""
    if tag and tag != f"v{version}":
        raise ValueError(f"tag {tag!r} does not match version {version!r}")
    if commit and not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError(f"commit {commit!r} is not a full SHA of 40 characters")
    return {"versie": version, "tag": tag, "commit": commit, "licentie": LICENCE, "broncode": SOURCE}


def write(path: str, version: str, tag: str, commit: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(source_info(version, tag, commit), f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out")
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--commit", default="")
    args = parser.parse_args()
    write(args.out, args.version, args.tag, args.commit)
