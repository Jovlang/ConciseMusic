#!/usr/bin/env python3
"""Deterministic neutral realization and Standard MIDI encoding for SemanticScore."""

from __future__ import annotations

import argparse
import math
import re
import struct
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from concise_musicxml import (
    InstrumentDefinition,
    Rest,
    SemanticNoteEvent,
    SemanticPart,
    SemanticScore,
    UnknownNote,
    Unpitched,
    WrittenPitch,
    import_musicxml,
    load_xml,
)


TICKS_PER_QUARTER = 480
DEFAULT_TEMPO_BPM = Fraction(120)
DEFAULT_VELOCITY = 64


class RealizationError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class SourceEventId:
    part_id: str
    note_index: int


@dataclass
class PerformedNote:
    identifier: int
    source_event_ids: list[SourceEventId]
    part_index: int
    channel: int
    pitch: int
    onset: Fraction
    duration: Fraction
    velocity: int = DEFAULT_VELOCITY


@dataclass(frozen=True)
class EventDisposition:
    kind: str
    performed_note_ids: tuple[int, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class TempoEvent:
    onset: Fraction
    bpm: Fraction


@dataclass(frozen=True)
class TimeSignatureEvent:
    onset: Fraction
    numerator: int
    denominator: int


@dataclass(frozen=True)
class ProgramEvent:
    onset: Fraction
    part_index: int
    channel: int
    program: int
    instrument_id: str


@dataclass
class NeutralRealization:
    notes: list[PerformedNote] = field(default_factory=list)
    dispositions: dict[SourceEventId, EventDisposition] = field(default_factory=dict)
    tempos: list[TempoEvent] = field(default_factory=list)
    time_signatures: list[TimeSignatureEvent] = field(default_factory=list)
    programs: list[ProgramEvent] = field(default_factory=list)
    part_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RealizationAudit:
    missing_dispositions: frozenset[SourceEventId]
    unexpected_dispositions: frozenset[SourceEventId]
    performed_notes_without_sources: tuple[int, ...]
    unknown_performed_sources: frozenset[SourceEventId]
    unknown_disposition_note_ids: tuple[int, ...]

    @property
    def ok(self) -> bool:
        return not any(
            (
                self.missing_dispositions,
                self.unexpected_dispositions,
                self.performed_notes_without_sources,
                self.unknown_performed_sources,
                self.unknown_disposition_note_ids,
            )
        )


@dataclass(frozen=True)
class MidiRenderResult:
    data: bytes
    realization: NeutralRealization
    audit: RealizationAudit

    @property
    def midi_note_sources(self) -> dict[int, tuple[SourceEventId, ...]]:
        return {
            note.identifier: tuple(note.source_event_ids)
            for note in self.realization.notes
        }


PITCH_CLASSES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
TIME_RE = re.compile(r"^time(?:\d+)?=(\d+)/(\d+)$")
TEMPO_RE = re.compile(r"^tempo=([0-9]+(?:\.[0-9]+)?)(?:\(([^)]+)\))?$")
TRANSPOSE_RE = re.compile(r"^transpose(\d*)=(-?\d+)$")
TRANSPOSEX_RE = re.compile(r"^transposex(\d*)=(.+)$")


def _fraction_decimal(value: str) -> Fraction:
    return Fraction(value)


def _measure_time(attributes: list[str], current: tuple[int, int]) -> tuple[int, int]:
    result = current
    for token in attributes:
        match = TIME_RE.fullmatch(token)
        if match:
            result = (int(match.group(1)), int(match.group(2)))
        elif token.startswith("timex"):
            raise RealizationError(f"additive/nonstandard meter is not yet supported: {token}")
    return result


def _measure_span(measure, time_signature: tuple[int, int]) -> Fraction:
    numerator, denominator = time_signature
    nominal = Fraction(numerator * 4, denominator)
    if measure.implicit and measure.content_duration:
        return measure.content_duration
    return max(nominal, measure.content_duration)


def _transpose_updates(attributes: list[str]) -> dict[str, int]:
    updates: dict[str, int] = {}
    for token in attributes:
        match = TRANSPOSE_RE.fullmatch(token)
        if match:
            updates[match.group(1) or "*"] = int(match.group(2))
            continue
        match = TRANSPOSEX_RE.fullmatch(token)
        if not match:
            continue
        staff = match.group(1) or "*"
        values: dict[str, str] = {}
        flags: set[str] = set()
        for item in match.group(2).split(","):
            if ":" in item:
                key, value = item.split(":", 1)
                values[key] = value
            else:
                flags.add(item)
        if "double" in flags:
            raise RealizationError(f"doubled transposition is not yet supported: {token}")
        if "chrom" not in values and "dia" in values:
            raise RealizationError(f"diatonic-only transposition has no unambiguous MIDI pitch: {token}")
        updates[staff] = int(values.get("chrom", "0")) + 12 * int(values.get("oct", "0"))
    return updates


def _tempo_from_direction(value: str) -> Fraction | None:
    match = TEMPO_RE.fullmatch(value)
    if not match:
        return None
    bpm = _fraction_decimal(match.group(1))
    unit = match.group(2) or "quarter"
    factors = {
        "whole": Fraction(4),
        "half": Fraction(2),
        "quarter": Fraction(1),
        "eighth": Fraction(1, 2),
        "16th": Fraction(1, 4),
        "32nd": Fraction(1, 8),
    }
    if unit not in factors:
        raise RealizationError(f"unsupported metronome beat unit: {unit}")
    return bpm * factors[unit]


def _midi_pitch(content: WrittenPitch, transpose: int) -> int:
    if content.step not in PITCH_CLASSES:
        raise RealizationError(f"invalid written pitch step: {content.step}")
    if content.alter.denominator != 1:
        raise RealizationError("microtonal pitch requires pitch-bend realization")
    try:
        octave = int(content.octave)
    except ValueError as exc:
        raise RealizationError(f"invalid written octave: {content.octave}") from exc
    pitch = (octave + 1) * 12 + PITCH_CLASSES[content.step] + int(content.alter) + transpose
    if not 0 <= pitch <= 127:
        raise RealizationError(f"sounding MIDI pitch is out of range: {pitch}")
    return pitch


def _tie_relations(event: SemanticNoteEvent) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    notated = [relation for relation in event.ties if relation.kind == "notated"]
    playback = [relation for relation in event.ties if relation.kind == "playback"]
    relations: list[tuple[str, str]] = []
    for relation in notated:
        if relation.relation_type == "continue":
            relations.extend(((relation.number, "stop"), (relation.number, "start")))
        elif relation.relation_type in {"start", "stop"}:
            relations.append((relation.number, relation.relation_type))
    notated_types = {relation.relation_type for relation in notated}
    for relation in playback:
        if relation.relation_type not in notated_types:
            relations.append(("sound", relation.relation_type))
    stops = [item for item in relations if item[1] == "stop"]
    starts = [item for item in relations if item[1] == "start"]
    return stops, starts


def _event_key(event: SemanticNoteEvent, pitch: int, number: str) -> tuple:
    source = event.provenance
    return (
        source.part_id,
        source.staff,
        source.voice,
        event.instrument_id,
        pitch,
        number,
    )


def _instrument_definition(
    part: SemanticPart, event: SemanticNoteEvent
) -> InstrumentDefinition | None:
    by_id = {definition.xml_id: definition for definition in part.instruments}
    if event.instrument_id:
        definition = by_id.get(event.instrument_id)
        if definition is None:
            raise RealizationError(
                f"undefined instrument reference {event.instrument_id!r} in part {part.identifier}"
            )
        return definition
    return part.instruments[0] if len(part.instruments) == 1 else None


def _lane_key(part: SemanticPart, event: SemanticNoteEvent) -> tuple[str, str, str, str]:
    definition = _instrument_definition(part, event)
    instrument_id = definition.xml_id if definition is not None else event.instrument_id
    source = event.provenance
    return (part.identifier, source.staff, source.voice, instrument_id)


def _assign_channels(score: SemanticScore) -> dict[tuple[str, str, str, str], int]:
    keys: list[tuple[str, str, str, str]] = []
    requested: dict[tuple[str, str, str, str], int | None] = {}
    seen = set()
    for part in score.parts:
        for measure in part.measures:
            for event in measure.events:
                if not isinstance(event.content, (WrittenPitch, Unpitched)):
                    continue
                definition = _instrument_definition(part, event)
                if isinstance(event.content, Unpitched):
                    if not event.instrument_id:
                        raise RealizationError(
                            f"unpitched instrument mapping requires a semantic instrument reference: "
                            f"{SourceEventId(part.identifier, event.provenance.note_index)}"
                        )
                    if definition is None or definition.midi_unpitched is None:
                        raise RealizationError(
                            f"unpitched instrument has no midi-unpitched mapping: {event.instrument_id}"
                        )
                key = _lane_key(part, event)
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
                    channel = definition.midi_channel if definition is not None else None
                    if channel is not None and not 1 <= channel <= 16:
                        raise RealizationError(f"MusicXML midi-channel is out of range: {channel}")
                    requested[key] = channel - 1 if channel is not None else (
                        9 if isinstance(event.content, Unpitched) else None
                    )
    assigned: dict[tuple[str, str, str, str], int] = {}
    used = {channel for channel in requested.values() if channel is not None}
    available = [channel for channel in range(16) if channel != 9 and channel not in used]
    for key in keys:
        channel = requested[key]
        if channel is None:
            if not available:
                raise RealizationError("neutral MIDI has no free channel for a pitched voice/instrument lane")
            channel = available.pop(0)
        assigned[key] = channel
    return assigned


def _grace_timing(measure) -> dict[int, tuple[Fraction, Fraction, str]]:
    """Return performed onset/duration overrides keyed by source note index."""
    overrides: dict[int, tuple[Fraction, Fraction, str]] = {}
    lanes: dict[tuple[str, str], list[SemanticNoteEvent]] = {}
    for event in measure.events:
        source = event.provenance
        lanes.setdefault((source.staff, source.voice), []).append(event)

    for events in lanes.values():
        index = 0
        while index < len(events):
            if events[index].grace is None:
                index += 1
                continue
            start = index
            while index < len(events) and events[index].grace is not None:
                index += 1
            grace_events = events[start:index]
            if index >= len(events):
                source = grace_events[0].provenance
                raise RealizationError(
                    f"grace group has no following principal note: "
                    f"{SourceEventId(source.part_id, source.note_index)}"
                )
            principal = events[index]
            if isinstance(principal.content, Rest) or principal.duration <= 0:
                raise RealizationError("grace group must precede a positive-duration sounding note")
            if any(event.grace.make_time for event in grace_events if event.grace):
                raise RealizationError("grace make-time realization is not yet implemented")
            if any(event.grace.steal_time_previous for event in grace_events if event.grace):
                raise RealizationError("grace steal-time-previous realization is not yet implemented")
            percentages = {
                Fraction(event.grace.steal_time_following)
                for event in grace_events
                if event.grace and event.grace.steal_time_following
            }
            if len(percentages) > 1:
                raise RealizationError("grace group has conflicting steal-time-following values")
            if percentages:
                percentage = next(iter(percentages))
                if not 0 < percentage < 100:
                    raise RealizationError("grace steal-time-following must be between 0 and 100")
                allocation = principal.duration * percentage / 100
                detail = f"stole {percentage}% from following note"
            else:
                allocation = min(Fraction(1, 8), principal.duration / 4)
                detail = "neutral default stole time from following note"

            slot = -1
            slots: list[int] = []
            for event in grace_events:
                if not event.chord:
                    slot += 1
                elif slot < 0:
                    raise RealizationError("grace chord member has no preceding grace chord head")
                slots.append(slot)
            slot_count = slot + 1
            if slot_count <= 0 or allocation <= 0 or allocation >= principal.duration:
                raise RealizationError("grace allocation leaves no positive principal-note duration")
            slot_duration = allocation / slot_count
            for event, slot_index in zip(grace_events, slots):
                overrides[event.provenance.note_index] = (
                    principal.onset + slot_duration * slot_index,
                    slot_duration,
                    detail,
                )

            principal_members = [principal]
            member_index = index + 1
            while (
                member_index < len(events)
                and events[member_index].grace is None
                and events[member_index].chord
                and events[member_index].onset == principal.onset
            ):
                principal_members.append(events[member_index])
                member_index += 1
            for member in principal_members:
                overrides[member.provenance.note_index] = (
                    member.onset + allocation,
                    member.duration - allocation,
                    "time donated to preceding grace group",
                )
    return overrides


def realize_neutral(score: SemanticScore) -> NeutralRealization:
    """Realize written score order with deterministic, non-expressive policies."""
    result = NeutralRealization(part_names=[part.name or part.identifier for part in score.parts])
    channels = _assign_channels(score)
    active_ties: dict[tuple, PerformedNote] = {}
    tempo_candidates: dict[Fraction, Fraction] = {}
    time_candidates: dict[Fraction, tuple[int, int]] = {}
    program_state: dict[tuple[int, int], int] = {}
    program_at_position: dict[tuple[int, int, Fraction], int] = {}

    for part_index, part in enumerate(score.parts):
        absolute_measure_start = Fraction(0)
        current_time = (4, 4)
        recorded_time: tuple[int, int] | None = None
        transpositions: dict[str, int] = {"*": 0}
        for measure in part.measures:
            grace_timing = _grace_timing(measure)
            for token in measure.attributes:
                if token.startswith(("measure-repeat", "beat-repeat", "multirest")) or re.match(
                    r"^slash\d*=", token
                ):
                    raise RealizationError(f"measure shorthand requires expansion before MIDI: {token}")
            current_time = _measure_time(measure.attributes, current_time)
            transpositions.update(_transpose_updates(measure.attributes))
            if part_index == 0 and current_time != recorded_time:
                previous = time_candidates.get(absolute_measure_start)
                if previous is not None and previous != current_time:
                    raise RealizationError("conflicting time signatures at the same score position")
                time_candidates[absolute_measure_start] = current_time
                recorded_time = current_time
            for offset, direction in measure.directions:
                if direction.startswith(("oct", "ped")):
                    raise RealizationError(f"direction requires a dedicated MIDI policy: {direction}")
                tempo = _tempo_from_direction(direction)
                if tempo is not None:
                    onset = absolute_measure_start + offset
                    previous = tempo_candidates.get(onset)
                    if previous is not None and previous != tempo:
                        raise RealizationError(f"conflicting tempos at score offset {onset}")
                    tempo_candidates[onset] = tempo

            for event in measure.events:
                source_id = SourceEventId(part.identifier, event.provenance.note_index)
                if source_id in result.dispositions:
                    raise RealizationError(f"duplicate semantic source identity: {source_id}")
                if isinstance(event.content, Rest):
                    result.dispositions[source_id] = EventDisposition("intentionally_silent", detail="rest")
                    continue
                if isinstance(event.content, UnknownNote):
                    raise RealizationError(f"unknown note content cannot be realized: {source_id}")
                staff = event.provenance.staff
                definition = _instrument_definition(part, event)
                channel_key = _lane_key(part, event)
                channel = channels[channel_key]
                if isinstance(event.content, Unpitched):
                    if definition is None or definition.midi_unpitched is None:
                        raise RealizationError(f"unpitched instrument mapping is unavailable: {source_id}")
                    if not 1 <= definition.midi_unpitched <= 128:
                        raise RealizationError(
                            f"MusicXML midi-unpitched is out of range: {definition.midi_unpitched}"
                        )
                    pitch = definition.midi_unpitched - 1
                else:
                    transpose = transpositions.get(staff, transpositions.get("*", 0))
                    pitch = _midi_pitch(event.content, transpose)
                stops, starts = _tie_relations(event)
                performed: PerformedNote | None = None
                for number, _ in stops:
                    key = _event_key(event, pitch, number)
                    tied = active_ties.pop(key, None)
                    if tied is None:
                        raise RealizationError(f"tie stop has no matching active start: {source_id} tie {number}")
                    if performed is not None and performed is not tied:
                        raise RealizationError(f"one score event closes multiple unrelated ties: {source_id}")
                    performed = tied
                performed_onset, performed_duration, timing_detail = grace_timing.get(
                    event.provenance.note_index, (event.onset, event.duration, "")
                )
                onset = absolute_measure_start + performed_onset
                if definition is not None and definition.midi_program is not None:
                    if not 1 <= definition.midi_program <= 128:
                        raise RealizationError(
                            f"MusicXML midi-program is out of range: {definition.midi_program}"
                        )
                    program = definition.midi_program - 1
                    state_key = (part_index, channel)
                    if program_state.get(state_key) != program:
                        position_key = (part_index, channel, onset)
                        previous_program = program_at_position.get(position_key)
                        if previous_program is not None and previous_program != program:
                            raise RealizationError(
                                "conflicting MIDI programs share a channel at the same onset"
                            )
                        result.programs.append(
                            ProgramEvent(onset, part_index, channel, program, definition.xml_id)
                        )
                        program_at_position[position_key] = program
                        program_state[state_key] = program
                if performed is not None:
                    performed.duration = max(
                        performed.onset + performed.duration, onset + performed_duration
                    ) - performed.onset
                    performed.source_event_ids.append(source_id)
                    result.dispositions[source_id] = EventDisposition(
                        "merged_by_tie", (performed.identifier,), "continuous sounding note"
                    )
                else:
                    if performed_duration <= 0:
                        raise RealizationError(f"non-grace pitched note has no positive duration: {source_id}")
                    performed = PerformedNote(
                        identifier=len(result.notes) + 1,
                        source_event_ids=[source_id],
                        part_index=part_index,
                        channel=channel,
                        pitch=pitch,
                        onset=onset,
                        duration=performed_duration,
                    )
                    result.notes.append(performed)
                    detail = "ornament retained without neutral expansion" if any(
                        marker.startswith("orn=") for marker in event.pre_grace_markers
                    ) else ""
                    if timing_detail:
                        detail = "; ".join(value for value in (timing_detail, detail) if value)
                    result.dispositions[source_id] = EventDisposition(
                        "grace_realization" if event.grace is not None else "directly_realized",
                        (performed.identifier,),
                        detail,
                    )
                for number, _ in starts:
                    key = _event_key(event, pitch, number)
                    if key in active_ties and active_ties[key] is not performed:
                        raise RealizationError(f"overlapping tie identity is ambiguous: {source_id} tie {number}")
                    active_ties[key] = performed

            absolute_measure_start += _measure_span(measure, current_time)

    if active_ties:
        examples = ", ".join(str(key) for key in list(active_ties)[:3])
        raise RealizationError(f"unclosed tie start(s): {examples}")
    result.tempos = [TempoEvent(onset, bpm) for onset, bpm in sorted(tempo_candidates.items())]
    if not result.tempos or result.tempos[0].onset != 0:
        result.tempos.insert(0, TempoEvent(Fraction(0), DEFAULT_TEMPO_BPM))
    result.time_signatures = [
        TimeSignatureEvent(onset, signature[0], signature[1])
        for onset, signature in sorted(time_candidates.items())
    ]
    if not result.time_signatures or result.time_signatures[0].onset != 0:
        result.time_signatures.insert(0, TimeSignatureEvent(Fraction(0), 4, 4))
    return result


def _tick(value: Fraction) -> int:
    scaled = value * TICKS_PER_QUARTER
    return (scaled.numerator * 2 + scaled.denominator) // (2 * scaled.denominator)


def _vlq(value: int) -> bytes:
    if value < 0:
        raise ValueError("negative MIDI delta")
    buffer = value & 0x7F
    result = bytearray([buffer])
    while value > 0x7F:
        value >>= 7
        result.insert(0, (value & 0x7F) | 0x80)
    return bytes(result)


def _track(events: list[tuple[int, int, bytes]]) -> bytes:
    body = bytearray()
    previous = 0
    for tick, _, payload in sorted(events, key=lambda item: (item[0], item[1])):
        body.extend(_vlq(tick - previous))
        body.extend(payload)
        previous = tick
    body.extend(b"\x00\xff\x2f\x00")
    return b"MTrk" + struct.pack(">I", len(body)) + body


def encode_midi(realization: NeutralRealization) -> bytes:
    """Encode only provenance-bearing performed notes plus conductor metadata."""
    active_until: dict[tuple[int, int], Fraction] = {}
    for note in sorted(realization.notes, key=lambda item: (item.onset, item.identifier)):
        key = (note.channel, note.pitch)
        if note.onset < active_until.get(key, Fraction(-1)):
            raise RealizationError(
                f"overlapping pitch {note.pitch} on channel {note.channel} needs a lane policy"
            )
        active_until[key] = note.onset + note.duration
    conductor: list[tuple[int, int, bytes]] = []
    for tempo in realization.tempos:
        micros = round(60_000_000 / float(tempo.bpm))
        if not 1 <= micros <= 0xFFFFFF:
            raise RealizationError(f"tempo is outside Standard MIDI range: {tempo.bpm}")
        conductor.append((_tick(tempo.onset), 0, b"\xff\x51\x03" + micros.to_bytes(3, "big")))
    for signature in realization.time_signatures:
        if signature.denominator <= 0 or signature.denominator & (signature.denominator - 1):
            raise RealizationError("MIDI time-signature denominator must be a power of two")
        exponent = int(math.log2(signature.denominator))
        conductor.append(
            (
                _tick(signature.onset),
                1,
                bytes((0xFF, 0x58, 0x04, signature.numerator, exponent, 24, 8)),
            )
        )
    tracks = [_track(conductor)]
    for part_index, name in enumerate(realization.part_names):
        encoded_name = name.encode("utf-8")
        events: list[tuple[int, int, bytes]] = [
            (0, 0, b"\xff\x03" + _vlq(len(encoded_name)) + encoded_name)
        ]
        for program in realization.programs:
            if program.part_index == part_index:
                events.append(
                    (_tick(program.onset), 1, bytes((0xC0 | program.channel, program.program)))
                )
        for note in realization.notes:
            if note.part_index != part_index:
                continue
            if not note.source_event_ids:
                raise RealizationError(f"performed note {note.identifier} has no semantic provenance")
            start = _tick(note.onset)
            stop = _tick(note.onset + note.duration)
            if stop <= start:
                raise RealizationError(
                    f"performed note {note.identifier} collapses under MIDI tick quantization"
                )
            events.append((start, 2, bytes((0x90 | note.channel, note.pitch, note.velocity))))
            events.append((stop, 1, bytes((0x80 | note.channel, note.pitch, 0))))
        tracks.append(_track(events))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), TICKS_PER_QUARTER)
    return header + b"".join(tracks)


