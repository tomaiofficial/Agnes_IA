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


def _audio_duration(path: str) -> float:
    """Durée de la piste audio seule (décodage `-map 0:a` — compatible avec le
    ffmpeg du conteneur, qui n'a PAS ffprobe ; retourne 0.0 si pas d'audio)."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-map", "0:a", "-f", "null", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stderr
    m = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if not m:
        return 0.0
    hh, mm, ss = int(m[-1][0]), int(m[-1][1]), float(m[-1][2])
    return hh * 3600 + mm * 60 + ss


def _has_audio(path: str) -> bool:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stderr
    return bool(re.search(r"Stream\s+#\d+:\d+.*Audio:", out))


@pytest.mark.asyncio
async def test_ensure_duration_pads_short_video_with_audio(tmp_path):
    """v8.14 : vidéo 12 s + audio 12 s → padrée à 15 s (bug 3 s avant).
    v8.16 : la piste audio doit AUSSI durer 15 s (apad) — sinon certains
    lecteurs coupent la lecture à la fin de l'audio (12 s)."""
    src = str(tmp_path / "short.mp4")
    _make_short_video_with_audio(src, 12.0)
    assert abs(_duration(src) - 12.0) < 0.5

    out = await ensure_video_duration(src, 15.0)
    dur = _duration(out)
    assert abs(dur - 15.0) <= 0.5, f"durée {dur}s ≠ 15s (bug 3s avant non corrigé)"
    a_dur = _audio_duration(out)
    assert abs(a_dur - 15.0) <= 0.6, f"piste audio {a_dur}s ≠ 15s (lecture coupée à 12s)"


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


@pytest.mark.asyncio
async def test_ensure_duration_pads_video_without_audio(tmp_path):
    """v8.16 : vidéo SANS piste audio (audio désactivé) → 15 s, sans audio."""
    src = str(tmp_path / "noaudio.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc2=duration=12:size=320x240:rate=15",
            "-c:v", "libx264", "-preset", "ultrafast",
            src,
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
    )
    assert abs(_duration(src) - 12.0) < 0.5
    assert not _has_audio(src)

    out = await ensure_video_duration(src, 15.0)
    assert abs(_duration(out) - 15.0) <= 0.5
    assert not _has_audio(out), "une vidéo sans audio ne doit pas gagner de piste audio"


class _FakeStream:
    def __init__(self, data: bytes):
        self._data = data

    async def read(self, *a, **k):
        return self._data

    def decode(self, errors="replace"):
        return self._data.decode(errors=errors)


class _FakeProc:
    def __init__(self, returncode: int, stderr: bytes):
        self.returncode = returncode
        self.stdout = _FakeStream(b"")
        self.stderr = _FakeStream(stderr)

    async def communicate(self):
        return b"", self.stderr._data


@pytest.mark.asyncio
async def test_ensure_duration_retries_without_audio(monkeypatch, tmp_path):
    """v8.15 : si l'encode audio échoue (`-c:a copy`), re-tentative SANS audio
    (`-an`) → la durée cible est garantie même au prix de la piste sonore."""
    src = str(tmp_path / "src.mp4")
    _make_short_video_with_audio(src, 12.0)
    assert abs(_duration(src) - 12.0) < 0.5

    calls = []

    async def fake_exec(*args, **kwargs):
        calls.append(tuple(args))
        # Probe (`ffmpeg -i <path>`) et retry `-an` : exécuter le VRAI ffmpeg.
        if "-an" in args or (len(args) == 3 and args[0] == "ffmpeg" and args[1] == "-i"):
            r = await asyncio.to_thread(subprocess.run, list(args), capture_output=True)
            return _FakeProc(r.returncode, r.stderr)
        # 1er encode (avec `-c:a copy`) : échec simulé → déclenche le retry -an.
        return _FakeProc(1, b"simulated copy failure")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    out = await ensure_video_duration(src, 15.0)
    assert abs(_duration(out) - 15.0) <= 0.5, f"durée {_duration(out)}s ≠ 15s"

    retry_cmd = [a for a in calls if "-an" in a]
    assert retry_cmd, "le retry `-an` n'a pas été déclenché après l'échec simulé"

    # La sortie finale ne doit plus contenir de piste audio (retry -an).
    probe = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", out],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stderr
    assert "Audio:" not in probe, "le retry -an a conservé une piste audio"
