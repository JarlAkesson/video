import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "arrange_score.py"
FIXTURE = REPO / "assets" / "xml" / "G_Minor_Bach_Original.mxl"
OLD_MAC_FIXTURE = REPO / "assets" / "_build" / "xml" / "Old-MacDonald.safe.mxl"


class ArrangeScoreTests(unittest.TestCase):
    def run_arranger(self, *extra_args, goal="test arrangement"):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "out.musicxml"
            cmd = [
                "python3",
                str(SCRIPT),
                str(FIXTURE),
                "--goal",
                goal,
                "--output",
                str(output),
                "--print-summary",
                *extra_args,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=REPO)
            tree = ET.parse(output)
            summary = json.loads(proc.stdout)
            return output, tree.getroot(), summary

    def test_default_output_goes_to_build_xml(self):
        expected = REPO / "assets" / "_build" / "xml" / "G_Minor_Bach_Original.hiphop-dark.musicxml"
        if expected.exists():
            expected.unlink()
        try:
            proc = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    str(FIXTURE),
                    "--goal",
                    "dark hiphop remix with swagger",
                    "--print-summary",
                ],
                capture_output=True,
                text=True,
                check=True,
                cwd=REPO,
            )
            summary = json.loads(proc.stdout)
            self.assertEqual(Path(summary["output_path"]), expected.resolve())
            self.assertTrue(expected.exists())
        finally:
            if expected.exists():
                expected.unlink()

    def test_add_violin_only(self):
        _, root, summary = self.run_arranger(
            "--preset",
            "chamber_additive",
            "--add-instruments",
            "violin",
            "--drums",
            "none",
            "--bass",
            "none",
        )
        names = [score_part.findtext("part-name") for score_part in root.find("part-list").findall("score-part")]
        self.assertIn("Violin", names)
        self.assertNotIn("Bass", names)
        self.assertIn("Violin", summary["parts_added"])

    def test_add_bass_only(self):
        _, root, _ = self.run_arranger(
            "--add-instruments",
            "bass",
            "--bass",
            "strong",
            "--drums",
            "none",
            goal="bass only",
        )
        names = [score_part.findtext("part-name") for score_part in root.find("part-list").findall("score-part")]
        self.assertIn("Bass", names)
        self.assertNotIn("Drumset", names)

    def test_add_drums_only(self):
        _, root, _ = self.run_arranger(
            "--add-instruments",
            "drumset",
            "--drums",
            "strong",
            "--bass",
            "none",
            goal="drums only",
        )
        names = [score_part.findtext("part-name") for score_part in root.find("part-list").findall("score-part")]
        self.assertIn("Drumset", names)

    def test_hiphop_dark_changes_key_and_tempo(self):
        _, root, summary = self.run_arranger(goal="dark hiphop remix with swagger")
        first_key = root.find(".//part/measure/attributes/key")
        self.assertIsNotNone(first_key)
        self.assertEqual(first_key.findtext("fifths"), "-4")
        tempos = [sound.attrib["tempo"] for sound in root.findall(".//sound[@tempo]")]
        self.assertTrue(tempos)
        self.assertNotEqual(summary["tempo_change"], "keep")
        self.assertIn("Bass", summary["parts_added"])
        self.assertIn("Drumset", summary["parts_added"])

    def test_preserve_only_does_not_add_parts(self):
        _, root, summary = self.run_arranger(
            "--preset",
            "none",
            "--tempo",
            "keep",
            "--target-key",
            "keep",
            goal="preserve only",
        )
        names = [score_part.findtext("part-name") for score_part in root.find("part-list").findall("score-part")]
        self.assertEqual(names, ["Piano"])
        self.assertEqual(summary["parts_added"], [])

    def test_preserve_only_accepts_underfull_source_measure(self):
        if not OLD_MAC_FIXTURE.exists():
            self.skipTest("Old MacDonald fixture not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "oldmac.musicxml"
            subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    str(OLD_MAC_FIXTURE),
                    "--goal",
                    "preserve only",
                    "--preset",
                    "none",
                    "--tempo",
                    "keep",
                    "--target-key",
                    "keep",
                    "--output",
                    str(output),
                ],
                check=True,
                cwd=REPO,
            )
            root = ET.parse(output).getroot()
            self.assertTrue(root.findall("part"))

    def test_old_mac_with_children_arrangement_and_drums(self):
        if not OLD_MAC_FIXTURE.exists():
            self.skipTest("Old MacDonald fixture not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "oldmac-kids.musicxml"
            subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    str(OLD_MAC_FIXTURE),
                    "--goal",
                    "happy lighthearted kids music with bright instruments, decorated melody, simple beat, add chords",
                    "--preset",
                    "none",
                    "--add-instruments",
                    "violin,strings_pad,drumset",
                    "--density",
                    "sparse",
                    "--groove",
                    "straight",
                    "--drums",
                    "restrained",
                    "--bass",
                    "none",
                    "--melody-treatment",
                    "decorate",
                    "--harmony-treatment",
                    "color",
                    "--expression",
                    "shaped",
                    "--output",
                    str(output),
                ],
                check=True,
                cwd=REPO,
            )
            names = [
                score_part.findtext("part-name")
                for score_part in ET.parse(output).getroot().find("part-list").findall("score-part")
            ]
            self.assertIn("Violin", names)
            self.assertIn("Strings Pad", names)
            self.assertIn("Drumset", names)

    def test_musescore_export_interop(self):
        musescore = next(
            (candidate for candidate in ("musescore3", "musescore4", "musescore", "mscore") if shutil.which(candidate)),
            None,
        )
        if musescore is None:
            self.skipTest("MuseScore CLI not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "interop.musicxml"
            midi = Path(tmpdir) / "interop.mid"
            subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    str(FIXTURE),
                    "--goal",
                    "dark hiphop remix with swagger",
                    "--output",
                    str(output),
                ],
                check=True,
                cwd=REPO,
            )
            subprocess.run(
                [
                    musescore,
                    "--no-webview",
                    "-c",
                    str(Path(tmpdir) / "musescore-cfg"),
                    "-o",
                    str(midi),
                    str(output),
                ],
                check=True,
                cwd=REPO,
                env={
                    **os.environ,
                    "QT_QPA_PLATFORM": "offscreen",
                    "HOME": str(Path(tmpdir) / "home"),
                    "XDG_CONFIG_HOME": str(Path(tmpdir) / "home"),
                },
            )
            self.assertTrue(midi.exists())
            self.assertGreater(midi.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
