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


def notation_elements(note: ET.Element, name: str):
    """Yield a notation type across every <notations> block on a note."""
    return (
        item
        for notations in note
        if local(notations.tag) == "notations"
        for item in notations.iter()
        if local(item.tag) == name
    )


def quote(value: str) -> str:
    """A compact, unambiguous JSON string."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def frac(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def safe_id(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip()) or "?"


def compact_text(value: str) -> str:
    """Quote free text used inside compact note markers."""
    return quote(value.strip())


def compact_atom(value: str) -> str:
    """Use an unquoted atom when safe, otherwise a JSON string."""
    value = value.strip()
    return value if re.fullmatch(r"[A-Za-z0-9_.#/+%\-]+", value) else quote(value)


@dataclass
class Event:
    start: Fraction
    duration: Fraction
    token: str
    chord: bool = False
    instrument: str = ""
    arpeggiations: tuple[tuple[str, str, str], ...] = ()


@dataclass
class Voice:
    events: list[Event] = field(default_factory=list)
    last_onset: Fraction = Fraction(0)


@dataclass(frozen=True)
class InstrumentDefinition:
    xml_id: str
    name: str = ""
    sound: str = ""


@dataclass
class NavigationState:
    segnos: int = 0
    codas: int = 0

    def next_segno(self) -> str:
        self.segnos += 1
        return f"S{self.segnos}"

    def next_coda(self) -> str:
        self.codas += 1
        return f"C{self.codas}"


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


def pitch_token(note: ET.Element, instrument_aliases: dict[str, str]) -> str:
    if child(note, "rest") is not None:
        # display-step/display-octave only position the rest glyph vertically;
        # they are engraving data, not a sounding pitch or musical event.
        return "r"
    if child(note, "unpitched") is not None:
        instrument = child(note, "instrument")
        instrument_id = instrument.get("id", "").strip() if instrument is not None else ""
        if instrument_id and instrument_id in instrument_aliases:
            return "x@" + instrument_aliases[instrument_id]
        # With no semantic reference, retain display position only as an
        # explicitly unknown fallback.  Never infer identity from it.
        unpitched = child(note, "unpitched")
        step = text(unpitched, "display-step")
        octave = text(unpitched, "display-octave")
        position = step + octave
        return f"x?({position})" if position else "x?"
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


def span_marker(element: ET.Element, prefix: str) -> str:
    """Compact marker for a numbered start/stop note relationship."""
    relation_type = element.get("type", "")
    number = safe_id(element.get("number", "1"))
    symbol = {"start": ">", "stop": "<", "continue": "~"}.get(relation_type, ":" + relation_type)
    marker = prefix + number + symbol
    value = (element.text or "").strip()
    return marker + (":" + compact_text(value) if value else "")


TRILL_SOUND_ATTRIBUTES = (
    ("start-note", "start"),
    ("trill-step", "step"),
    ("two-note-turn", "turn"),
    ("accelerate", "accel"),
    ("beats", "beats"),
    ("first-beat", "first"),
    ("second-beat", "second"),
    ("last-beat", "last"),
)


def trill_semantics(element: ET.Element) -> str:
    values = [f"{short}={element.get(attribute)}" for attribute, short in TRILL_SOUND_ATTRIBUTES if element.get(attribute)]
    return "(" + ";".join(values) + ")" if values else ""


def technical_markers(technical: ET.Element) -> list[str]:
    values: list[str] = []
    for indication in technical:
        name = local(indication.tag)
        value = (indication.text or "").strip()
        if name == "harmonic":
            kinds = [local(x.tag) for x in indication if local(x.tag) in {"natural", "artificial"}]
            pitches = [local(x.tag).removesuffix("-pitch") for x in indication if local(x.tag).endswith("-pitch")]
            detail = "+".join(kinds + pitches)
            values.append("harmonic" + (":" + detail if detail else ""))
        elif name == "bend":
            details: list[str] = []
            alter = text(indication, "bend-alter")
            if alter:
                details.append("alter=" + alter)
            if child(indication, "pre-bend") is not None:
                details.append("pre-bend")
            release = child(indication, "release")
            if release is not None:
                details.append("release" + ("@" + release.get("offset", "") if release.get("offset") else ""))
            if child(indication, "with-bar") is not None:
                details.append("with-bar")
            values.append("bend" + (":" + "+".join(details) if details else ""))
        elif name in {"fingering", "heel", "toe"}:
            attributes = []
            if indication.get("alternate") == "yes":
                attributes.append("alt")
            if indication.get("substitution") == "yes":
                attributes.append("sub")
            suffix = "(" + ";".join(attributes) + ")" if attributes else ""
            values.append(name + (":" + compact_atom(value) if value else "") + suffix)
        elif name in {"hole", "arrow", "harmon-mute"}:
            details: list[str] = []
            for item in indication:
                item_name = local(item.tag)
                item_value = (item.text or "").strip()
                location = item.get("location", "")
                detail = item_name + ("=" + compact_atom(item_value) if item_value else "")
                if location:
                    detail += "@" + safe_id(location)
                details.append(detail)
            values.append(name + (":" + "+".join(details) if details else ""))
        elif name in {"hammer-on", "pull-off"}:
            relation_type = indication.get("type", "")
            number = safe_id(indication.get("number", "1"))
            symbol = {"start": ">", "stop": "<"}.get(relation_type, ":" + relation_type)
            values.append(name + number + symbol + (":" + compact_text(value) if value else ""))
        else:
            values.append(name + (":" + compact_atom(value) if value else ""))
    return values


def arpeggiation_markers(note: ET.Element) -> tuple[tuple[str, str, str], ...]:
    markers: list[tuple[str, str, str]] = []
    for item in notation_elements(note, "arpeggiate"):
        markers.append(("arp", safe_id(item.get("number", "1")), item.get("direction", "")))
    for item in notation_elements(note, "non-arpeggiate"):
        # top/bottom describe the drawn bracket endpoints; number carries
        # the semantic association and is sufficient after normalization.
        markers.append(("noarp", safe_id(item.get("number", "1")), ""))
    return tuple(markers)


def note_suffix(note: ET.Element) -> str:
    marks: list[str] = []
    playback_ties = {x.get("type", "") for x in (x for x in note if local(x.tag) == "tie")}
    notated_tie_types: set[str] = set()
    for tied in notation_elements(note, "tied"):
        tie_type = tied.get("type", "")
        number = safe_id(tied.get("number", "1"))
        symbol = {"start": ">", "stop": "<", "continue": "~"}.get(tie_type)
        if symbol:
            marks.append(f"t{number}{symbol}")
            notated_tie_types.add(tie_type)
        elif tie_type == "let-ring":
            marks.append("let-ring")
            notated_tie_types.add(tie_type)
    # A matching <tie> merely duplicates the notated relation. Keep a marker
    # only when playback semantics exist without a corresponding <tied>.
    for tie_type, symbol in (("stop", "<"), ("start", ">")):
        if tie_type in playback_ties and tie_type not in notated_tie_types:
            marks.append("soundtie" + symbol)
    # Slurs are separate from ties and retain their MusicXML number so nested
    # and overlapping phrases can be paired.  Other slur attributes describe
    # engraving and are intentionally omitted.
    notations = [x for x in note if local(x.tag) == "notations"]
    for slur in notation_elements(note, "slur"):
        slur_type = slur.get("type", "")
        if slur_type in {"start", "stop"}:
            number = safe_id(slur.get("number", "1"))
            marks.append(f"s{number}{'>' if slur_type == 'start' else '<'}")
    if notations:
        for articulations in notation_elements(note, "articulations"):
            values = []
            for articulation in articulations:
                name = local(articulation.tag)
                value = (articulation.text or "").strip()
                values.append(name + (":" + compact_text(value) if value else ""))
            if values:
                marks.append("art=" + "+".join(values))

        for technical in notation_elements(note, "technical"):
            values = technical_markers(technical)
            if values:
                marks.append("tech=" + "+".join(values))

        for fermata in notation_elements(note, "fermata"):
            shape = (fermata.text or "normal").strip() or "normal"
            marks.append("fer=" + safe_id(shape))

        for ornaments in notation_elements(note, "ornaments"):
            names: list[str] = []
            for ornament in ornaments:
                name = local(ornament.tag)
                if name == "tremolo":
                    trem_type = ornament.get("type", "single")
                    strokes = (ornament.text or "").strip()
                    names.append("trem:" + trem_type + (":" + strokes if strokes else ""))
                elif name == "wavy-line":
                    wave_type = ornament.get("type", "continue")
                    number = safe_id(ornament.get("number", "1"))
                    symbol = {"start": ">", "stop": "<", "continue": "~"}.get(wave_type, ":" + wave_type)
                    names.append(f"wav{number}{symbol}" + trill_semantics(ornament))
                elif name == "accidental-mark":
                    value = (ornament.text or "").strip()
                    names.append("acc:" + safe_id(value or "?"))
                else:
                    value = (ornament.text or "").strip()
                    names.append(name + trill_semantics(ornament) + (":" + compact_text(value) if value else ""))
            if names:
                marks.append("orn=" + "+".join(names))

        for tuplet in notation_elements(note, "tuplet"):
            tuplet_type = tuplet.get("type", "")
            if tuplet_type in {"start", "stop"}:
                number = safe_id(tuplet.get("number", "1"))
                marks.append(f"tup{number}{'>' if tuplet_type == 'start' else '<'}")

        for glissando in notation_elements(note, "glissando"):
            marks.append(span_marker(glissando, "gl"))
        for slide in notation_elements(note, "slide"):
            marker = span_marker(slide, "slide")
            # Bend-sound attributes affect slide realization; line-type and
            # other graphical attributes are deliberately excluded.
            sound = trill_semantics(slide)
            marks.append(marker + sound)

    time_modification = child(note, "time-modification")
    if time_modification is not None:
        actual = text(time_modification, "actual-notes")
        normal = text(time_modification, "normal-notes")
        if actual and normal:
            marker = f"tm={actual}:{normal}"
            normal_type = text(time_modification, "normal-type")
            if normal_type:
                dots = sum(1 for x in time_modification if local(x.tag) == "normal-dot")
                marker += ":" + safe_id(normal_type) + ("." * dots)
            marks.append(marker)

    grace = child(note, "grace")
    if grace is not None:
        marks.append("g")
        if grace.get("slash") == "yes":
            marks.append("gslash")
        for attribute, marker in (
            ("steal-time-previous", "gprev"),
            ("steal-time-following", "gnext"),
            ("make-time", "gmake"),
        ):
            if grace.get(attribute):
                marks.append(marker + "=" + grace.get(attribute, ""))
    if text(note, "voice") and text(note, "voice") != "1":
        pass  # represented in the voice label
    notehead = child(note, "notehead")
    if notehead is not None:
        shape = (notehead.text or "normal").strip() or "normal"
        if shape != "normal" or notehead.get("parentheses") == "yes":
            marker = "head=" + safe_id(shape)
            if notehead.get("parentheses") == "yes":
                marker += "(paren)"
            marks.append(marker)
    notehead_text = child(note, "notehead-text")
    if notehead_text is not None:
        values = [x.text.strip() for x in notehead_text if x.text and x.text.strip()]
        if values:
            marks.append("headtext=" + quote(" ".join(values)))

    for lyric_index, lyric in enumerate((x for x in note if local(x.tag) == "lyric"), 1):
        verse = safe_id(lyric.get("number") or lyric.get("name") or str(lyric_index))
        pieces: list[str] = []
        for item in lyric:
            name = local(item.tag)
            if name == "text" and item.text:
                pieces.append(item.text.strip())
            elif name == "elision":
                pieces.append((item.text or "‿").strip() or "‿")
        if pieces:
            marks.append(f"ly{verse}=" + quote("".join(pieces)))
        syllabic = text(lyric, "syllabic")
        if syllabic:
            marks.append(f"syl{verse}=" + syllabic)
        for extend in (x for x in lyric if local(x.tag) == "extend"):
            extend_type = extend.get("type", "continue")
            symbol = {"start": ">", "stop": "<", "continue": "~"}.get(extend_type, ":" + extend_type)
            marks.append(f"ext{verse}{symbol}")
        for flag in ("humming", "laughing", "end-line", "end-paragraph"):
            if child(lyric, flag) is not None:
                marks.append(f"ly{verse}:{flag}")
    return ("{" + ",".join(marks) + "}") if marks else ""


def attribute_tokens(attributes: ET.Element, divisions: int) -> tuple[list[str], int]:
    out: list[str] = []
    raw_div = text(attributes, "divisions")
    if raw_div:
        divisions = max(1, int(raw_div))
        out.append(f"div={divisions}")
    for key in (x for x in attributes if local(x.tag) == "key"):
        staff = key.get("number", "")
        label = "key" + staff
        fifths = text(key, "fifths")
        mode = text(key, "mode")
        if fifths:
            out.append(label + "=" + fifths + (":" + safe_id(mode) if mode else ""))
        else:
            items = []
            steps = [x for x in key if local(x.tag) == "key-step"]
            alters = [x for x in key if local(x.tag) == "key-alter"]
            accidentals = [x for x in key if local(x.tag) == "key-accidental"]
            for index, step in enumerate(steps):
                value = (step.text or "?").strip()
                if index < len(alters) and alters[index].text:
                    value += ":" + alters[index].text.strip()
                if index < len(accidentals) and accidentals[index].text:
                    value += ":" + safe_id(accidentals[index].text)
                items.append(value)
            if items:
                out.append("keyx" + staff + "=" + "+".join(items) + (":" + safe_id(mode) if mode else ""))
    for time in (x for x in attributes if local(x.tag) == "time"):
        staff = time.get("number", "")
        pairs: list[str] = []
        pending = ""
        for item in time:
            name = local(item.tag)
            if name == "beats":
                pending = (item.text or "").strip()
            elif name == "beat-type" and pending:
                pairs.append(pending + "/" + (item.text or "?").strip())
                pending = ""
        symbol = time.get("symbol", "")
        senza = text(time, "senza-misura")
        if senza or child(time, "senza-misura") is not None:
            out.append("timex" + staff + "=senza-misura" + (":" + safe_id(senza) if senza else ""))
        elif len(pairs) == 1 and child(time, "interchangeable") is None:
            out.append("time" + staff + "=" + pairs[0] + (f":{symbol}" if symbol else ""))
        elif pairs:
            marker = "timex" + staff + "=" + "+".join(pairs)
            interchangeable = child(time, "interchangeable")
            if interchangeable is not None:
                other_pairs = []
                other_beats = [x for x in interchangeable if local(x.tag) == "beats"]
                other_types = [x for x in interchangeable if local(x.tag) == "beat-type"]
                other_pairs = [
                    (beat.text or "?").strip() + "/" + (other_types[i].text or "?").strip()
                    for i, beat in enumerate(other_beats)
                    if i < len(other_types)
                ]
                marker += "|" + "+".join(other_pairs)
            out.append(marker + (f":{symbol}" if symbol else ""))
    for clef in (x for x in attributes if local(x.tag) == "clef"):
        number = clef.get("number", "1")
        sign, line = text(clef, "sign"), text(clef, "line")
        octave = text(clef, "clef-octave-change")
        if sign:
            out.append(f"clef{number}={sign}{line}" + (f"^{octave}" if octave else ""))
    transpose = child(attributes, "transpose")
    if transpose is not None:
        staff = transpose.get("number", "")
        diatonic = text(transpose, "diatonic")
        chromatic = text(transpose, "chromatic")
        octave = text(transpose, "octave-change")
        doubled = child(transpose, "double") is not None
        if chromatic and not diatonic and not octave and not doubled:
            out.append("transpose" + staff + "=" + chromatic)
        elif chromatic or diatonic or octave or doubled:
            values = []
            if diatonic:
                values.append("dia:" + diatonic)
            if chromatic:
                values.append("chrom:" + chromatic)
            if octave:
                values.append("oct:" + octave)
            if doubled:
                values.append("double")
            out.append("transposex" + staff + "=" + ",".join(values))

    for measure_style in (x for x in attributes if local(x.tag) == "measure-style"):
        staff = measure_style.get("number", "")
        for item in measure_style:
            name = local(item.tag)
            value = (item.text or "").strip()
            if name == "multiple-rest":
                out.append("multirest" + staff + "=" + (value or "?"))
            elif name == "measure-repeat":
                repeat_type = item.get("type", "")
                out.append("measure-repeat" + staff + "=" + repeat_type + (":" + value if value else ""))
            elif name in {"beat-repeat", "slash"}:
                repeat_type = item.get("type", "")
                details = [repeat_type] if repeat_type else []
                if value:
                    details.append(value)
                slash_type = text(item, "slash-type")
                if slash_type:
                    dots = sum(1 for x in item if local(x.tag) == "slash-dot")
                    details.append(slash_type + "." * dots)
                out.append(name + staff + "=" + ":".join(details))
    return out, divisions


def direction_tokens(direction: ET.Element, navigation: NavigationState | None = None) -> list[str]:
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
    for rehearsal in descendants(direction, "rehearsal"):
        value = (rehearsal.text or "").strip()
        if value:
            out.append("rehearsal=" + quote(value))
    for segno in descendants(direction, "segno"):
        value = sound.get("segno", "") if sound is not None else ""
        value = value or (segno.text or "").strip() or (navigation.next_segno() if navigation else "S1")
        out.append("segno=" + safe_id(value))
    for coda in descendants(direction, "coda"):
        value = sound.get("coda", "") if sound is not None else ""
        value = value or (coda.text or "").strip() or (navigation.next_coda() if navigation else "C1")
        out.append("coda=" + safe_id(value))
    if sound is not None:
        if sound.get("dacapo") == "yes":
            out.append("jump=DC")
        if sound.get("dalsegno"):
            out.append("jump=DS:" + safe_id(sound.get("dalsegno", "")))
        if sound.get("tocoda"):
            out.append("tocoda=" + safe_id(sound.get("tocoda", "")))
        if sound.get("fine"):
            out.append("fine")
    for wedge in descendants(direction, "wedge"):
        if wedge.get("type"):
            out.append("wedge=" + wedge.get("type", ""))
    for pedal in descendants(direction, "pedal"):
        pedal_type = pedal.get("type", "")
        if pedal_type:
            number = safe_id(pedal.get("number", "1"))
            out.append(f"ped{number}=" + pedal_type)
    for shift in descendants(direction, "octave-shift"):
        shift_type = shift.get("type", "")
        if shift_type:
            number = safe_id(shift.get("number", "1"))
            size = shift.get("size", "")
            out.append(f"oct{number}=" + shift_type + (":" + size if size else ""))
    return out


def add_instrument(token: str, alias: str) -> str:
    """Place an instrument marker after pitch and before note properties."""
    marker = "@" + alias
    brace = token.find("{")
    return token + marker if brace < 0 else token[:brace] + marker + token[brace:]


def normalized_arpeggiations(events: list[Event]) -> list[str]:
    order: list[tuple[str, str]] = []
    directions: dict[tuple[str, str], list[str]] = {}
    for event in events:
        for kind, number, direction in event.arpeggiations:
            key = (kind, number)
            if key not in directions:
                order.append(key)
                directions[key] = []
            if direction and direction not in directions[key]:
                directions[key].append(direction)
    result = []
    for kind, number in order:
        if kind == "arp":
            specified = directions[(kind, number)]
            if not specified:
                result.append(f"arp{number}")
            for direction in specified:
                suffix = {"up": "^", "down": "v"}.get(direction, ":" + direction)
                result.append(f"arp{number}{suffix}")
        else:
            result.append(f"noarp{number}")
    return result


def render_voice(
    voice: Voice,
    instrument_states: dict[str, str] | None = None,
    voice_key: str = "1",
    multiple_instruments: bool = False,
) -> str:
    grouped: list[tuple[Fraction, Fraction, list[Event]]] = []
    for _, event in sorted(enumerate(voice.events), key=lambda item: (item[1].start, item[0])):
        if event.chord and grouped and grouped[-1][0] == event.start and grouped[-1][1] == event.duration:
            grouped[-1][2].append(event)
        else:
            grouped.append((event.start, event.duration, [event]))
    cursor = Fraction(0)
    tokens: list[str] = []
    for start, duration, events in grouped:
        if start > cursor:
            tokens.append("_" + frac(start - cursor))
        pitches = [event.token for event in events]
        identities = [event.instrument for event in events if event.instrument]
        if multiple_instruments and identities:
            distinct = list(dict.fromkeys(identities))
            state = instrument_states.get(voice_key, "") if instrument_states is not None else ""
            mixed_event = len(distinct) > 1 or len(identities) != len(events)
            if mixed_event:
                pitches = [add_instrument(event.token, event.instrument) if event.instrument else event.token for event in events]
                next_state = identities[0]
            else:
                next_state = distinct[0]
            if instrument_states is not None:
                if not mixed_event and next_state != state:
                    # Applied to the assembled event below.
                    state_marker = next_state
                else:
                    state_marker = ""
                instrument_states[voice_key] = next_state
            else:
                state_marker = next_state if not mixed_event else ""
        else:
            state_marker = ""
        head = pitches[0] if len(pitches) == 1 else "[" + ",".join(pitches) + "]"
        if state_marker:
            head += "@" + state_marker
        arpeggiations = normalized_arpeggiations(events)
        if arpeggiations:
            head += "{" + ",".join(arpeggiations) + "}"
        tokens.append(head + "/" + (frac(duration) if duration else "0"))
        cursor = max(cursor, start + duration)
    return " ".join(tokens)


def instrument_catalog(
    score_part: ET.Element | None, part: ET.Element
) -> tuple[list[InstrumentDefinition], dict[str, str]]:
    """Return definitions and deterministic part-local aliases."""
    referenced: list[str] = []
    referenced_set: set[str] = set()
    has_unreferenced_pitched_note = False
    for note in descendants(part, "note"):
        if child(note, "rest") is not None or (child(note, "unpitched") is None and child(note, "pitch") is None):
            continue
        reference = child(note, "instrument")
        xml_id = reference.get("id", "").strip() if reference is not None else ""
        if child(note, "pitch") is not None and not xml_id:
            has_unreferenced_pitched_note = True
        if xml_id and xml_id not in referenced_set:
            referenced.append(xml_id)
            referenced_set.add(xml_id)

    definitions: list[InstrumentDefinition] = []
    seen: set[str] = set()
    available: list[ET.Element] = []
    if score_part is not None:
        available = [x for x in score_part if local(x.tag) == "score-instrument"]
        available_ids = {x.get("id", "").strip() for x in available}
        selected = set(referenced_set)
        if not referenced_set or has_unreferenced_pitched_note:
            selected.update(available_ids)
        for item in available:
            xml_id = item.get("id", "").strip()
            if xml_id in selected and xml_id not in seen:
                definitions.append(
                    InstrumentDefinition(
                        xml_id=xml_id,
                        name=text(item, "instrument-name"),
                        sound=text(item, "instrument-sound"),
                    )
                )
                seen.add(xml_id)

    # Referenced IDs remain meaningful even when their definitions are absent.
    for xml_id in referenced:
        if xml_id not in seen:
            definitions.append(InstrumentDefinition(xml_id=xml_id))
            seen.add(xml_id)

    aliases = {definition.xml_id: f"I{index}" for index, definition in enumerate(definitions, 1)}
    return definitions, aliases


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

    score_parts: dict[str, ET.Element] = {}
    part_list = child(root, "part-list")
    if part_list is not None:
        for score_part in (x for x in part_list if local(x.tag) == "score-part"):
            score_parts[score_part.get("id", "")] = score_part

    for part in (x for x in root if local(x.tag) == "part"):
        part_id = part.get("id", "?")
        score_part = score_parts.get(part_id)
        part_line = f"@part {safe_id(part_id)}"
        part_name = text(score_part, "part-name") if score_part is not None else ""
        if part_name:
            part_line += " name=" + quote(part_name)
        lines.append(part_line)
        instruments, instrument_aliases = instrument_catalog(score_part, part)
        for definition in instruments:
            instrument_line = f"@instrument {instrument_aliases[definition.xml_id]} id={quote(definition.xml_id)}"
            if definition.name:
                instrument_line += " name=" + quote(definition.name)
            if definition.sound:
                instrument_line += " sound=" + quote(definition.sound)
            lines.append(instrument_line)
        divisions = 1
        instrument_states: dict[str, str] = {}
        multiple_instruments = len(instrument_aliases) > 1
        navigation = NavigationState()
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
                    annotations.extend((cursor + offset, x) for x in direction_tokens(item, navigation))
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
                    token = pitch_token(item, instrument_aliases) + note_suffix(item)
                    instrument_alias = ""
                    if child(item, "pitch") is not None and instrument_aliases:
                        reference = child(item, "instrument")
                        xml_id = reference.get("id", "").strip() if reference is not None else ""
                        if xml_id:
                            instrument_alias = instrument_aliases.get(xml_id, "?")
                        elif len(instrument_aliases) == 1:
                            instrument_alias = next(iter(instrument_aliases.values()))
                        else:
                            instrument_alias = "?"
                    voices[key].events.append(
                        Event(start, duration, token, is_chord, instrument_alias, arpeggiation_markers(item))
                    )
                    if not is_chord:
                        voices[key].last_onset = start
                        if child(item, "grace") is None:
                            cursor += duration
            prefix = f"m{safe_id(number)}"
            if attrs:
                prefix += " " + " ".join(attrs)
            # Python's stable sort retains MusicXML order for semantic events
            # sharing an offset (for example pedal stop followed by start).
            for at, value in sorted(annotations, key=lambda annotation: annotation[0]):
                prefix += f" @{frac(at)}:{value}"
            if not voices:
                lines.append(prefix + " |")
            elif len(voices) == 1 and "1" in voices:
                # Only the canonical voice 1 / staff 1 may use the shorthand.
                lines.append(
                    prefix
                    + " | "
                    + render_voice(voices["1"], instrument_states, "1", multiple_instruments)
                )
            else:
                rendered = [
                    f"v{safe_id(k)}: {render_voice(v, instrument_states, k, multiple_instruments)}"
                    for k, v in sorted(voices.items())
                ]
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
