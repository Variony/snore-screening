import csv
import datetime
import io
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from audio_analyzer import analyze_file, get_ffmpeg_executable


ROOT = Path(__file__).resolve().parent
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
PORT = int(os.environ.get("PORT", "8765"))
_PROGRESS_LOCK = threading.Lock()
_PROGRESS_STATES = {}
_PACKAGE_LOCK = threading.Lock()
_PACKAGED_RESULTS = {}


def _set_progress(analysis_id, stage, percent, message, processed_seconds=None, total_seconds=None):
    now = time.monotonic()
    state = {
        "stage": stage,
        "percent": max(0, min(100, int(percent))),
        "message": message,
        "processed_seconds": processed_seconds,
        "total_seconds": total_seconds,
        "updated_at": now,
    }
    with _PROGRESS_LOCK:
        expired = [key for key, value in _PROGRESS_STATES.items() if now - value["updated_at"] > 3600]
        for key in expired:
            del _PROGRESS_STATES[key]
        if len(_PROGRESS_STATES) >= 128 and analysis_id not in _PROGRESS_STATES:
            oldest = min(_PROGRESS_STATES, key=lambda key: _PROGRESS_STATES[key]["updated_at"])
            del _PROGRESS_STATES[oldest]
        _PROGRESS_STATES[analysis_id] = state


def _store_result_package(path):
    now = time.time()
    with _PACKAGE_LOCK:
        expired = [
            package_id
            for package_id, package in _PACKAGED_RESULTS.items()
            if now - package["created_at"] > 3600
        ]
        expired_paths = [_PACKAGED_RESULTS.pop(package_id)["path"] for package_id in expired]
        package_id = uuid.uuid4().hex
        _PACKAGED_RESULTS[package_id] = {"path": Path(path), "created_at": now}
    for expired_path in expired_paths:
        try:
            expired_path.unlink()
        except FileNotFoundError:
            pass
    return package_id


def _get_result_package(package_id):
    expired_path = None
    with _PACKAGE_LOCK:
        package = _PACKAGED_RESULTS.get(package_id)
        if package is None:
            return None
        if time.time() - package["created_at"] > 3600:
            expired_path = _PACKAGED_RESULTS.pop(package_id)["path"]
            package_path = None
        else:
            package_path = package["path"]
    if expired_path is not None:
        try:
            expired_path.unlink()
        except FileNotFoundError:
            pass
    return package_path


def _finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number.")
    return float(value)


def _format_timestamp(seconds):
    whole_seconds = int(seconds)
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    fractional = seconds - whole_seconds
    return f"{hours:02d}:{minutes:02d}:{seconds_part + fractional:04.1f}"


def _build_result_files(document):
    if not isinstance(document, dict) or not isinstance(document.get("result"), dict):
        raise ValueError("Invalid scan result.")
    result = document["result"]
    events = result.get("events")
    if not isinstance(events, list) or len(events) > 1_000_000:
        raise ValueError("Invalid scan events.")
    settings = document.get("settings", {})
    if not isinstance(settings, dict):
        raise ValueError("Invalid scan settings.")
    language = "zh" if document.get("language") == "zh" else "en"

    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(
        ["序号", "开始时间", "结束时间", "持续秒数", "峰值 dBFS", "高于背景 dB"]
        if language == "zh"
        else ["No.", "Start", "End", "Duration (s)", "Peak (dBFS)", "Rise above background (dB)"]
    )
    normalized_events = []
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict):
            raise ValueError("Invalid scan event.")
        start = _finite_number(event.get("start"), "event start")
        end = _finite_number(event.get("end"), "event end")
        peak = _finite_number(event.get("peak_dbfs"), "event peak")
        rise = _finite_number(event.get("rise_db"), "event rise")
        if start < 0 or end < start:
            raise ValueError("Invalid event time range.")
        normalized_events.append({
            "start": start,
            "end": end,
            "peak_dbfs": peak,
            "rise_db": rise,
        })
        writer.writerow([
            index,
            _format_timestamp(start),
            _format_timestamp(end),
            round(end - start, 3),
            round(peak, 2),
            round(rise, 2),
        ])

    source_name = document.get("file_name", "audio")
    if not isinstance(source_name, str):
        raise ValueError("Invalid source filename.")
    source_name = source_name.replace("\\", "/").split("/")[-1]
    duration = _finite_number(result.get("duration"), "duration")
    summary = {
        "source_file": source_name,
        "duration_seconds": duration,
        "sample_rate_hz": result.get("sample_rate"),
        "source_size_bytes": result.get("file_size"),
        "candidate_count": len(events),
        "settings": settings,
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": (
            "声强突增候选，不代表已识别为呼噜声；请试听核实。本工具不提供医疗诊断。候选音频片段含事件前约3秒、后约1.5秒。"
            if language == "zh"
            else "These are loudness-spike candidates, not confirmed snoring. Listen to verify. Clips include about 3 seconds before and 1.5 seconds after each event. This tool is not a medical diagnostic."
        ),
    }
    return normalized_events, "\ufeff" + csv_buffer.getvalue(), json.dumps(
        summary,
        ensure_ascii=False,
        indent=2,
    )


