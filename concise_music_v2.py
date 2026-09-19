#!/usr/bin/env python3
"""Experimental concise-music-v2 renderer and recursive-descent parser."""

from __future__ import annotations

import json
import re
import argparse
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from concise_musicxml import (
    SemanticNoteEvent,
    SemanticScore,
    Voice,
    frac,
    normalized_arpeggiations,
    render_articulation_groups,
    render_fermatas,
    render_grace_semantics,
    render_note_content,
    render_slur_relations,
    render_technical_groups,
    render_tie_relations,
    import_musicxml,
    load_xml,
)


class V2ParseError(ValueError):
    pass


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _a(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9_.#/+%?^:\-]+", value) else _q(value)


def _markers(event: SemanticNoteEvent) -> list[str]:
    compact = (
        render_tie_relations(event.ties)
        + render_slur_relations(event.slurs)
        + render_articulation_groups(event.articulations)
        + render_technical_groups(event.technical)
        + render_fermatas(event.fermatas)
        + list(event.pre_grace_markers)
        + render_grace_semantics(event.grace)
        + list(event.notation_markers)
    )
    return [_expand_marker(marker) for marker in compact]


def _expand_marker(marker: str) -> str:
    relations = (
        (r"^t([^<>~]+)([<>~])$", "tie"),
        (r"^soundtie([<>])$", "playback-tie"),
        (r"^s([^<>]+)([<>])$", "slur"),
        (r"^gl([^<>]+)([<>])(?::(.*))?$", "glissando"),
        (r"^slide([^<>]+)([<>])(?::(.*))?$", "slide"),
        (r"^tup([^<>]+)([<>])$", "tuplet"),
    )
    endpoint = {">": "start", "<": "stop", "~": "continue"}
    for pattern, name in relations:
        match = re.fullmatch(pattern, marker)
        if match:
            groups = match.groups()
            if name == "playback-tie":
                return f"{name}-{endpoint[groups[0]]}"
            result = f"{name}-{endpoint[groups[1]]}={groups[0]}"
            if len(groups) > 2 and groups[2]:
                result += f":{groups[2]}"
            return result
    prefixes = {
        "art=": "articulation=",
        "tech=": "technical=",
        "ferm=": "fermata=",
        "orn=": "ornament=",
        "tm=": "time-modification=",
        "nh=": "notehead=",
    }
    for prefix, expanded in prefixes.items():
        if marker.startswith(prefix):
            return expanded + marker[len(prefix):]
    exact = {"g": "grace", "gslash": "grace-slash"}
    if marker in exact:
        return exact[marker]
    grace = {"gprev=": "grace-steal-previous=", "gnext=": "grace-steal-following=", "gmake=": "grace-make-time="}
    for prefix, expanded in grace.items():
        if marker.startswith(prefix):
            return expanded + marker[len(prefix):]
    return marker


@dataclass
class V2Tone:
    pitch: str
    instrument: str = ""
    markers: list[str] = field(default_factory=list)


@dataclass
class V2Event:
    kind: str
    duration: str
    tones: list[V2Tone] = field(default_factory=list)
    instrument: str = ""
    markers: list[str] = field(default_factory=list)


@dataclass
class V2Voice:
    identifier: str
    staff: str
    events: list[V2Event] = field(default_factory=list)


@dataclass
class V2Measure:
    index: int
    number: str
    attributes: list[str] = field(default_factory=list)
    directions: list[tuple[str, str]] = field(default_factory=list)
    voices: list[V2Voice] = field(default_factory=list)


@dataclass
class V2Instrument:
    alias: str
    xml_id: str
    name: str = ""
    sound: str = ""


@dataclass
class V2Part:
    identifier: str
    name: str = ""
    instruments: list[V2Instrument] = field(default_factory=list)
    measures: list[V2Measure] = field(default_factory=list)


@dataclass
class V2Score:
    title: str = ""
    creator: str = ""
    source: str = ""
    parts: list[V2Part] = field(default_factory=list)

    def render(self) -> str:
        header = 'score format="concise-music-v2"'
        for key, value in (("title", self.title), ("creator", self.creator), ("source", self.source)):
            if value:
                header += f" {key}={_q(value)}"
        lines = [header + " {"]
        for part in self.parts:
            line = f"part {_a(part.identifier)}"
            if part.name:
                line += f" name={_q(part.name)}"
            lines.append(line + " {")
            for instrument in part.instruments:
                line = f"    instrument alias={_q(instrument.alias)} id={_q(instrument.xml_id)}"
                if instrument.name:
                    line += f" name={_q(instrument.name)}"
                if instrument.sound:
                    line += f" sound={_q(instrument.sound)}"
                lines.append("  " + line.strip() + ";")
            for measure in part.measures:
                measure_head = f"  m{measure.index}"
                if measure.number != str(measure.index):
                    measure_head += f" number={_q(measure.number)}"
                lines.append(measure_head + " {")
                if measure.attributes:
                    lines.append("    attributes [" + "; ".join(_q(x) for x in measure.attributes) + "];")
                if measure.directions:
                    values = [f"at {offset} value={_q(value)}" for offset, value in measure.directions]
                    lines.append("    directions [" + "; ".join(values) + "];")
                for voice in measure.voices:
                    rendered_events = []
                    for event in voice.events:
                        if event.kind == "skip":
                            rendered_events.append(f"skip/{event.duration}")
                            continue
                        if event.kind == "note":
                            tone = event.tones[0]
                            line = f"{_a(tone.pitch)}/{event.duration}"
                            if event.instrument:
                                line += f" @{_a(event.instrument)}"
                            if tone.markers:
                                line += " {" + "; ".join(x for x in tone.markers) + "}"
                            rendered_events.append(line)
                            continue
                        line = f"chord /{event.duration}"
                        if event.instrument:
                            line += f" @{_a(event.instrument)}"
                        rendered_tones = []
                        for tone in event.tones:
                            tone_line = _a(tone.pitch)
                            if tone.instrument:
                                tone_line += f" @{_a(tone.instrument)}"
                            if tone.markers:
                                tone_line += " {" + "; ".join(x for x in tone.markers) + "}"
                            rendered_tones.append(tone_line)
                        line += " { " + " ".join(rendered_tones) + " }"
                        if event.markers:
                            line += " {" + "; ".join(x for x in event.markers) + "}"
                        rendered_events.append(line)
                    lines.append(
                        f"    v{voice.identifier}s{voice.staff} {{ "
                        + "  ".join(rendered_events) + " }"
                    )
                lines.append("  }")
            lines.append("}")
        lines.append("}")
        return "\n".join(lines) + "\n"


def from_semantic_score(score: SemanticScore) -> V2Score:
    result = V2Score(score.title, "; ".join(score.creators), score.source)
    for part in score.parts:
        target_part = V2Part(part.identifier, part.name)
        target_part.instruments = [
            V2Instrument(part.instrument_aliases[item.xml_id], item.xml_id, item.name, item.sound)
            for item in part.instruments
        ]
        multiple_instruments = len(part.instruments) > 1
        for measure in part.measures:
            target_measure = V2Measure(
                measure.index,
                measure.number,
                list(measure.attributes),
                [(frac(offset), value) for offset, value in measure.directions],
            )
            voices: dict[tuple[str, str], Voice] = {}
            for event in measure.events:
                key = (event.provenance.voice, event.provenance.staff)
                voices.setdefault(key, Voice()).events.append(event)
            for (voice_id, staff), voice in voices.items():
                target_voice = V2Voice(voice_id, staff)
                grouped: list[tuple[Fraction, Fraction, list[SemanticNoteEvent]]] = []
                for order, event in sorted(enumerate(voice.events), key=lambda x: (x[1].onset, x[0])):
                    if event.chord and grouped and grouped[-1][0] == event.onset and grouped[-1][1] == event.duration:
                        grouped[-1][2].append(event)
                    else:
                        grouped.append((event.onset, event.duration, [event]))
                cursor = Fraction(0)
                for onset, duration, events in grouped:
                    if onset > cursor:
                        target_voice.events.append(V2Event("skip", frac(onset - cursor)))
                    tones = [
                        V2Tone(
                            render_note_content(event.content),
                            event.instrument_alias if multiple_instruments and len(events) > 1 else "",
                            _markers(event),
                        )
                        for event in events
                    ]
                    event_instrument = ""
                    identities = [event.instrument_alias for event in events if event.instrument_alias]
                    if multiple_instruments and len(set(identities)) == 1 and len(identities) == len(events):
                        event_instrument = identities[0]
                        for tone in tones:
                            tone.instrument = ""
                    chord_markers = [_expand_marker(x) for x in normalized_arpeggiations(events)]
                    target_voice.events.append(
                        V2Event("note" if len(tones) == 1 else "chord", frac(duration), tones, event_instrument, chord_markers)
                    )
                    cursor = max(cursor, onset + duration)
                target_measure.voices.append(target_voice)
            target_part.measures.append(target_measure)
        result.parts.append(target_part)
    return result


TOKEN_RE = re.compile(r'\s*(?:("(?:\\.|[^"\\])*")|([{}\[\];=])|([^\s{}\[\];=]+))')


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    position = 0
    while position < len(text):
        match = TOKEN_RE.match(text, position)
        if not match:
            if text[position:].strip():
                raise V2ParseError(f"invalid input near offset {position}")
            break
        position = match.end()
        tokens.append(next(value for value in match.groups() if value is not None))
    return tokens


class _Parser:
    def __init__(self, text: str):
        self.tokens = _tokenize(text)
        self.index = 0

    def peek(self) -> str:
        return self.tokens[self.index] if self.index < len(self.tokens) else ""

    def take(self, expected: str | None = None) -> str:
        token = self.peek()
        if not token or (expected is not None and token != expected):
            raise V2ParseError(f"expected {expected or 'token'}, found {token or 'end of input'}")
        self.index += 1
        return token

    def value(self) -> str:
        token = self.take()
        return json.loads(token) if token.startswith('"') else token

    def field(self, name: str) -> str:
        self.take(name); self.take("="); return self.value()

    def optional_fields(self, allowed: set[str]) -> dict[str, str]:
        result = {}
        while self.peek() in allowed:
            name = self.take(); self.take("="); result[name] = self.value()
        return result

    def string_list(self) -> list[str]:
        self.take("["); values = []
        while self.peek() != "]":
            values.append(self.value())
            if self.peek() == ";": self.take(";")
            elif self.peek() != "]": raise V2ParseError("expected ';' or ']'")
        self.take("]"); return values

    def properties(self) -> list[str]:
        self.take("{"); values = []
        while self.peek() != "}":
            pieces = []
            while self.peek() not in {";", "}"}:
                pieces.append(self.take())
            if not pieces:
                raise V2ParseError("empty property")
            values.append("".join(pieces))
            if self.peek() == ";": self.take(";")
        self.take("}")
        return values

    def tone(self) -> V2Tone:
        pitch = self.value(); instrument = ""; markers = []
        if self.peek().startswith("@"):
            instrument = self.take()[1:]
        if self.peek() == "{": markers = self.properties()
        return V2Tone(pitch, instrument, markers)

    def event(self) -> V2Event:
        token = self.take()
        if token.startswith("skip/"):
            return V2Event("skip", token[5:])
        if token != "chord":
            if "/" not in token: raise V2ParseError(f"unknown event {token}")
            pitch, duration = token.rsplit("/", 1)
            instrument = ""; markers = []
            if self.peek().startswith("@"):
                instrument = self.take()[1:]
            if self.peek() == "{": markers = self.properties()
            return V2Event("note", duration, [V2Tone(pitch, markers=markers)], instrument)
        duration = self.take()
        if not duration.startswith("/"): raise V2ParseError("chord requires /duration")
        instrument = ""
        if self.peek().startswith("@"):
            instrument = self.take()[1:]
        self.take("{"); tones = []
        while self.peek() != "}": tones.append(self.tone())
        self.take("}")
        markers = self.properties() if self.peek() == "{" else []
        return V2Event("chord", duration[1:], tones, instrument, markers)

    def voice(self) -> V2Voice:
        scope = self.take()
        match = re.fullmatch(r"v(.+)s([^s]+)", scope)
        if not match: raise V2ParseError("invalid voice/staff scope")
        identifier, staff = match.groups(); self.take("{")
        events = []
        while self.peek() != "}": events.append(self.event())
        self.take("}"); return V2Voice(identifier, staff, events)

    def measure(self) -> V2Measure:
        scope = self.take()
        if not re.fullmatch(r"m\d+", scope): raise V2ParseError("invalid measure scope")
        index = int(scope[1:]); fields = self.optional_fields({"number"}); number = fields.get("number", str(index)); self.take("{")
        result = V2Measure(index, number)
        while self.peek() != "}":
            if self.peek() == "attributes":
                self.take(); result.attributes = self.string_list(); self.take(";")
            elif self.peek() == "directions":
                self.take(); self.take("[")
                while self.peek() != "]":
                    self.take("at"); offset = self.value(); value = self.field("value")
                    result.directions.append((offset, value))
                    if self.peek() == ";": self.take(";")
                self.take("]"); self.take(";")
            elif self.peek().startswith("v"): result.voices.append(self.voice())
            else: raise V2ParseError(f"unknown measure item {self.peek()}")
        self.take("}"); return result

    def part(self) -> V2Part:
        self.take("part"); identifier = self.value(); fields = self.optional_fields({"name"}); self.take("{")
        result = V2Part(identifier, fields.get("name", ""))
        while self.peek() != "}":
            if self.peek() == "instrument":
                self.take(); alias = self.field("alias"); xml_id = self.field("id")
                values = self.optional_fields({"name", "sound"}); self.take(";")
                result.instruments.append(V2Instrument(alias, xml_id, values.get("name", ""), values.get("sound", "")))
            else: result.measures.append(self.measure())
        self.take("}"); return result

    def score(self) -> V2Score:
        self.take("score")
        if self.field("format") != "concise-music-v2": raise V2ParseError("unsupported format")
        fields = self.optional_fields({"title", "creator", "source"}); self.take("{")
        parts = []
        while self.peek() != "}": parts.append(self.part())
        self.take("}")
        if self.peek(): raise V2ParseError("trailing input")
        return V2Score(fields.get("title", ""), fields.get("creator", ""), fields.get("source", ""), parts)


def parse_v2(text: str) -> V2Score:
    return _Parser(text).score()


def render_cmusic_v2(score: SemanticScore) -> str:
    return from_semantic_score(score).render()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        score = import_musicxml(load_xml(args.input), args.input.name)
        args.output.write_text(render_cmusic_v2(score), encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
