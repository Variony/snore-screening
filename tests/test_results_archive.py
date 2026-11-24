import csv
import io
import json
import re
import subprocess
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path

import imageio_ffmpeg

from server import create_audio_results_archive, create_results_archive


class ResultsArchiveTests(unittest.TestCase):
    def test_archive_contains_candidate_csv_and_summary(self):
        archive_bytes = create_results_archive({
            "file_name": "../recording.m4a",
            "settings": {"min_peak_dbfs": -28, "rise_db": 6, "window_ms": 250},
            "result": {
                "duration": 12.5,
                "sample_rate": 8_000,
                "file_size": 1234,
                "events": [{
                    "start": 2.0,
                    "end": 2.5,
                    "peak_dbfs": -20.0,
                    "rise_db": 12.0,
                }],
            },
        })

        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"snore_screening_results.csv", "scan_summary.json"},
            )
            csv_data = archive.read("snore_screening_results.csv").decode("utf-8-sig")
            rows = list(csv.reader(io.StringIO(csv_data)))
            self.assertEqual(rows[0][0], "No.")
            self.assertEqual(rows[1][1:3], ["00:00:02.0", "00:00:02.5"])
            summary = json.loads(archive.read("scan_summary.json"))

        self.assertEqual(summary["source_file"], "recording.m4a")
        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(summary["settings"]["window_ms"], 250)

    def test_archive_uses_selected_report_language(self):
        archive_bytes = create_results_archive({
            "language": "zh",
            "result": {"duration": 1, "events": []},
        })
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            csv_data = archive.read("snore_screening_results.csv").decode("utf-8-sig")
            rows = list(csv.reader(io.StringIO(csv_data)))
        self.assertEqual(rows[0][0], "序号")

    def test_rejects_malformed_event_data(self):
        with self.assertRaises(ValueError):
            create_results_archive({
                "result": {
                    "duration": 1,
                    "events": [{"start": 2, "end": 1, "peak_dbfs": -20, "rise_db": 5}],
                },
            })

    def test_audio_archive_contains_candidate_clip(self):
        sample_rate = 8_000
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "sample.wav"
            archive_path = Path(directory) / "results.zip"
            quiet = int(0.01 * 32767).to_bytes(2, "little", signed=True)
            loud = int(0.6 * 32767).to_bytes(2, "little", signed=True)
            with wave.open(str(audio_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(sample_rate)
                audio.writeframes(quiet * (sample_rate * 5))
                audio.writeframes(loud * (sample_rate // 2))
                audio.writeframes(quiet * (sample_rate * 4 + sample_rate // 2))

            create_audio_results_archive({
                "file_name": "sample.wav",
                "settings": {"min_peak_dbfs": -28, "rise_db": 6, "window_ms": 250},
                "result": {
                    "duration": 10,
                    "sample_rate": sample_rate,
                    "file_size": audio_path.stat().st_size,
                    "events": [{
                        "start": 5.0,
                        "end": 5.5,
                        "peak_dbfs": -4.4,
                        "rise_db": 30.0,
                    }],
                },
            }, audio_path, archive_path)

            with zipfile.ZipFile(archive_path) as archive:
                clip_names = [
                    name for name in archive.namelist()
                    if name.startswith("audio_clips/") and name.endswith(".m4a")
                ]
                self.assertEqual(len(clip_names), 1)
                self.assertGreater(archive.getinfo(clip_names[0]).file_size, 0)
                clip_path = Path(directory) / "candidate.m4a"
                clip_path.write_bytes(archive.read(clip_names[0]))

            probe = subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(clip_path),
                    "-t", "0.01", "-f", "null", "-",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            match = re.search(r"Duration: \d+:\d+:(\d+(?:\.\d+)?)", probe.stderr)
            self.assertIsNotNone(match)
            self.assertAlmostEqual(float(match.group(1)), 5.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
