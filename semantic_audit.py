#!/usr/bin/env python3
"""Audit selected MusicXML semantics against serialized concise-music output."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from concise_music_parser import MusicalEvent, parse as parse_cmusic
from concise_musicxml import (
    SemanticScore,
    import_musicxml,
    load_xml,
    local,
    notation_elements,
    render_slur_relations,
    render_tie_relations,
    safe_id,
)


SLUR_RE = re.compile(r"(?:\{|,)s(?!oundtie)([^,{}<>]+)([<>])(?=,|\})")
SLUR_MARKER_RE = re.compile(r"^s(.+)([<>])$")
TIE_MARKER_RE = re.compile(r"^t(.+)([<>~])$")

SourceRelationKey = tuple[str, str, str, int, str, str, str]
RenderedRelationKey = tuple[str, str, str, str, str, str]


@dataclass(frozen=True)
class RelationAudit:
    source_to_model_missing: Counter[SourceRelationKey]
    source_to_model_unexpected: Counter[SourceRelationKey]
    model_to_output_missing: Counter[RenderedRelationKey]
    model_to_output_unexpected: Counter[RenderedRelationKey]

    @property
    def ok(self) -> bool:
        return not any(
            (
                self.source_to_model_missing,
                self.source_to_model_unexpected,
                self.model_to_output_missing,
                self.model_to_output_unexpected,
            )
        )


def source_relation_events(root: ET.Element) -> Counter[SourceRelationKey]:
    """Extract supported tie/slur relations with exact source-note identity."""
    events: Counter[SourceRelationKey] = Counter()
    for part in (item for item in root if local(item.tag) == "part"):
        part_id = safe_id(part.get("id", "?"))
        note_index = 0
        for measure in (item for item in part if local(item.tag) == "measure"):
            measure_id = safe_id(measure.get("number", "?"))
            for note in (item for item in measure if local(item.tag) == "note"):
                note_index += 1
                for tied in notation_elements(note, "tied"):
                    relation_type = tied.get("type", "")
                    if relation_type in {"start", "stop", "continue", "let-ring"}:
                        events[
                            (
                                "tie",
                                part_id,
                                measure_id,
                                note_index,
                                "notated",
                                safe_id(tied.get("number", "1")),
                                relation_type,
                            )
                        ] += 1
                for tie in (item for item in note if local(item.tag) == "tie"):
                    relation_type = tie.get("type", "")
                    if relation_type in {"start", "stop"}:
                        events[
                            ("tie", part_id, measure_id, note_index, "playback", "", relation_type)
                        ] += 1
                for slur in notation_elements(note, "slur"):
                    relation_type = slur.get("type", "")
                    if relation_type in {"start", "stop"}:
                        events[
                            (
                                "slur",
                                part_id,
                                measure_id,
                                note_index,
                                "slur",
                                safe_id(slur.get("number", "1")),
                                relation_type,
                            )
                        ] += 1
    return events


def model_relation_events(score: SemanticScore) -> Counter[SourceRelationKey]:
    """Read typed relations from the imported model at source-note granularity."""
    events: Counter[SourceRelationKey] = Counter()
    for part in score.parts:
        part_id = safe_id(part.identifier)
        for measure in part.measures:
            measure_id = safe_id(measure.number)
            for event in measure.events:
                note_index = event.provenance.note_index
                for tie in event.ties:
                    events[
                        (
                            "tie",
                            part_id,
                            measure_id,
                            note_index,
                            tie.kind,
                            tie.number,
                            tie.relation_type,
                        )
                    ] += 1
                for slur in event.slurs:
                    events[
                        (
                            "slur",
                            part_id,
                            measure_id,
                            note_index,
                            "slur",
                            slur.number,
                            slur.relation_type,
                        )
                    ] += 1
    return events


def marker_relation(marker: str) -> tuple[str, str, str, str] | None:
    """Return category, kind, number, and type for a serialized marker."""
    match = SLUR_MARKER_RE.fullmatch(marker)
    if match:
        number, symbol = match.groups()
        return "slur", "slur", number, "start" if symbol == ">" else "stop"
    # Tuplet markers share the initial ``t`` but are a separate reserved
    # category. Check that prefix before the compact numbered tie form.
    if marker.startswith("tup"):
        return None
    match = TIE_MARKER_RE.fullmatch(marker)
    if match:
        number, symbol = match.groups()
        relation_type = {">": "start", "<": "stop", "~": "continue"}[symbol]
        return "tie", "notated", number, relation_type
    if marker == "let-ring":
        return "tie", "notated", "", "let-ring"
    if marker in {"soundtie>", "soundtie<"}:
        return "tie", "playback", "", "start" if marker.endswith(">") else "stop"
    return None


def model_rendered_relation_events(score: SemanticScore) -> Counter[RenderedRelationKey]:
    """Apply documented relation normalization without serializing the score."""
    events: Counter[RenderedRelationKey] = Counter()
    for part in score.parts:
        part_id = safe_id(part.identifier)
        for measure in part.measures:
            measure_id = safe_id(measure.number)
            for event in measure.events:
                markers = render_tie_relations(event.ties) + render_slur_relations(event.slurs)
                for marker in markers:
                    relation = marker_relation(marker)
                    if relation:
                        category, kind, number, relation_type = relation
                        events[(category, part_id, measure_id, kind, number, relation_type)] += 1
    return events


def output_relation_events(output: str) -> Counter[RenderedRelationKey]:
    """Read relations through the grammar-aware cmusic parser, not regex splitting."""
    events: Counter[RenderedRelationKey] = Counter()
    parsed = parse_cmusic(output)
    for part in parsed.parts:
        for measure in part.measures:
            for voice in measure.voices:
                for event in voice.events:
                    if not isinstance(event, MusicalEvent):
                        continue
                    groups = [group for note in event.notes for group in note.marker_groups]
                    groups.extend(event.common_markers)
                    for group in groups:
                        for marker in group.markers:
                            relation = marker_relation(marker)
                            if relation:
                                category, kind, number, relation_type = relation
                                events[
                                    (
                                        category,
                                        part.identifier,
                                        measure.number,
                                        kind,
                                        number,
                                        relation_type,
                                    )
                                ] += 1
    return events


def audit_relations(root: ET.Element, score: SemanticScore, output: str) -> RelationAudit:
    source = source_relation_events(root)
    model = model_relation_events(score)
    expected_output = model_rendered_relation_events(score)
    serialized = output_relation_events(output)
    return RelationAudit(
        source - model,
        model - source,
        expected_output - serialized,
        serialized - expected_output,
    )


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
    score = import_musicxml(root, args.input.name)
    relations = audit_relations(root, score, output)
    missing, unexpected = audit_slurs(root, output)
    input_bytes, output_bytes, ratio = compression_stats(args.input, args.output)
    print(f"input_bytes={input_bytes} output_bytes={output_bytes} ratio={ratio:.4f}")
    print(f"slur_missing={sum(missing.values())} slur_unexpected={sum(unexpected.values())}")
    print(
        "source_model_relation_missing="
        f"{sum(relations.source_to_model_missing.values())} "
        "source_model_relation_unexpected="
        f"{sum(relations.source_to_model_unexpected.values())}"
    )
    print(
        "model_output_relation_missing="
        f"{sum(relations.model_to_output_missing.values())} "
        "model_output_relation_unexpected="
        f"{sum(relations.model_to_output_unexpected.values())}"
    )
    if missing:
        print("missing:", dict(missing))
    if unexpected:
        print("unexpected:", dict(unexpected))
    if relations.source_to_model_missing:
        print("source-to-model missing:", dict(relations.source_to_model_missing))
    if relations.source_to_model_unexpected:
        print("source-to-model unexpected:", dict(relations.source_to_model_unexpected))
    if relations.model_to_output_missing:
        print("model-to-output missing:", dict(relations.model_to_output_missing))
    if relations.model_to_output_unexpected:
        print("model-to-output unexpected:", dict(relations.model_to_output_unexpected))
    return 1 if missing or unexpected or not relations.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