def audit_realization(score: SemanticScore, realization: NeutralRealization) -> RealizationAudit:
    expected = {
        SourceEventId(part.identifier, event.provenance.note_index)
        for part in score.parts
        for measure in part.measures
        for event in measure.events
    }
    disposed = set(realization.dispositions)
    performed_without_sources = tuple(
        note.identifier for note in realization.notes if not note.source_event_ids
    )
    performed_sources = {
        source_id for note in realization.notes for source_id in note.source_event_ids
    }
    performed_ids = {note.identifier for note in realization.notes}
    unknown_disposition_note_ids = tuple(
        note_id
        for disposition in realization.dispositions.values()
        for note_id in disposition.performed_note_ids
        if note_id not in performed_ids
    )
    return RealizationAudit(
        missing_dispositions=frozenset(expected - disposed),
        unexpected_dispositions=frozenset(disposed - expected),
        performed_notes_without_sources=performed_without_sources,
        unknown_performed_sources=frozenset(performed_sources - expected),
        unknown_disposition_note_ids=unknown_disposition_note_ids,
    )


def render_midi(score: SemanticScore) -> MidiRenderResult:
    realization = realize_neutral(score)
    audit = audit_realization(score, realization)
    if not audit.ok:
        raise RealizationError(f"realization provenance audit failed: {audit}")
    return MidiRenderResult(encode_midi(realization), realization, audit)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="MusicXML input")
    parser.add_argument("-o", "--output", type=Path, required=True, help="MIDI output path")
    args = parser.parse_args()
    try:
        score = import_musicxml(load_xml(args.input), args.input.name)
        result = render_midi(score)
        args.output.write_bytes(result.data)
        print(
            f"performed_notes={len(result.realization.notes)} "
            f"source_dispositions={len(result.realization.dispositions)} "
            f"provenance_audit={'ok' if result.audit.ok else 'failed'}"
        )
    except (OSError, ValueError, RealizationError) as exc:
        print(f"error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
