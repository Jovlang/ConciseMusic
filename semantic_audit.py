#!/usr/bin/env python3
"""Audit selected MusicXML semantics against serialized concise-music output."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from concise_musicxml import load_xml, local, notation_elements, safe_id


SLUR_RE = re.compile(r"(?:\{|,)s(?!oundtie)([^,{}<>]+)([<>])(?=,|\})")


def source_slur_events(root: ET.Element) -> Counter[tuple[str, str, str, str]]:
    """Count slur identity at part/measure/number/type granularity."""
    events: Counter[tuple[str, str, str, str]] = Counter()
    for part in (x for x in root if local(x.tag) == "part"):
        part_id = safe_id(part.get("id", "?"))
        for measure in (x for x in part if local(x.tag) == "measure"):
            measure_id = safe_id(measure.get("number", "?"))
            for note in (x for x in measure if local(x.tag) == "note"):
                for slur in notation_elements(note, "slur"):
                    slur_type = slur.get("type", "")
                    if slur_type in {"start", "stop"}:
                        events[(part_id, measure_id, safe_id(slur.get("number", "1")), slur_type)] += 1
    return events


def output_slur_events(output: str) -> Counter[tuple[str, str, str, str]]:
    """Count serialized slurs at the same identity/location granularity."""
    events: Counter[tuple[str, str, str, str]] = Counter()
    part_id = "?"
    for line in output.splitlines():
        if line.startswith("@part "):
            part_id = line.split(maxsplit=2)[1]
        elif line.startswith("m") and " " in line:
            measure_id = line.split(maxsplit=1)[0][1:]
            for number, symbol in SLUR_RE.findall(line):
                events[(part_id, measure_id, number, "start" if symbol == ">" else "stop")] += 1
    return events


def audit_slurs(root: ET.Element, output: str) -> tuple[Counter, Counter]:
    """Return missing and unexpected slur identities."""
    source = source_slur_events(root)
    serialized = output_slur_events(output)
    return source - serialized, serialized - source


def compression_stats(input_path: Path, output_path: Path) -> tuple[int, int, float]:
    input_bytes = input_path.stat().st_size
    output_bytes = output_path.stat().st_size
    ratio = output_bytes / input_bytes if input_bytes else 0.0
    return input_bytes, output_bytes, ratio


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = load_xml(args.input)
    output = args.output.read_text(encoding="utf-8")
    missing, unexpected = audit_slurs(root, output)
    input_bytes, output_bytes, ratio = compression_stats(args.input, args.output)
    print(f"input_bytes={input_bytes} output_bytes={output_bytes} ratio={ratio:.4f}")
    print(f"slur_missing={sum(missing.values())} slur_unexpected={sum(unexpected.values())}")
    if missing:
        print("missing:", dict(missing))
    if unexpected:
        print("unexpected:", dict(unexpected))
    return 1 if missing or unexpected else 0


if __name__ == "__main__":
    raise SystemExit(main())
