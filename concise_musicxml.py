#!/usr/bin/env python3
"""Convert MusicXML (including compressed .mxl) to compact, LLM-readable text.

The output is intentionally line-oriented and deterministic.  Durations are
fractions of a quarter note, so ``C4/1`` is a quarter note and ``r/1/2`` is an
eighth-note rest.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child(node: ET.Element, name: str) -> ET.Element | None:
    return next((x for x in node if local(x.tag) == name), None)


def text(node: ET.Element, name: str, default: str = "") -> str:
    item = child(node, name)
    return (item.text or default).strip() if item is not None else default


def descendants(node: ET.Element, name: str):
    return (x for x in node.iter() if local(x.tag) == name)


def quote(value: str) -> str:
    """A compact, unambiguous JSON string."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def frac(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def safe_id(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip()) or "?"


@dataclass
class Event:
    start: Fraction
    duration: Fraction
    token: str
    chord: bool = False


@dataclass
class Voice:
    events: list[Event] = field(default_factory=list)
    last_onset: Fraction = Fraction(0)


def load_xml(path: Path) -> ET.Element:
    data: bytes
    if path.suffix.lower() == ".mxl" or zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith((".xml", ".musicxml"))]
            preferred = [n for n in names if not n.upper().startswith("META-INF/")]
            if not preferred:
                raise ValueError("compressed MusicXML contains no score XML file")
            data = zf.read(preferred[0])
    else:
        data = path.read_bytes()
    return ET.parse(io.BytesIO(data)).getroot()


def pitch_token(note: ET.Element) -> str:
    if child(note, "rest") is not None:
        display = child(note, "rest")
        step = text(display, "display-step") if display is not None else ""
        octave = text(display, "display-octave") if display is not None else ""
        return "r" + (f"@{step}{octave}" if step and octave else "")
    if child(note, "unpitched") is not None:
        unpitched = child(note, "unpitched")
        step = text(unpitched, "display-step", "x")
        octave = text(unpitched, "display-octave")
        return f"x{step}{octave}"
    pitch = child(note, "pitch")
    if pitch is None:
        return "?"
    step = text(pitch, "step", "?")
    octave = text(pitch, "octave", "?")
    alter_raw = text(pitch, "alter", "0")
    try:
        alter = Fraction(alter_raw)
    except ValueError:
        alter = Fraction(0)
    accidental = {Fraction(-2): "bb", Fraction(-1): "b", Fraction(0): "", Fraction(1): "#", Fraction(2): "##"}.get(alter)
    if accidental is None:
        accidental = f"({'+' if alter > 0 else ''}{frac(alter)})"
    return f"{step}{accidental}{octave}"


def note_suffix(note: ET.Element) -> str:
    marks: list[str] = []
    ties = {x.get("type", "") for x in descendants(note, "tie")}
    if "stop" in ties:
        marks.append("<")
    if "start" in ties:
        marks.append(">")
    # Slurs are separate from ties and retain their MusicXML number so nested
    # and overlapping phrases can be paired.  Other slur attributes describe
    # engraving and are intentionally omitted.
    notations = child(note, "notations")
    for slur in descendants(notations, "slur") if notations is not None else ():
        slur_type = slur.get("type", "")
        if slur_type in {"start", "stop"}:
            number = safe_id(slur.get("number", "1"))
            marks.append(f"s{number}{'>' if slur_type == 'start' else '<'}")
    if child(note, "grace") is not None:
        marks.append("g")
    if text(note, "voice") and text(note, "voice") != "1":
        pass  # represented in the voice label
    lyrics = []
    for lyric in (x for x in note if local(x.tag) == "lyric"):
        syllables = [x.text.strip() for x in descendants(lyric, "text") if x.text and x.text.strip()]
        if syllables:
            lyrics.append(" ".join(syllables))
    if lyrics:
        marks.append("ly=" + quote("/".join(lyrics)))
    return ("{" + ",".join(marks) + "}") if marks else ""


def attribute_tokens(attributes: ET.Element, divisions: int) -> tuple[list[str], int]:
    out: list[str] = []
    raw_div = text(attributes, "divisions")
    if raw_div:
        divisions = max(1, int(raw_div))
        out.append(f"div={divisions}")
    for key in (x for x in attributes if local(x.tag) == "key"):
        fifths = text(key, "fifths")
        mode = text(key, "mode")
        if fifths:
            out.append("key=" + fifths + (":" + safe_id(mode) if mode else ""))
    for time in (x for x in attributes if local(x.tag) == "time"):
        beats = text(time, "beats")
        beat_type = text(time, "beat-type")
        symbol = time.get("symbol", "")
        if beats and beat_type:
            out.append(f"time={beats}/{beat_type}" + (f":{symbol}" if symbol else ""))
    for clef in (x for x in attributes if local(x.tag) == "clef"):
        number = clef.get("number", "1")
        sign, line = text(clef, "sign"), text(clef, "line")
        octave = text(clef, "clef-octave-change")
        if sign:
            out.append(f"clef{number}={sign}{line}" + (f"^{octave}" if octave else ""))
    transpose = child(attributes, "transpose")
    if transpose is not None:
        chromatic = text(transpose, "chromatic")
        if chromatic:
            out.append(f"transpose={chromatic}")
    return out, divisions