def create_results_archive(document):
    _, csv_contents, summary_json = _build_result_files(document)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("snore_screening_results.csv", csv_contents)
        zipped.writestr("scan_summary.json", summary_json)
    return archive.getvalue()


def create_audio_results_archive(document, audio_path, archive_path, progress_callback=None):
    events, csv_contents, summary_json = _build_result_files(document)
    executable = get_ffmpeg_executable() if events else None
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("snore_screening_results.csv", csv_contents)
        zipped.writestr("scan_summary.json", summary_json)
        with tempfile.TemporaryDirectory(prefix="snore-clips-") as clip_directory:
            for index, event in enumerate(events, 1):
                clip_start = max(0.0, event["start"] - 3.0)
                clip_end = min(float(document["result"]["duration"]), event["end"] + 1.5)
                clip_duration = max(0.1, clip_end - clip_start)
                clip_path = Path(clip_directory) / f"candidate_{index:03d}.m4a"
                command = [
                    executable, "-hide_banner", "-loglevel", "error", "-nostdin",
                    "-ss", f"{clip_start:.3f}", "-i", str(audio_path),
                    "-t", f"{clip_duration:.3f}", "-map", "0:a:0",
                    "-vn", "-sn", "-dn", "-c:a", "aac", "-b:a", "128k",
                    "-map_metadata", "-1", str(clip_path),
                ]
                process = subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=120,
                )
                if process.returncode:
                    raise ValueError(
                        process.stderr.strip()
                        or f"Could not create audio for candidate {index}."
                    )
                timestamp = _format_timestamp(event["start"]).replace(":", "-")
                zipped.write(
                    clip_path,
                    f"audio_clips/candidate_{index:03d}_{timestamp}.m4a",
                    compress_type=zipfile.ZIP_STORED,
                )
                if progress_callback is not None:
                    progress_callback(index, len(events))


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "AudioSpikeAnalyzer/1.0"

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; media-src 'self' blob:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        super().end_headers()

    def do_GET(self):
        if not self._valid_host():
            return self._send_json(403, {"error": "Only local access is allowed."})
        path = urlparse(self.path).path
        if path == "/api/progress":
            analysis_id = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            if not re.fullmatch(r"[a-fA-F0-9-]{32,36}", analysis_id):
                return self._send_json(400, {"error": "Invalid analysis ID."})
            with _PROGRESS_LOCK:
                state = _PROGRESS_STATES.get(analysis_id)
            if state is None:
                return self._send_json(404, {"error": "Analysis progress was not found."})
            return self._send_json(200, {key: value for key, value in state.items() if key != "updated_at"})
        if path == "/api/results.zip":
            package_id = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            if not re.fullmatch(r"[a-fA-F0-9]{32}", package_id):
                return self._send_json(400, {"error": "Invalid results package ID."})
            package_path = _get_result_package(package_id)
            if package_path is None or not package_path.is_file():
                return self._send_json(404, {"error": "The results package expired or is unavailable."})
            return self._send_download(
                package_path,
                "snore_screening_results.zip",
                "application/zip",
            )
        relative = "index.html" if path == "/" else path.removeprefix("/")
        file_path = (ROOT / "static" / relative).resolve()
        if ROOT.joinpath("static").resolve() not in file_path.parents:
            return self._send_json(404, {"error": "Not found."})
        if not file_path.is_file():
            return self._send_json(404, {"error": "Not found."})
        content_type = "text/javascript; charset=utf-8" if file_path.suffix == ".js" else (
            "text/css; charset=utf-8" if file_path.suffix == ".css" else "text/html; charset=utf-8"
        )
        payload = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_download(self, file_path, filename, content_type="audio/mp4"):
        if not file_path.is_file():
            return self._send_json(404, {"error": "The trimmed recording is not available."})
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            with file_path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        if not self._valid_host():
            return self._send_json(403, {"error": "Only local access is allowed."})
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self._send_json(403, {"error": "Cross-origin requests are not allowed."})
        request_path = urlparse(self.path).path
        if request_path != "/api/analyze":
            return self._send_json(404, {"error": "Not found."})
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._send_json(411, {"error": "A Content-Length header is required."})
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            return self._send_json(413, {"error": "File must be between 1 byte and 4 GiB."})

        query = parse_qs(urlparse(self.path).query)
        try:
            min_peak = float(query.get("min_peak_dbfs", ["-28"])[0])
            rise_db = float(query.get("rise_db", ["6"])[0])
            window_ms = int(query.get("window_ms", ["250"])[0])
            if not -60 <= min_peak <= 0 or not 0 <= rise_db <= 40 or not 50 <= window_ms <= 1000:
                raise ValueError("Thresholds are outside the allowed range.")
        except (TypeError, ValueError) as error:
            return self._send_json(400, {"error": str(error) or "Invalid analysis settings."})

        suffix = Path(self.headers.get("X-Audio-Filename", "audio.wav")).suffix.lower()
        if not suffix or len(suffix) > 12 or not suffix[1:].isalnum():
            suffix = ".audio"
        language = self.headers.get("X-UI-Language", "en").lower()
        if language not in ("en", "zh"):
            language = "en"
        messages = {
            "en": {
                "receiving": "Receiving audio file…",
                "preparing": "Preparing audio scan…",
                "analyzing": "Scanning audio…",
                "packaging": "Scan complete; clipping candidate audio…",
                "clip_progress": "Clipping candidate audio {}/{}…",
                "complete": "Scan complete",
            },
            "zh": {
                "receiving": "正在接收音频文件…",
                "preparing": "正在准备逐块分析…",
                "analyzing": "正在逐块分析音频…",
                "packaging": "扫描完成，正在剪辑候选音频片段…",
                "clip_progress": "正在剪辑第 {}/{} 个候选音频片段…",
                "complete": "扫描完成",
            },
        }[language]
        analysis_id = self.headers.get("X-Analysis-ID", "")
        if not re.fullmatch(r"[a-fA-F0-9-]{32,36}", analysis_id):
            analysis_id = uuid.uuid4().hex
        _set_progress(analysis_id, "uploading", 0, messages["receiving"])
        try:
            with tempfile.NamedTemporaryFile(prefix="audio-spike-", suffix=suffix) as audio_file:
                remaining = length
                received = 0
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        return self._send_json(400, {"error": "Upload ended before the file was complete."})
                    audio_file.write(chunk)
                    remaining -= len(chunk)
                    received += len(chunk)
                    _set_progress(
                        analysis_id,
                        "uploading",
                        received * 100 // length,
                        messages["receiving"],
                    )
                audio_file.flush()

                _set_progress(analysis_id, "analyzing", 0, messages["preparing"])

                def report_analysis_progress(processed_seconds, total_seconds):
                    percent = min(89, int(processed_seconds / total_seconds * 89)) if total_seconds else 0
                    _set_progress(
                        analysis_id,
                        "analyzing",
                        percent,
                        messages["analyzing"],
                        processed_seconds,
                        total_seconds,
                    )

                result = analyze_file(
                    audio_file.name,
                    window_ms=window_ms,
                    min_peak_dbfs=min_peak,
                    rise_db=rise_db,
                    progress_callback=report_analysis_progress,
                )
                result["file_size"] = length
                display_name = unquote(self.headers.get("X-Audio-Display-Name", "audio"))
                document = {
                    "file_name": display_name.replace("\\", "/").split("/")[-1],
                    "language": language,
                    "settings": {
                        "min_peak_dbfs": min_peak,
                        "rise_db": rise_db,
                        "window_ms": window_ms,
                    },
                    "result": result,
                }
                _set_progress(
                    analysis_id,
                    "packaging",
                    90,
                    messages["packaging"],
                )
                with tempfile.NamedTemporaryFile(
                    prefix="snore-results-",
                    suffix=".zip",
                    delete=False,
                ) as package_file:
                    package_path = Path(package_file.name)

                try:
                    def report_package_progress(completed, total):
                        percent = 90 + int(completed / total * 9) if total else 99
                        _set_progress(
                            analysis_id,
                            "packaging",
                            percent,
                            messages["clip_progress"].format(completed, total),
                        )

                    create_audio_results_archive(
                        document,
                        audio_file.name,
                        package_path,
                        progress_callback=report_package_progress,
                    )
                except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                    try:
                        package_path.unlink()
                    except FileNotFoundError:
                        pass
                    raise ValueError(f"无法生成音频结果 ZIP：{error}") from error

                result["download_id"] = _store_result_package(package_path)
            _set_progress(analysis_id, "complete", 100, messages["complete"])
            self._send_json(200, result)
        except (OSError, ValueError) as error:
            _set_progress(analysis_id, "error", 0, str(error))
            self._send_json(422, {"error": str(error)})

    def _valid_host(self):
        host = self.headers.get("Host", "").split(":")[0].strip("[]").lower()
        return host in ("127.0.0.1", "localhost")

    def _send_json(self, status, data):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), RequestHandler)
    address = f"http://127.0.0.1:{PORT}"
    print(f"Audio Spike Analyzer is running locally at {address}")
    print("Press Ctrl+C to stop.")
    threading.Timer(0.8, webbrowser.open, args=(address,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
