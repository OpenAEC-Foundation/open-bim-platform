"""Measure the conversion of every IFC file in a folder and write a report.

    python scripts/measure.py <map> --uit <rapport.md>

Writes the report as a Markdown table (bestand | MB IFC | MB .frag | s | piekgeheugen | delen, with the times per
stage and the peak memory of IfcOpenShell for the property index), plus <rapport>.json with the raw rows. The
converted output lands in <map>/.afgeleid/, where `openbim-kern lokaal <map>` finds it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openbim_kern.measure import measure, render


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("map", type=Path, help="map met IFC-modellen")
    parser.add_argument("--uit", type=Path, required=True, help="het rapport (Markdown)")
    args = parser.parse_args(argv)
    root = args.map.resolve()
    rows = measure(root)
    args.uit.parent.mkdir(parents=True, exist_ok=True)
    args.uit.write_text(render(rows, root), encoding="utf-8")
    args.uit.with_suffix(".json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Rapport: {args.uit}")


if __name__ == "__main__":
    main()