def direction_tokens(direction: ET.Element) -> list[str]:
    out: list[str] = []
    sound = child(direction, "sound")
    if sound is not None and sound.get("tempo"):
        out.append("tempo=" + sound.get("tempo", ""))
    for met in descendants(direction, "metronome"):
        per_minute = text(met, "per-minute")
        beat_unit = text(met, "beat-unit")
        if per_minute and not out:
            out.append(f"tempo={per_minute}" + (f"({beat_unit})" if beat_unit else ""))
    for dynamics in descendants(direction, "dynamics"):
        values = [local(x.tag) for x in dynamics if isinstance(x.tag, str)]
        if values:
            out.append("dyn=" + "+".join(values))
    words = [x.text.strip() for x in descendants(direction, "words") if x.text and x.text.strip()]
    if words:
        out.append("text=" + quote(" ".join(words)))
    for wedge in descendants(direction, "wedge"):
        if wedge.get("type"):
            out.append("wedge=" + wedge.get("type", ""))
    return out


def render_voice(voice: Voice) -> str:
    grouped: dict[tuple[Fraction, Fraction], list[str]] = defaultdict(list)
    for event in voice.events:
        grouped[(event.start, event.duration)].append(event.token)
    cursor = Fraction(0)
    tokens: list[str] = []
    for (start, duration), pitches in sorted(grouped.items()):
        if start > cursor:
            tokens.append("_" + frac(start - cursor))
        head = pitches[0] if len(pitches) == 1 else "[" + ",".join(pitches) + "]"
        tokens.append(head + "/" + (frac(duration) if duration else "0"))
        cursor = max(cursor, start + duration)
    return " ".join(tokens)


def convert(root: ET.Element, source: str = "") -> str:
    root_name = local(root.tag)
    if root_name not in {"score-partwise", "score-timewise"}:
        raise ValueError(f"unsupported root element: {root_name}")
    if root_name == "score-timewise":
        raise ValueError("score-timewise MusicXML is not supported; export as score-partwise")

    title = text(root, "movement-title")
    work = child(root, "work")
    if not title and work is not None:
        title = text(work, "work-title")
    creators = [x.text.strip() for x in descendants(root, "creator") if x.text and x.text.strip()]
    header = ["@score", "format=concise-music-v1"]
    if title:
        header.append("title=" + quote(title))
    if creators:
        header.append("creator=" + quote("; ".join(creators)))
    if source:
        header.append("source=" + quote(source))
    lines = [" ".join(header)]

    part_names: dict[str, str] = {}
    part_list = child(root, "part-list")
    if part_list is not None:
        for score_part in (x for x in part_list if local(x.tag) == "score-part"):
            part_names[score_part.get("id", "")] = text(score_part, "part-name")

    for part in (x for x in root if local(x.tag) == "part"):
        part_id = part.get("id", "?")
        part_line = f"@part {safe_id(part_id)}"
        if part_names.get(part_id):
            part_line += " name=" + quote(part_names[part_id])
        lines.append(part_line)
        divisions = 1
        for measure in (x for x in part if local(x.tag) == "measure"):
            number = measure.get("number", "?")
            attrs: list[str] = []
            annotations: list[tuple[Fraction, str]] = []
            voices: dict[str, Voice] = defaultdict(Voice)
            cursor = Fraction(0)
            for item in measure:
                kind = local(item.tag)
                if kind == "attributes":
                    found, divisions = attribute_tokens(item, divisions)
                    attrs.extend(found)
                elif kind == "backup":
                    cursor -= Fraction(int(text(item, "duration", "0")), divisions)
                elif kind == "forward":
                    cursor += Fraction(int(text(item, "duration", "0")), divisions)
                elif kind == "direction":
                    offset = Fraction(int(text(item, "offset", "0") or 0), divisions)
                    annotations.extend((cursor + offset, x) for x in direction_tokens(item))
                elif kind == "barline":
                    repeat = child(item, "repeat")
                    if repeat is not None:
                        attrs.append("repeat=" + repeat.get("direction", "?"))
                    ending = child(item, "ending")
                    if ending is not None:
                        attrs.append("ending=" + ending.get("number", "?") + ":" + ending.get("type", "?"))
                elif kind == "note":
                    duration_raw = text(item, "duration", "0")
                    duration = Fraction(int(duration_raw or 0), divisions)
                    voice_id = text(item, "voice", "1")
                    staff = text(item, "staff", "1")
                    key = voice_id + (f"s{staff}" if staff != "1" else "")
                    is_chord = child(item, "chord") is not None
                    start = voices[key].last_onset if is_chord else cursor
                    token = pitch_token(item) + note_suffix(item)
                    voices[key].events.append(Event(start, duration, token, is_chord))
                    if not is_chord:
                        voices[key].last_onset = start
                        if child(item, "grace") is None:
                            cursor += duration
            prefix = f"m{safe_id(number)}"
            if attrs:
                prefix += " " + " ".join(attrs)
            for at, value in sorted(annotations):
                prefix += f" @{frac(at)}:{value}"
            if not voices:
                lines.append(prefix + " |")
            elif len(voices) == 1:
                lines.append(prefix + " | " + render_voice(next(iter(voices.values()))))
            else:
                rendered = [f"v{safe_id(k)}: {render_voice(v)}" for k, v in sorted(voices.items())]
                lines.append(prefix + " | " + " ; ".join(rendered))
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="MusicXML .xml, .musicxml, or compressed .mxl file")
    parser.add_argument("-o", "--output", type=Path, help="output path (default: stdout)")
    parser.add_argument("--no-source", action="store_true", help="omit the source filename from the header")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = convert(load_xml(args.input), "" if args.no_source else args.input.name)
        if args.output:
            args.output.write_text(result, encoding="utf-8")
        else:
            sys.stdout.write(result)
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
