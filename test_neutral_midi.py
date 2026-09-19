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

    def test_ornament_uses_documented_neutral_direct_policy(self):
        semantic = score("""<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
            <notations><ornaments><trill-mark/></ornaments></notations></note>
        </measure></part>""")
        realized = realize_neutral(semantic)
        disposition = realized.dispositions[SourceEventId("P1", 1)]
        self.assertEqual(disposition.kind, "directly_realized")
        self.assertIn("without neutral expansion", disposition.detail)

    def test_grace_and_unpitched_notes_fail_explicitly(self):
        grace = score("""<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><grace/><pitch><step>D</step><octave>4</octave></pitch></note>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
        </measure></part>""")
        with self.assertRaisesRegex(RealizationError, "grace realization"):
            realize_neutral(grace)

        unpitched = score("""<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
          <note><unpitched><display-step>D</display-step><display-octave>5</display-octave></unpitched>
            <duration>1</duration></note></measure></part>""")
        with self.assertRaisesRegex(RealizationError, "unpitched instrument mapping"):
            realize_neutral(unpitched)


if __name__ == "__main__":
    unittest.main()
