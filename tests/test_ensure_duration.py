"""Tests d'intégration ffmpeg pour ensure_video_duration (v8.14).

Reproduit le bug « vidéo de 15 s coupée à 12 s » : une vidéo courte (12 s)
AVEC piste audio courte, padrée à 15 s, doit rester 15 s (et non 12 s).

Nécessite `ffmpeg` dans le PATH (injecté par le shell de test).
"""
import asyncio
import os
import re
import subprocess

import pytest

from core.video.postprocess import ensure_video_duration


def _make_short_video_with_audio(path: str, seconds: float = 12.0) -> None:
    """Génère une vidéo de `seconds` avec une piste audio de même durée."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"testsrc2=duration={seconds}:size=320x240:rate=15",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "128k",
            path,
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
    )


def _duration(path: str) -> float:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    assert m, "impossible de lire la durée"
    hh, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return hh * 3600 + mm * 60 + ss


@pytest.mark.asyncio
async def test_ensure_duration_pads_short_video_with_audio(tmp_path):
    """v8.14 : vidéo 12 s + audio 12 s → padrée à 15 s (bug 3 s avant)."""
    src = str(tmp_path / "short.mp4")
    _make_short_video_with_audio(src, 12.0)
    assert abs(_duration(src) - 12.0) < 0.5

    out = await ensure_video_duration(src, 15.0)
    dur = _duration(out)
    assert abs(dur - 15.0) <= 0.5, f"durée {dur}s ≠ 15s (bug 3s avant non corrigé)"


@pytest.mark.asyncio
async def test_ensure_duration_trims_long_video(tmp_path):
    """Vidéo 18 s → tronquée à 15 s."""
    src = str(tmp_path / "long.mp4")
    _make_short_video_with_audio(src, 18.0)
    out = await ensure_video_duration(src, 15.0)
    dur = _duration(out)
    assert abs(dur - 15.0) <= 0.5


@pytest.mark.asyncio
async def test_ensure_duration_already_correct(tmp_path):
    """Vidéo déjà à 15 s → renvoyée inchangée (fail-safe)."""
    src = str(tmp_path / "ok.mp4")
    _make_short_video_with_audio(src, 15.0)
    out = await ensure_video_duration(src, 15.0)
    assert out == src
