import struct
import unittest
from collections import Counter
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

from concise_musicxml import import_musicxml, load_xml
from neutral_midi import RealizationError, SourceEventId, realize_neutral, render_midi


def score(parts: str, part_list: str = '<score-part id="P1"><part-name>Test</part-name></score-part>'):
    root = ET.fromstring(
        f'<score-partwise version="4.0"><part-list>{part_list}</part-list>{parts}</score-partwise>'
    )
    return import_musicxml(root)


class NeutralMidiTests(unittest.TestCase):
    def test_western_sunrise_neutral_realization_when_source_is_available(self):
        path = Path.home() / "Downloads" / "Western Sunrise v2 - Full score - 01 .musicxml"
        if not path.exists():
            self.skipTest("external Western Sunrise source is not available")
        semantic = import_musicxml(load_xml(path), path.name)
        result = render_midi(semantic)

        self.assertTrue(result.audit.ok)
        self.assertEqual(sum(len(measure.events) for part in semantic.parts for measure in part.measures), 1179)
        self.assertEqual(len(result.realization.notes), 1007)
        self.assertEqual(
            Counter(item.kind for item in result.realization.dispositions.values()),
            {"directly_realized": 1007, "intentionally_silent": 150, "merged_by_tie": 22},
        )
        self.assertTrue(all(note.source_event_ids for note in result.realization.notes))

    def test_single_note_has_provenance_and_valid_format_one_midi(self):
        semantic = score("""<part id="P1"><measure number="1"><attributes><divisions>1</divisions>
          <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
          <direction><sound tempo="100"/></direction>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
        </measure></part>""")
        result = render_midi(semantic)

        self.assertTrue(result.audit.ok)
        self.assertEqual(result.data[:4], b"MThd")
        self.assertEqual(struct.unpack(">HHH", result.data[8:14]), (1, 2, 480))
        self.assertEqual(len(result.realization.notes), 1)
        note = result.realization.notes[0]
        self.assertEqual((note.pitch, note.onset, note.duration, note.velocity), (60, 0, 1, 64))
        self.assertEqual(note.source_event_ids, [SourceEventId("P1", 1)])
        self.assertEqual(result.realization.dispositions[SourceEventId("P1", 1)].kind, "directly_realized")
        self.assertEqual(result.midi_note_sources, {1: (SourceEventId("P1", 1),)})
        self.assertEqual(result.realization.tempos[0].bpm, 100)

    def test_chord_and_multiple_voices_retain_distinct_provenance(self):
        semantic = score("""<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
          <note><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
          <backup><duration>1</duration></backup>
          <note><pitch><step>G</step><octave>3</octave></pitch><duration>1</duration><voice>2</voice></note>
        </measure></part>""")
        realized = realize_neutral(semantic)

        self.assertEqual([note.pitch for note in realized.notes], [60, 64, 55])
        self.assertEqual([note.onset for note in realized.notes], [0, 0, 0])
        self.assertEqual(len({note.channel for note in realized.notes}), 2)
        self.assertEqual(
            [tuple(note.source_event_ids) for note in realized.notes],
            [(SourceEventId("P1", 1),), (SourceEventId("P1", 2),), (SourceEventId("P1", 3),)],
        )

    def test_multiple_parts_become_separate_tracks(self):
        semantic = score(
            """<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
              <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note></measure></part>
              <part id="P2"><measure number="1"><attributes><divisions>1</divisions></attributes>
              <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note></measure></part>""",
            '<score-part id="P1"><part-name>One</part-name></score-part>'
            '<score-part id="P2"><part-name>Two</part-name></score-part>',
        )
        result = render_midi(semantic)

        self.assertEqual(struct.unpack(">H", result.data[10:12])[0], 3)
        self.assertEqual({note.part_index for note in result.realization.notes}, {0, 1})

    def test_rests_advance_written_timing_and_are_accounted_silent(self):
        semantic = score("""<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><rest/><duration>1</duration></note>
          <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note>
        </measure></part>""")
        realized = realize_neutral(semantic)

        self.assertEqual(realized.notes[0].onset, 1)
        self.assertEqual(realized.dispositions[SourceEventId("P1", 1)].kind, "intentionally_silent")

    def test_tied_score_notes_merge_with_both_source_identities(self):
        semantic = score("""<part id="P1">
          <measure number="1"><attributes><divisions>1</divisions></attributes>
            <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration>
              <notations><tied type="start" number="1"/></notations></note></measure>
          <measure number="2"><note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration>
              <notations><tied type="stop" number="1"/></notations></note></measure>
        </part>""")
        realized = realize_neutral(semantic)

        self.assertEqual(len(realized.notes), 1)
        self.assertEqual(realized.notes[0].duration, 6)
        self.assertEqual(
            realized.notes[0].source_event_ids,
            [SourceEventId("P1", 1), SourceEventId("P1", 2)],
        )
        self.assertEqual(realized.dispositions[SourceEventId("P1", 2)].kind, "merged_by_tie")

    def test_chromatic_transposition_resolves_sounding_pitch(self):
        semantic = score("""<part id="P1"><measure number="1"><attributes><divisions>1</divisions>
          <transpose><chromatic>-2</chromatic></transpose></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
        </measure></part>""")
        self.assertEqual(realize_neutral(semantic).notes[0].pitch, 58)

    def test_authored_midi_program_and_channel_are_realized(self):
        semantic = score(
            """<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
              <note><instrument id="P1-I1"/><pitch><step>C</step><octave>4</octave></pitch>
                <duration>1</duration></note></measure></part>""",
            '<score-part id="P1"><part-name>Clarinet</part-name>'
            '<score-instrument id="P1-I1"><instrument-name>Clarinet</instrument-name></score-instrument>'
            '<midi-instrument id="P1-I1"><midi-channel>3</midi-channel>'
            '<midi-program>72</midi-program></midi-instrument></score-part>',
        )
        definition = semantic.parts[0].instruments[0]
        self.assertEqual((definition.midi_channel, definition.midi_program), (3, 72))

        result = render_midi(semantic)
        self.assertEqual((result.realization.notes[0].channel, result.realization.notes[0].pitch), (2, 60))
        self.assertEqual(result.realization.programs[0].program, 71)
        self.assertIn(bytes((0xC2, 71)), result.data)
        self.assertIn(bytes((0x92, 60, 64)), result.data)

    def test_unpitched_uses_authored_identity_mapping_not_display_position(self):
        semantic = score(
            """<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
              <note><instrument id="P1-Snare"/><unpitched><display-step>D</display-step>
                <display-octave>5</display-octave></unpitched><duration>1</duration></note>
              <note><instrument id="P1-Snare"/><unpitched><display-step>F</display-step>
                <display-octave>4</display-octave></unpitched><duration>1</duration></note>
            </measure></part>""",
            '<score-part id="P1"><part-name>Drums</part-name>'
            '<score-instrument id="P1-Snare"><instrument-name>Snare</instrument-name></score-instrument>'
            '<midi-instrument id="P1-Snare"><midi-channel>10</midi-channel>'
            '<midi-unpitched>39</midi-unpitched></midi-instrument></score-part>',
        )
        realized = realize_neutral(semantic)
        self.assertEqual([(note.channel, note.pitch) for note in realized.notes], [(9, 38), (9, 38)])
        self.assertTrue(all(note.source_event_ids for note in realized.notes))

    def test_unpitched_without_authored_mapping_fails_explicitly(self):
        semantic = score(
            """<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
              <note><instrument id="P1-I1"/><unpitched><display-step>D</display-step>
                <display-octave>5</display-octave></unpitched><duration>1</duration></note>
            </measure></part>""",
            '<score-part id="P1"><part-name>Drums</part-name>'
            '<score-instrument id="P1-I1"><instrument-name>Unknown drum</instrument-name>'
            '</score-instrument></score-part>',
        )
        with self.assertRaisesRegex(RealizationError, "no midi-unpitched mapping"):
            realize_neutral(semantic)

    def test_pitched_instrument_switch_emits_program_changes(self):
        semantic = score(
            """<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
              <note><instrument id="P1-I1"/><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
              <note><instrument id="P1-I2"/><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note>
            </measure></part>""",
            '<score-part id="P1"><part-name>Player</part-name>'
            '<score-instrument id="P1-I1"><instrument-name>One</instrument-name></score-instrument>'
            '<score-instrument id="P1-I2"><instrument-name>Two</instrument-name></score-instrument>'
            '<midi-instrument id="P1-I1"><midi-program>1</midi-program></midi-instrument>'
            '<midi-instrument id="P1-I2"><midi-program>41</midi-program></midi-instrument>'
            '</score-part>',
        )
        realized = realize_neutral(semantic)
        self.assertEqual([(item.onset, item.program) for item in realized.programs], [(0, 0), (1, 40)])
        self.assertNotEqual(realized.notes[0].channel, realized.notes[1].channel)

    def test_ornament_uses_documented_neutral_direct_policy(self):
        semantic = score("""<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><ornaments><trill-mark/></ornaments></notations></note>
        </measure></part>""")
        realized = realize_neutral(semantic)
        disposition = realized.dispositions[SourceEventId("P1", 1)]
        self.assertEqual(disposition.kind, "directly_realized")
        self.assertIn("without neutral expansion", disposition.detail)

    def test_grace_sequence_uses_deterministic_following_note_timing(self):
        grace = score("""<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><grace/><pitch><step>D</step><octave>4</octave></pitch></note>
          <note><grace/><pitch><step>E</step><octave>4</octave></pitch></note>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
        </measure></part>""")
        realized = realize_neutral(grace)
        self.assertEqual(
            [(note.pitch, note.onset, note.duration) for note in realized.notes],
            [(62, 0, Fraction(1, 16)), (64, Fraction(1, 16), Fraction(1, 16)),
             (60, Fraction(1, 8), Fraction(7, 8))],
        )
        self.assertEqual(realized.dispositions[SourceEventId("P1", 1)].kind, "grace_realization")
        self.assertEqual(realized.dispositions[SourceEventId("P1", 2)].kind, "grace_realization")

    def test_grace_chord_shares_one_performed_slot(self):
        semantic = score("""<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><grace steal-time-following="20"/><pitch><step>C</step><octave>4</octave></pitch></note>
          <note><chord/><grace steal-time-following="20"/><pitch><step>E</step><octave>4</octave></pitch></note>
          <note><pitch><step>G</step><octave>4</octave></pitch><duration>2</duration></note>
        </measure></part>""")
        realized = realize_neutral(semantic)
        self.assertEqual(
            [(note.pitch, note.onset, note.duration) for note in realized.notes],
            [(60, 0, Fraction(2, 5)), (64, 0, Fraction(2, 5)),
             (67, Fraction(2, 5), Fraction(8, 5))],
        )

    def test_unsupported_grace_timing_semantics_fail_explicitly(self):
        for attribute, message in (
            ('make-time="1"', "make-time"),
            ('steal-time-previous="20"', "steal-time-previous"),
        ):
            semantic = score(f"""<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
              <note><grace {attribute}/><pitch><step>D</step><octave>4</octave></pitch></note>
              <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
            </measure></part>""")
            with self.assertRaisesRegex(RealizationError, message):
                realize_neutral(semantic)

    def test_unpitched_without_identity_fails_explicitly(self):

        unpitched = score("""<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><unpitched><display-step>D</display-step><display-octave>5</display-octave></unpitched>
            <duration>1</duration></note></measure></part>""")
        with self.assertRaisesRegex(RealizationError, "unpitched instrument mapping"):
            realize_neutral(unpitched)


if __name__ == "__main__":
    unittest.main()
