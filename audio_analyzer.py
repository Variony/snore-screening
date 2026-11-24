import math
import re
import shutil
import struct
import subprocess
import wave
from collections import deque
from pathlib import Path


READ_FRAMES = 16_384
FFMPEG_SAMPLE_RATE = 8_000


def _dbfs(value):
    return 20 * math.log10(max(value, 1e-6))


class SpikeDetector:
    def __init__(self, sample_rate, window_ms=250, min_peak_dbfs=-28, rise_db=6):
        self.sample_rate = sample_rate
        self.window_frames = max(1, round(sample_rate * window_ms / 1000))
        self.min_peak_dbfs = min_peak_dbfs
        self.rise_db = rise_db
        self.history = deque(maxlen=max(10, round(10_000 / window_ms)))
        self.sample_count = 0
        self.window_peak = 0.0
        self.window_squares = 0.0
        self.window_samples = 0
        self.events = []
        self.active_event = None

    def push(self, sample):
        self.window_peak = max(self.window_peak, abs(sample))
        self.window_squares += sample * sample
        self.window_samples += 1
        self.sample_count += 1
        if self.window_samples >= self.window_frames:
            self._finish_window()

    def finish(self):
        if self.window_samples:
            self._finish_window()
        self._close_event()
        return self.events

    def _finish_window(self):
        peak = self.window_peak
        rms = math.sqrt(self.window_squares / self.window_samples)
        start = (self.sample_count - self.window_samples) / self.sample_rate
        end = self.sample_count / self.sample_rate

        baseline = None
        if len(self.history) >= 5:
            baseline = sorted(self.history)[len(self.history) // 2]
        peak_dbfs = _dbfs(peak)
        rms_dbfs = _dbfs(rms)
        baseline_dbfs = _dbfs(baseline) if baseline is not None else None
        rise = (
            max(rms_dbfs, peak_dbfs) - baseline_dbfs
            if baseline_dbfs is not None else None
        )
        is_spike = (
            peak_dbfs >= self.min_peak_dbfs
            and rise is not None
            and rise >= self.rise_db
        )

        if is_spike:
            if self.active_event is None:
                self.active_event = {
                    "start": start,
                    "end": end,
                    "peak_dbfs": peak_dbfs,
                    "rms_dbfs": rms_dbfs,
                    "rise_db": rise,
                    "last_spike_end": end,
                }
            else:
                gap = start - self.active_event["last_spike_end"]
                if gap > 0.3:
                    self._close_event()
                    self.active_event = {
                        "start": start,
                        "end": end,
                        "peak_dbfs": peak_dbfs,
                        "rms_dbfs": rms_dbfs,
                        "rise_db": rise,
                        "last_spike_end": end,
                    }
                else:
                    self.active_event["end"] = end
                    self.active_event["last_spike_end"] = end
                    self.active_event["peak_dbfs"] = max(
                        self.active_event["peak_dbfs"], peak_dbfs
                    )
                    self.active_event["rms_dbfs"] = max(
                        self.active_event["rms_dbfs"], rms_dbfs
                    )
                    self.active_event["rise_db"] = max(
                        self.active_event["rise_db"], rise
                    )
        elif (
            self.active_event is not None
            and start - self.active_event["last_spike_end"] > 0.3
        ):
            self._close_event()

        if not is_spike:
            self.history.append(rms)

        self.window_peak = 0.0
        self.window_squares = 0.0
        self.window_samples = 0

    def _close_event(self):
        if self.active_event is not None:
            self.active_event.pop("last_spike_end", None)
            self.events.append(self.active_event)
            self.active_event = None


def _wav_samples(path):
    with open(path, "rb") as source:
        header = source.read(12)
        if header[:4] not in (b"RIFF", b"RF64", b"BW64") or header[8:12] != b"WAVE":
            raise ValueError("Invalid WAV container.")
        while True:
            chunk_header = source.read(8)
            if len(chunk_header) < 8:
                raise ValueError("WAV format information is missing.")
            chunk_id, chunk_size = chunk_header[:4], int.from_bytes(chunk_header[4:], "little")
            if chunk_id == b"fmt ":
                format_data = source.read(min(chunk_size, 40))
                if len(format_data) < 16:
                    raise ValueError("WAV format information is incomplete.")
                format_code = int.from_bytes(format_data[:2], "little")
                if format_code == 0xFFFE and len(format_data) >= 26:
                    format_code = int.from_bytes(format_data[24:26], "little")
                if format_code != 1:
                    raise ValueError("This WAV is not integer PCM.")
                break
            source.seek(chunk_size + (chunk_size & 1), 1)

    with wave.open(str(path), "rb") as audio:
        if audio.getcomptype() != "NONE":
            raise ValueError("This WAV uses compression; install FFmpeg to analyze it.")
        channels = audio.getnchannels()
        width = audio.getsampwidth()
        sample_rate = audio.getframerate()
        if width not in (1, 2, 3, 4):
            raise ValueError("Unsupported WAV sample format; install FFmpeg to analyze it.")
        yield sample_rate
        while True:
            data = audio.readframes(READ_FRAMES)
            if not data:
                break
            frame_width = channels * width
            for offset in range(0, len(data), frame_width):
                peak = 0.0
                for channel in range(channels):
                    index = offset + channel * width
                    if width == 1:
                        value = (data[index] - 128) / 128.0
                    elif width == 2:
                        value = int.from_bytes(data[index:index + 2], "little", signed=True) / 32768.0
                    elif width == 3:
                        value = int.from_bytes(data[index:index + 3], "little", signed=True) / 8_388_608.0
                    else:
                        value = int.from_bytes(data[index:index + 4], "little", signed=True) / 2_147_483_648.0
                    peak = max(peak, abs(value))
                yield peak


def get_ffmpeg_executable():
    executable = shutil.which("ffmpeg")
    if not executable:
        try:
            import imageio_ffmpeg
        except ImportError:
            executable = None
        else:
            executable = imageio_ffmpeg.get_ffmpeg_exe()
    if not executable:
        raise ValueError(
            "FFmpeg is required for this format. Install it with `brew install ffmpeg` "
            "or `python3 -m pip install -r requirements.txt`, then restart the app. "
            "Uncompressed PCM WAV works without FFmpeg."
        )
    return executable


def _probe_duration(path):
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as audio:
                return audio.getnframes() / audio.getframerate()
        except (wave.Error, EOFError):
            pass

    result = subprocess.run(
        [
            get_ffmpeg_executable(), "-hide_banner", "-i", str(path),
            "-t", "0.01", "-f", "null", "-",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        raise ValueError("Could not read the audio duration for progress reporting.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _ffmpeg_samples(path):
    executable = get_ffmpeg_executable()
    command = [
        executable, "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-vn", "-sn", "-dn", "-ac", "1", "-ar", str(FFMPEG_SAMPLE_RATE),
        "-f", "f32le", "pipe:1",
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
    )
    try:
        yield FFMPEG_SAMPLE_RATE
        remainder = b""
        while True:
            chunk = process.stdout.read(64 * 1024)
            if not chunk:
                break
            data = remainder + chunk
            usable = len(data) - (len(data) % 4)
            remainder = data[usable:]
            for (sample,) in struct.iter_unpack("<f", data[:usable]):
                yield min(1.0, abs(sample))
        if remainder:
            raise ValueError("FFmpeg returned incomplete audio samples.")
        error = process.stderr.read().decode("utf-8", errors="replace").strip()
        return_code = process.wait()
        if return_code:
            raise ValueError(error or "FFmpeg could not decode this audio file.")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()


def analyze_file(path, window_ms=250, min_peak_dbfs=-28, rise_db=6, progress_callback=None):
    path = Path(path)
    progress_total = _probe_duration(path) if progress_callback is not None else None
    if path.suffix.lower() == ".wav":
        try:
            samples = _wav_samples(path)
            sample_rate = next(samples)
        except (wave.Error, EOFError, ValueError):
            samples = _ffmpeg_samples(path)
            sample_rate = next(samples)
    else:
        samples = _ffmpeg_samples(path)
        sample_rate = next(samples)

    detector = SpikeDetector(sample_rate, window_ms, min_peak_dbfs, rise_db)
    next_progress_sample = sample_rate
    for sample in samples:
        detector.push(sample)
        if progress_callback is not None and detector.sample_count >= next_progress_sample:
            progress_callback(detector.sample_count / sample_rate, progress_total)
            next_progress_sample = detector.sample_count + sample_rate
    events = detector.finish()
    duration = detector.sample_count / sample_rate
    if progress_callback is not None:
        progress_callback(duration, progress_total)
    return {
        "duration": duration,
        "sample_rate": sample_rate,
        "events": events,
    }
