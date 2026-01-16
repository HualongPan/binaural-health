#!/usr/bin/env python3
"""Frequency Shift Processor (PWA-ready Flask app)

What it does
- Upload a WAV file
- Create stereo WAV:
  Left  = original audio (mono)
  Right = Hilbert-based frequency-shifted audio (+shift_hz)

This version is structured for deployment + PWA/TWA wrapping.
"""

from __future__ import annotations

import os
import time
import uuid
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import hilbert, firwin, lfilter

from flask import Flask, render_template, request, send_file, url_for, send_from_directory, after_this_request
from werkzeug.utils import secure_filename

# -----------------------
# DSP helpers
# -----------------------

def to_mono(x: np.ndarray) -> np.ndarray:
    """If stereo/multi-channel, average to mono."""
    if x.ndim == 1:
        return x
    return x.mean(axis=1)


def lowpass_for_shift(fs: float, shift_hz: float, numtaps: int = 1025) -> np.ndarray:
    """Anti-aliasing low-pass filter taps.

    Guard band so shifting up doesn't alias near Nyquist.
    cutoff = (fs/2) - shift_hz - 10 Hz
    """
    nyq = fs / 2.0
    cutoff = max(10.0, nyq - shift_hz - 10.0)
    if cutoff >= nyq:
        return np.array([1.0])
    return firwin(numtaps, cutoff / nyq)


def freq_shift(signal_mono: np.ndarray, fs: float, shift_hz: float) -> np.ndarray:
    """Frequency-shift a real signal by +shift_hz using analytic signal.

    x_a(t) = hilbert(x(t))
    y(t)   = Re{ x_a(t) * exp(j*2*pi*f0*t) }
    """
    # Optional anti-aliasing filter
    taps = lowpass_for_shift(fs, shift_hz)
    if taps.size > 1:
        signal_mono = lfilter(taps, [1.0], signal_mono)

    n = np.arange(len(signal_mono))
    phasor = np.exp(1j * 2 * np.pi * shift_hz * n / fs)

    analytic = hilbert(signal_mono)
    shifted = np.real(analytic * phasor)

    # Light normalization to avoid clipping
    peak = max(1e-9, float(np.max(np.abs(shifted))))
    if peak > 1.0:
        shifted = shifted / peak
    return shifted


def normalize_pair(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    peak = max(float(np.max(np.abs(left))), float(np.max(np.abs(right))), 1e-9)
    if peak > 0.999:
        left = left / peak
        right = right / peak
    return left, right


def process_file(input_path: str, output_path: str, shift_hz: float) -> None:
    x, fs = sf.read(input_path, always_2d=False)
    x = to_mono(np.asarray(x, dtype=np.float64))

    # Remove DC offset
    x = x - np.mean(x)

    x_shifted = freq_shift(x, fs, shift_hz)

    left, right = normalize_pair(x, x_shifted)
    stereo = np.stack([left, right], axis=-1).astype(np.float32)

    sf.write(output_path, stereo, int(fs), subtype="PCM_24")


# -----------------------
# App setup
# -----------------------

APP_NAME = "Frequency Shift Processor"

BASE_DIR = Path(__file__).resolve().parent

WORK_DIR = Path(tempfile.gettempdir()) / "freqshift_pwa"
WORK_DIR.mkdir(parents=True, exist_ok=True)

# Delete files older than this (seconds)
CLEANUP_AFTER_SECONDS = 60 * 60  # 1 hour

ALLOWED_EXTENSIONS = {"wav"}

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

# Max upload size (adjust if you want)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def cleanup_old_files() -> None:
    now = time.time()
    for p in WORK_DIR.glob("freqshift_*"):
        try:
            if now - p.stat().st_mtime > CLEANUP_AFTER_SECONDS:
                p.unlink(missing_ok=True)
        except Exception:
            pass


@app.after_request
def add_security_headers(resp):
    # Basic headers useful for PWA/TWA + security
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp


@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    resp = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
    # SW should not be cached aggressively by proxies
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/.well-known/<path:filename>")
def well_known(filename):
    return send_from_directory(str(BASE_DIR / "static" / ".well-known"), filename)


@app.route("/privacy")
def privacy():
    return render_template("privacy.html", app_name=APP_NAME)


@app.route("/", methods=["GET", "POST"])
def index():
    cleanup_old_files()

    audio_url = None
    download_url = None
    shift_hz = 40.0
    error = None

    if request.method == "POST":
        f = request.files.get("file")
        if not f or f.filename == "":
            error = "Please select a WAV file."
            return render_template("index.html", app_name=APP_NAME, audio_url=None, download_url=None, shift_hz=shift_hz, error=error)

        shift_hz = float(request.form.get("shift", 40.0))
        if shift_hz <= 0:
            error = "Shift must be > 0 Hz."
            return render_template("index.html", app_name=APP_NAME, audio_url=None, download_url=None, shift_hz=shift_hz, error=error)

        filename = secure_filename(f.filename)
        if not allowed_file(filename):
            error = "Only .wav files are supported."
            return render_template("index.html", app_name=APP_NAME, audio_url=None, download_url=None, shift_hz=shift_hz, error=error)

        # Unique temp paths
        job_id = uuid.uuid4().hex[:12]
        src_path = WORK_DIR / f"freqshift_{job_id}_src.wav"
        out_path = WORK_DIR / f"freqshift_{job_id}_stereo_shift_{int(round(shift_hz))}Hz.wav"

        f.save(str(src_path))

        try:
            process_file(str(src_path), str(out_path), shift_hz=shift_hz)
        except Exception as e:
            error = f"Processing failed: {type(e).__name__}"
            return render_template("index.html", app_name=APP_NAME, audio_url=None, download_url=None, shift_hz=shift_hz, error=error)

        # Stream + download endpoints
        audio_url = url_for("result_audio", filename=out_path.name)
        download_url = url_for("download_audio", filename=out_path.name)

        # Cleanup uploaded source after response
        @after_this_request
        def _cleanup(response):
            try:
                src_path.unlink(missing_ok=True)
            except Exception:
                pass
            return response

    return render_template(
        "index.html",
        app_name=APP_NAME,
        audio_url=audio_url,
        download_url=download_url,
        shift_hz=shift_hz,
        error=error,
    )


@app.route("/result/<path:filename>")
def result_audio(filename: str):
    path = WORK_DIR / filename
    if not path.exists():
        return "Not found", 404
    return send_file(str(path), mimetype="audio/wav", conditional=True)


@app.route("/download/<path:filename>")
def download_audio(filename: str):
    path = WORK_DIR / filename
    if not path.exists():
        return "Not found", 404
    return send_file(str(path), mimetype="audio/wav", as_attachment=True, download_name=filename)


if __name__ == "__main__":
    # For local testing:
    #   python app.py
    # Production (Render/Fly/etc.) should use gunicorn.
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
