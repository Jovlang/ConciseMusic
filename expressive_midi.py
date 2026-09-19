#!/usr/bin/env python3
"""LLM-planned expressive MIDI rendered directly from SemanticScore."""

from __future__ import annotations

import argparse
import copy
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, fields, is_dataclass
from fractions import Fraction
from pathlib import Path

from concise_musicxml import SemanticScore, import_musicxml, load_xml, render_cmusic
from concise_music_v2 import render_cmusic_v2
from neutral_midi import (
    MidiRenderResult,
    RealizationError,
    SourceEventId,
    TempoEvent,
    _measure_span,
    _measure_time,
    audit_realization,
    encode_midi,
    realize_neutral,
)


class PerformancePlanError(ValueError):
    pass


@dataclass(frozen=True)
class PerformanceSection:
    start_measure: int
    end_measure: int
    tempo_bpm: Fraction | None
    velocity_delta: int
    duration_scale: Fraction
    character: str = ""


@dataclass(frozen=True)
class PerformancePlan:
    summary: str
    sections: tuple[PerformanceSection, ...]


PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "sections"],
    "properties": {
        "summary": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "start_measure",
                    "end_measure",
                    "tempo_bpm",
                    "velocity_delta",
                    "duration_scale",
                    "character",
                ],
                "properties": {
                    "start_measure": {"type": "integer", "minimum": 1},
                    "end_measure": {"type": "integer", "minimum": 1},
                    "tempo_bpm": {
                        "anyOf": [
                            {"type": "number", "minimum": 20, "maximum": 300},
                            {"type": "null"},
                        ]
                    },
                    "velocity_delta": {"type": "integer", "minimum": -32, "maximum": 32},
                    "duration_scale": {"type": "number", "minimum": 0.5, "maximum": 1.0},
                    "character": {"type": "string"},
                },
            },
        },
    },
}


