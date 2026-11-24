import tempfile
import unittest
import wave
from pathlib import Path

from audio_analyzer import SpikeDetector, analyze_file


class SpikeDetectorTests(unittest.TestCase):
    def test_default_settings_find_moderate_loudness_increase(self):
        sample_rate = 8_000
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moderate-spike.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(sample_rate)
                quiet = int(0.01 * 32767).to_bytes(2, "little", signed=True)
                louder = int(0.1 * 32767).to_bytes(2, "little", signed=True)
                audio.writeframes(quiet * (sample_rate * 2))
                audio.writeframes(louder * (sample_rate // 2))
                audio.writeframes(quiet * sample_rate)

            result = analyze_file(path)

        self.assertEqual(len(result["events"]), 1)
        self.assertAlmostEqual(result["events"][0]["start"], 2.0, places=1)
        self.assertGreater(result["events"][0]["peak_dbfs"], -22)

    def test_detects_loud_section_after_quiet_baseline(self):
        sample_rate = 8_000
        detector = SpikeDetector(sample_rate, window_ms=100, min_peak_dbfs=-12, rise_db=8)
        for _ in range(sample_rate * 2):
            detector.push(0.01)
        for _ in range(sample_rate // 2):
            detector.push(0.8)
        for _ in range(sample_rate):
            detector.push(0.01)

        events = detector.finish()
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]["start"], 2.0, places=1)
        self.assertGreater(events[0]["peak_dbfs"], -2)
        self.assertGreaterEqual(events[0]["rise_db"], 8)

    def test_streams_pcm_wav_and_returns_duration_and_events(self):
        sample_rate = 8_000
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(sample_rate)
                quiet = int(0.01 * 32767).to_bytes(2, "little", signed=True)
                loud = int(0.8 * 32767).to_bytes(2, "little", signed=True)
                audio.writeframes(quiet * (sample_rate * 2))
                audio.writeframes(loud * (sample_rate // 2))
                audio.writeframes(quiet * sample_rate)

            progress = []
            result = analyze_file(
                path,
                progress_callback=lambda processed, total: progress.append((processed, total)),
            )

        self.assertAlmostEqual(result["duration"], 3.5, places=2)
        self.assertEqual(result["sample_rate"], sample_rate)
        self.assertEqual(len(result["events"]), 1)
        self.assertAlmostEqual(result["events"][0]["start"], 2.0, places=1)
        self.assertTrue(progress)
        self.assertAlmostEqual(progress[-1][0], 3.5, places=2)
        self.assertAlmostEqual(progress[-1][1], 3.5, places=2)

    def test_small_threshold_changes_are_valid(self):
        detector = SpikeDetector(1_000, window_ms=100, min_peak_dbfs=-60, rise_db=0)
        for index in range(1_000):
            detector.push(0.5 if index >= 500 else 0.01)
        self.assertEqual(len(detector.finish()), 1)

    def test_detects_brief_peak_above_a_louder_background(self):
        detector = SpikeDetector(1_000, window_ms=100, min_peak_dbfs=-12, rise_db=8)
        for _ in range(1_000):
            detector.push(0.15)
        detector.push(0.9)
        for _ in range(999):
            detector.push(0.15)

        events = detector.finish()
        self.assertEqual(len(events), 1)
        self.assertGreaterEqual(events[0]["rise_db"], 8)


if __name__ == "__main__":
    unittest.main()
