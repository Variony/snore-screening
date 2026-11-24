# Snore Screening

**Version 1.0**

Snore Screening is a local web app for finding audio regions with sudden loudness increases in long recordings. It flags loudness changes for review; it does not identify sound sources. Audio is handled locally through the loopback interface and processed incrementally from a temporary file. The app does not upload recordings to external services or modify the original files.

## Run

Python 3 is required. On macOS, double-click `run.command`, or start the app from a terminal:

```sh
python3 server.py
```

The app opens in your browser at <http://127.0.0.1:8765>. Close the terminal window running the server to stop it. The interface defaults to English; use the language button in the upper-right corner to switch to Chinese. ZIP reports use the language selected when the scan starts.

Uncompressed PCM WAV files can be analyzed directly. Other common formats, including MP3, M4A, AAC, FLAC, and OGG, require FFmpeg. Install it with Homebrew:

```sh
brew install ffmpeg
```

Alternatively, install the Python package that provides FFmpeg:

```sh
python3 -m pip install -r requirements.txt
```

## Scanning and results

The default settings use 250 ms windows and flag candidates whose peak reaches at least -28 dBFS and whose peak or RMS is at least 6 dB above recent background. Lower thresholds can find quieter events but may increase false positives. Results are loudness candidates, not confirmed snores; listen to the clips to review them.

The results ZIP contains a CSV candidate list, a JSON scan summary, and an M4A clip for each candidate. Clips include approximately 3 seconds before and 1.5 seconds after each event. Upload and scan progress are shown in the interface.

Files up to 4 GiB are supported. Audio is processed incrementally rather than loaded into memory in full. The app temporarily stores the uploaded copy on the local system, so ensure enough disk space is available. Temporary audio is removed after analysis; result ZIPs are kept for up to one hour.

## Privacy and intended use

Audio stays on this computer and is not sent to an external service. Snore Screening is for reviewing audio only; it does not provide medical advice or diagnosis. The repository does not include recordings or exported audio.

## Tests

```sh
python3 -m unittest discover -s tests
```