def _transport_value(value):
    """Mechanically serialize typed score data without selecting musical fields."""
    if isinstance(value, Fraction):
        return {"$type": "Fraction", "numerator": value.numerator, "denominator": value.denominator}
    if is_dataclass(value):
        result = {"$type": type(value).__name__}
        for item in fields(value):
            result[item.name] = _transport_value(getattr(value, item.name))
        return result
    if isinstance(value, (list, tuple)):
        return [_transport_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _transport_value(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported SemanticScore transport value: {type(value).__name__}")


def serialize_semantic_score_diagnostic(score: SemanticScore) -> str:
    """Lossless diagnostic serialization; not the default LLM score view."""
    if not isinstance(score, SemanticScore):
        raise TypeError("serialize_semantic_score_diagnostic requires SemanticScore")
    return json.dumps(_transport_value(score), ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class InputSizeDiagnostics:
    musicxml_bytes: int | None
    cmusic_bytes: int
    semantic_score_bytes: int


def input_size_diagnostics(
    score: SemanticScore, source_path: Path | None = None
) -> InputSizeDiagnostics:
    cmusic = render_cmusic(score).encode("utf-8")
    diagnostic = serialize_semantic_score_diagnostic(score).encode("utf-8")
    source_bytes = source_path.stat().st_size if source_path is not None else None
    return InputSizeDiagnostics(source_bytes, len(cmusic), len(diagnostic))


def parse_performance_plan(data: dict, measure_count: int) -> PerformancePlan:
    if not isinstance(data, dict) or set(data) != {"summary", "sections"}:
        raise PerformancePlanError("performance plan must contain only summary and sections")
    if not isinstance(data["summary"], str) or not isinstance(data["sections"], list):
        raise PerformancePlanError("invalid performance plan types")
    sections: list[PerformanceSection] = []
    previous_end = 0
    required = {
        "start_measure", "end_measure", "tempo_bpm", "velocity_delta",
        "duration_scale", "character",
    }
    for raw in data["sections"]:
        if not isinstance(raw, dict) or set(raw) != required:
            raise PerformancePlanError("invalid performance section fields")
        start, end = raw["start_measure"], raw["end_measure"]
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int):
            raise PerformancePlanError("measure bounds must be integers")
        if start <= previous_end or end < start or end > measure_count:
            raise PerformancePlanError("performance sections must be ordered, non-overlapping, and in range")
        tempo = raw["tempo_bpm"]
        tempo_value = None if tempo is None else Fraction(str(tempo))
        if tempo_value is not None and not 20 <= tempo_value <= 300:
            raise PerformancePlanError("tempo_bpm must be between 20 and 300")
        velocity = raw["velocity_delta"]
        if not isinstance(velocity, int) or isinstance(velocity, bool) or not -32 <= velocity <= 32:
            raise PerformancePlanError("velocity_delta must be an integer from -32 to 32")
        duration = Fraction(str(raw["duration_scale"]))
        if not Fraction(1, 2) <= duration <= 1:
            raise PerformancePlanError("duration_scale must be between 0.5 and 1.0")
        if not isinstance(raw["character"], str):
            raise PerformancePlanError("character must be text")
        sections.append(PerformanceSection(start, end, tempo_value, velocity, duration, raw["character"]))
        previous_end = end
    return PerformancePlan(data["summary"], tuple(sections))


def _response_text(response: dict) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    for item in response.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    return content["text"]
    raise PerformancePlanError("LLM response contained no structured output text")


def generate_performance_plan(
    score: SemanticScore,
    model: str,
    *,
    api_key: str | None = None,
    endpoint: str = "https://api.openai.com/v1/responses",
    timeout: int = 120,
    cmusic_version: str = "v2",
) -> PerformancePlan:
    """Ask an LLM for interpretation only; note truth remains in SemanticScore."""
    if not model.strip():
        raise PerformancePlanError("an LLM model name is required")
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise PerformancePlanError("OPENAI_API_KEY is not set")
    measure_count = len(score.parts[0].measures) if score.parts else 0
    if cmusic_version == "v2":
        score_view = render_cmusic_v2(score)
    elif cmusic_version == "v1":
        score_view = render_cmusic(score)
    else:
        raise PerformancePlanError(f"unsupported cmusic LLM view: {cmusic_version}")
    prompt = (
        "Create a restrained, musically coherent performance plan for this score. "
        "Do not reproduce, add, remove, or alter score notes. Choose ordered, non-overlapping "
        "measure regions. tempo_bpm null means retain the authored/default tempo. "
        "velocity_delta adjusts neutral velocity 64. duration_scale controls neutral note length "
        "and may only shorten notes. Return only the requested structured data.\n\n"
        "CMUSIC VIEW OF THE AUTHORITATIVE SEMANTIC SCORE:\n"
        + score_view
    )
    body = json.dumps(
        {
            "model": model,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "performance_plan",
                    "strict": True,
                    "schema": PLAN_SCHEMA,
                }
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as opened:
            response = json.load(opened)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PerformancePlanError(f"LLM request failed ({exc.code}): {detail}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise PerformancePlanError(f"LLM request failed: {exc}") from exc
    try:
        data = json.loads(_response_text(response))
    except json.JSONDecodeError as exc:
        raise PerformancePlanError("LLM structured output was not valid JSON") from exc
    return parse_performance_plan(data, measure_count)


def _measure_starts(score: SemanticScore) -> dict[int, Fraction]:
    if not score.parts:
        return {}
    starts: dict[int, Fraction] = {}
    onset = Fraction(0)
    current_time = (4, 4)
    for measure in score.parts[0].measures:
        starts[measure.index] = onset
        current_time = _measure_time(measure.attributes, current_time)
        onset += _measure_span(measure, current_time)
    return starts


def apply_performance_plan(score: SemanticScore, plan: PerformancePlan):
    """Apply interpretation to performed properties, never to semantic score identity."""
    realized = copy.deepcopy(realize_neutral(score))
    source_events = {
        SourceEventId(part.identifier, event.provenance.note_index): event
        for part in score.parts
        for measure in part.measures
        for event in measure.events
    }
    starts = _measure_starts(score)
    tempo_by_onset = {event.onset: event.bpm for event in realized.tempos}
    for section in plan.sections:
        if section.tempo_bpm is not None:
            tempo_by_onset[starts[section.start_measure]] = section.tempo_bpm
    realized.tempos = [TempoEvent(onset, bpm) for onset, bpm in sorted(tempo_by_onset.items())]

    for note in realized.notes:
        source = source_events[note.source_event_ids[0]]
        section = next(
            (
                item for item in plan.sections
                if item.start_measure <= source.provenance.measure_index <= item.end_measure
            ),
            None,
        )
        if section is None:
            continue
        note.velocity = max(1, min(127, note.velocity + section.velocity_delta))
        note.duration *= section.duration_scale
    audit = audit_realization(score, realized)
    if not audit.ok:
        raise RealizationError(f"expressive realization provenance audit failed: {audit}")
    return realized, audit


def render_expressive_midi(
    score: SemanticScore, plan: PerformancePlan | None = None, *, model: str = "",
    api_key: str | None = None,
) -> MidiRenderResult:
    selected = plan or generate_performance_plan(score, model, api_key=api_key)
    realization, audit = apply_performance_plan(score, selected)
    return MidiRenderResult(encode_midi(realization), realization, audit)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--plan-output", type=Path)
    args = parser.parse_args()
    try:
        score = import_musicxml(load_xml(args.input), args.input.name)
        plan = generate_performance_plan(score, args.model)
        if args.plan_output:
            args.plan_output.write_text(json.dumps({
                "summary": plan.summary,
                "sections": [
                    {
                        "start_measure": item.start_measure,
                        "end_measure": item.end_measure,
                        "tempo_bpm": float(item.tempo_bpm) if item.tempo_bpm is not None else None,
                        "velocity_delta": item.velocity_delta,
                        "duration_scale": float(item.duration_scale),
                        "character": item.character,
                    }
                    for item in plan.sections
                ],
            }, indent=2), encoding="utf-8")
        args.output.write_bytes(render_expressive_midi(score, plan).data)
    except (OSError, ValueError, PerformancePlanError, RealizationError) as exc:
        print(f"error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
