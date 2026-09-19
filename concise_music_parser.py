#!/usr/bin/env python3
"""Parser and lossless AST for the canonical concise-music-v1 format."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Iterable


class ParseError(ValueError):
    def __init__(self, message: str, line: int = 0):
        prefix = f"line {line}: " if line else ""
        super().__init__(prefix + message)
        self.line = line


def _scan_parts(text: str, delimiter: str | None = None, whitespace: bool = False) -> list[str]:
    """Split outside JSON strings and (), [], or {} nesting."""
    parts: list[str] = []
    start = 0
    quote = False
    escape = False
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    for index, char in enumerate(text):
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                quote = False
            continue
        if char == '"':
            quote = True
        elif char in "([{":
            stack.append(char)
        elif char in ")]}":
            if not stack or stack[-1] != pairs[char]:
                raise ParseError(f"unmatched {char!r}")
            stack.pop()
        elif not stack and ((delimiter is not None and char == delimiter) or (whitespace and char.isspace())):
            if start < index:
                parts.append(text[start:index])
            start = index + 1
    if quote:
        raise ParseError("unterminated quoted string")
    if stack:
        raise ParseError(f"unterminated {stack[-1]!r} group")
    # Delimiter-based splitting preserves a trailing empty field. This matters
    # for valid empty measures (``m12 |``), and lets callers reject accidental
    # trailing separators in contexts where an empty field is not valid.
    if start < len(text) or delimiter is not None:
        parts.append(text[start:])
    return parts


def split_tokens(text: str) -> list[str]:
    return _scan_parts(text, whitespace=True)


def split_top_level(text: str, delimiter: str) -> list[str]:
    return _scan_parts(text, delimiter=delimiter)


def decoded_value(token: str) -> str:
    value = token.split("=", 1)[1] if "=" in token else token
    if value.startswith('"'):
        try:
            result = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ParseError(f"invalid JSON string in {token!r}: {exc.msg}") from exc
        if not isinstance(result, str):
            raise ParseError(f"property value must be a string: {token!r}")
        return result
    return value


@dataclass(frozen=True)
class MarkerGroup:
    markers: tuple[str, ...]

    def render(self) -> str:
        return "{" + ",".join(self.markers) + "}"


def marker_groups(text: str) -> tuple[MarkerGroup, ...]:
    groups: list[MarkerGroup] = []
    quote = False
    escape = False
    depth = 0
    start = -1
    for index, char in enumerate(text):
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                quote = False
            continue
        if char == '"':
            quote = True
        elif char == "{":
            if depth == 0:
                start = index + 1
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                raise ParseError("unmatched '}' in event")
            if depth == 0:
                assert start >= 0
                groups.append(MarkerGroup(tuple(split_top_level(text[start:index], ","))))
    if quote or depth:
        raise ParseError("unterminated marker group")
    return tuple(groups)


def _without_marker_groups(text: str) -> str:
    result: list[str] = []
    quote = False
    escape = False
    depth = 0
    for char in text:
        if quote:
            if depth == 0:
                result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                quote = False
            continue
        if char == '"':
            quote = True
            if depth == 0:
                result.append(char)
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif depth == 0:
            result.append(char)
    return "".join(result)


@dataclass(frozen=True)
class NoteAtom:
    raw: str
    symbol: str
    instrument: str | None
    marker_groups: tuple[MarkerGroup, ...]

    def render(self) -> str:
        return self.raw


def parse_note_atom(text: str) -> NoteAtom:
    if not text:
        raise ParseError("empty note or chord member")
    groups = marker_groups(text)
    plain = _without_marker_groups(text)
    if "@" in plain:
        symbol, instrument = plain.rsplit("@", 1)
        if not symbol or not instrument:
            raise ParseError(f"invalid instrument annotation: {text!r}")
    else:
        symbol, instrument = plain, None
    if not symbol:
        raise ParseError(f"missing note symbol: {text!r}")
    return NoteAtom(text, symbol, instrument, groups)


@dataclass(frozen=True)
class Gap:
    duration: Fraction
    duration_text: str

    def render(self) -> str:
        return "_" + self.duration_text


@dataclass(frozen=True)
class MusicalEvent:
    raw_head: str
    duration: Fraction
    duration_text: str
    notes: tuple[NoteAtom, ...]
    common_suffix: str = ""
    common_markers: tuple[MarkerGroup, ...] = ()
    common_instrument: str | None = None

    @property
    def is_chord(self) -> bool:
        return len(self.notes) > 1 or self.raw_head.startswith("[")

    def render(self) -> str:
        return self.raw_head + "/" + self.duration_text


Event = Gap | MusicalEvent
_EVENT_DURATION_RE = re.compile(r"/(\d+(?:/\d+)?)$")


def parse_event(token: str) -> Event:
    if token.startswith("_"):
        duration_text = token[1:]
        try:
            return Gap(Fraction(duration_text), duration_text)
        except (ValueError, ZeroDivisionError) as exc:
            raise ParseError(f"invalid gap duration: {token!r}") from exc

    match = _EVENT_DURATION_RE.search(token)
    if not match:
        raise ParseError(f"event has no valid duration: {token!r}")
    raw_head = token[: match.start()]
    duration_text = match.group(1)
    try:
        duration = Fraction(duration_text)
    except (ValueError, ZeroDivisionError) as exc:
        raise ParseError(f"invalid event duration: {duration_text!r}") from exc

    if raw_head.startswith("["):
        quote = False
        escape = False
        depth = 0
        closing = -1
        for index, char in enumerate(raw_head):
            if quote:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    quote = False
                continue
            if char == '"':
                quote = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing < 0:
            raise ParseError(f"unterminated chord: {token!r}")
        members = split_top_level(raw_head[1:closing], ",")
        if not members:
            raise ParseError("empty chord")
        notes = tuple(parse_note_atom(member) for member in members)
        suffix = raw_head[closing + 1 :]
        suffix_groups = marker_groups(suffix)
        plain_suffix = _without_marker_groups(suffix)
        if plain_suffix:
            if not plain_suffix.startswith("@") or len(plain_suffix) == 1:
                raise ParseError(f"invalid chord suffix: {suffix!r}")
            common_instrument = plain_suffix[1:]
        else:
            common_instrument = None
        return MusicalEvent(raw_head, duration, duration_text, notes, suffix, suffix_groups, common_instrument)

    note = parse_note_atom(raw_head)
    return MusicalEvent(raw_head, duration, duration_text, (note,))


@dataclass(frozen=True)
class Voice:
    identifier: str | None
    events: tuple[Event, ...]

    def render(self) -> str:
        body = " ".join(event.render() for event in self.events)
        return f"v{self.identifier}: {body}" if self.identifier is not None else body


@dataclass(frozen=True)
class TimedDirection:
    offset: Fraction
    offset_text: str
    value: str


@dataclass(frozen=True)
class Measure:
    number: str
    prefix_tokens: tuple[str, ...]
    voices: tuple[Voice, ...]

    @property
    def directions(self) -> tuple[TimedDirection, ...]:
        result = []
        for token in self.prefix_tokens:
            if token.startswith("@") and ":" in token:
                offset_text, value = token[1:].split(":", 1)
                try:
                    result.append(TimedDirection(Fraction(offset_text), offset_text, value))
                except (ValueError, ZeroDivisionError) as exc:
                    raise ParseError(f"invalid direction offset: {token!r}") from exc
        return tuple(result)

    @property
    def attributes(self) -> tuple[str, ...]:
        return tuple(token for token in self.prefix_tokens if not token.startswith("@"))

    def render(self) -> str:
        prefix = "m" + self.number
        if self.prefix_tokens:
            prefix += " " + " ".join(self.prefix_tokens)
        body = " ; ".join(voice.render() for voice in self.voices)
        return prefix + " |" + (" " + body if body else "")


@dataclass(frozen=True)
class Instrument:
    alias: str
    fields: tuple[str, ...]

    def render(self) -> str:
        return "@instrument " + self.alias + (" " + " ".join(self.fields) if self.fields else "")


@dataclass
class Part:
    identifier: str
    fields: tuple[str, ...]
    instruments: list[Instrument] = field(default_factory=list)
    measures: list[Measure] = field(default_factory=list)

    def render_lines(self) -> Iterable[str]:
        yield "@part " + self.identifier + (" " + " ".join(self.fields) if self.fields else "")
        yield from (instrument.render() for instrument in self.instruments)
        yield from (measure.render() for measure in self.measures)


@dataclass
class Score:
    fields: tuple[str, ...]
    parts: list[Part] = field(default_factory=list)

    @property
    def format(self) -> str | None:
        for field_token in self.fields:
            if field_token.startswith("format="):
                return decoded_value(field_token)
        return None

    def render(self) -> str:
        lines = ["@score" + (" " + " ".join(self.fields) if self.fields else "")]
        for part in self.parts:
            lines.extend(part.render_lines())
        return "\n".join(lines) + "\n"


def _parse_voice(segment: str) -> Voice:
    match = re.match(r"^v([^:\s]+):(?: (.*))?$", segment)
    if match:
        identifier = match.group(1)
        body = match.group(2) or ""
    else:
        identifier = None
        body = segment
    events = tuple(parse_event(token) for token in split_tokens(body)) if body else ()
    return Voice(identifier, events)


def _parse_measure(line: str) -> Measure:
    pieces = split_top_level(line, "|")
    if len(pieces) != 2:
        raise ParseError("measure must contain exactly one top-level '|' separator")
    prefix = pieces[0].rstrip()
    body = pieces[1].lstrip()
    prefix_tokens = split_tokens(prefix)
    if not prefix_tokens or not prefix_tokens[0].startswith("m") or len(prefix_tokens[0]) == 1:
        raise ParseError("invalid measure identifier")
    voices = tuple(_parse_voice(segment.strip()) for segment in split_top_level(body, ";")) if body else ()
    if len(voices) > 1 and any(voice.identifier is None for voice in voices):
        raise ParseError("every segment must have a voice label when a measure has multiple voices")
    measure = Measure(prefix_tokens[0][1:], tuple(prefix_tokens[1:]), voices)
    _ = measure.directions  # Eagerly validate offsets.
    return measure


def parse(text: str) -> Score:
    lines = text.splitlines()
    if not lines:
        raise ParseError("empty concise-music document")
    try:
        header = split_tokens(lines[0])
    except ParseError as exc:
        raise ParseError(str(exc), 1) from exc
    if not header or header[0] != "@score":
        raise ParseError("document must begin with @score", 1)
    score = Score(tuple(header[1:]))
    try:
        score_format = score.format
    except ParseError as exc:
        raise ParseError(str(exc), 1) from exc
    if score_format != "concise-music-v1":
        raise ParseError("unsupported or missing format (expected concise-music-v1)", 1)

    current_part: Part | None = None
    for line_number, line in enumerate(lines[1:], 2):
        if not line:
            raise ParseError("blank lines are not part of canonical concise-music-v1", line_number)
        try:
            if line.startswith("@part "):
                tokens = split_tokens(line)
                if len(tokens) < 2:
                    raise ParseError("missing part identifier")
                current_part = Part(tokens[1], tuple(tokens[2:]))
                score.parts.append(current_part)
            elif line.startswith("@instrument "):
                if current_part is None:
                    raise ParseError("instrument appears before a part")
                tokens = split_tokens(line)
                if len(tokens) < 2:
                    raise ParseError("missing instrument alias")
                current_part.instruments.append(Instrument(tokens[1], tuple(tokens[2:])))
            elif line.startswith("m"):
                if current_part is None:
                    raise ParseError("measure appears before a part")
                current_part.measures.append(_parse_measure(line))
            else:
                raise ParseError(f"unknown line type: {line[:24]!r}")
        except ParseError as exc:
            if exc.line:
                raise
            raise ParseError(str(exc), line_number) from exc
    return score


def parse_file(path: Path) -> Score:
    return parse(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="concise-music-v1 file")
    parser.add_argument("--roundtrip", action="store_true", help="verify byte-identical canonical rendering")
    args = parser.parse_args()
    original = args.input.read_text(encoding="utf-8")
    score = parse(original)
    rendered = score.render()
    if args.roundtrip and rendered != original:
        print("valid document, but canonical rendering differs")
        return 2
    measure_count = sum(len(part.measures) for part in score.parts)
    print(f"valid {score.format}: parts={len(score.parts)} measures={measure_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
