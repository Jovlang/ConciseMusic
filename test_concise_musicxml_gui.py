import unittest
from pathlib import Path

from concise_musicxml_gui import plan_outputs


class GuiOutputPlanningTests(unittest.TestCase):
    def test_default_plans_cmusic_output(self):
        jobs = plan_outputs([Path("one.musicxml")], Path("out"))
        self.assertEqual(jobs, [(Path("one.musicxml"), Path("out/one.cmusic"), "cmusic")])

    def test_midi_mode_plans_direct_mid_output(self):
        jobs = plan_outputs([Path("one.musicxml")], Path("out"), "midi")
        self.assertEqual(jobs, [(Path("one.musicxml"), Path("out/one.mid"), "midi")])

    def test_both_mode_plans_both_outputs_in_stable_order(self):
        jobs = plan_outputs([Path("one.musicxml")], Path("out"), "both")
        self.assertEqual(
            jobs,
            [
                (Path("one.musicxml"), Path("out/one.cmusic"), "cmusic"),
                (Path("one.musicxml"), Path("out/one.mid"), "midi"),
            ],
        )

    def test_colliding_basenames_are_disambiguated_per_extension(self):
        jobs = plan_outputs(
            [Path("a/score.musicxml"), Path("b/score.musicxml")], Path("out"), "both"
        )
        self.assertEqual(
            [destination.name for _, destination, _ in jobs],
            ["score.cmusic", "score.mid", "score_2.cmusic", "score_2.mid"],
        )

    def test_unknown_output_mode_fails(self):
        with self.assertRaisesRegex(ValueError, "unknown output format"):
            plan_outputs([], Path("out"), "audio")


if __name__ == "__main__":
    unittest.main()
