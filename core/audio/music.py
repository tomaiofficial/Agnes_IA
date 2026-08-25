"""
core/audio/music.py — Musique de fond synthétisee (v2.0 — Organique)

Amelioration majeure v2.0 :
  - Enveloppes ADSD (Attack-Decay-Sustain-Release) plus complexes
  - Timbres plus riches (additif avec harmoniques)
  - Reverb artificielle
  - Compression douce
  - Meilleure stereo imaging
  - Dynamics plus naturelles
"""

from __future__ import annotations

import logging
import math
import wave
from typing import List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100

# Progression d'accords (en degres temperamentes autour de la fondamentale).
# Chaque accord = (fondamentale, tierce, quinte) en demi-tons RELATIFS.
# 16 progressions : majeur pop, mineur emotionnel, dorien, ambiances neutres...
_PROGRESSIONS: List[List[Tuple[int, int, int]]] = [
    # Majeur
    [(0, 4, 7), (5, 9, 12), (7, 11, 14), (9, 13, 16)],   # I  IV  V  VI (pop)
    [(0, 4, 7), (9, 13, 16), (5, 9, 12), (4, 8, 11)],    # I  VI  IV V (50s)
    [(0, 4, 7), (7, 11, 14), (9, 13, 16), (5, 9, 12)],   # I  V   VI IV
    [(0, 4, 7), (5, 9, 12), (9, 13, 16), (7, 11, 14)],   # I  IV  VI V
    [(0, 4, 7), (2, 6, 9), (7, 11, 14), (5, 9, 12)],     # I  II  V  IV
    [(0, 4, 7), (9, 13, 16), (2, 6, 9), (7, 11, 14)],    # I  VI  II V
    [(0, 4, 7), (4, 8, 11), (7, 11, 14), (5, 9, 12)],    # I  III V  IV
    [(0, 4, 7), (9, 13, 16), (5, 9, 12), (7, 11, 14)],   # I  VI  IV V (doux)
    # Mineur
    [(0, 3, 7), (5, 8, 12), (7, 10, 14), (9, 12, 16)],   # i  iv  v  VI
    [(0, 3, 7), (7, 10, 14), (5, 8, 12), (3, 7, 10)],    # i  v  iv III
    [(0, 3, 7), (9, 12, 16), (5, 8, 12), (7, 10, 14)],   # i  VI  iv v
    [(0, 3, 7), (3, 7, 10), (7, 10, 14), (9, 12, 16)],   # i  III v  VI
    [(0, 3, 7), (5, 8, 12), (9, 12, 16), (3, 7, 10)],    # i  iv  VI III
    [(0, 3, 7), (7, 10, 14), (9, 12, 16), (5, 8, 12)],   # i  v   VI iv
    # Ambiances
    [(0, 3, 7), (7, 10, 14), (5, 8, 12), (0, 3, 7)],     # i  v  iv i (cinema)
    [(0, 4, 7), (0, 3, 7), (0, 4, 7), (5, 8, 12)],       # I  i  I  iv (tension)
]

_TRANSPOSITIONS = (0, 2, 3, 5, 7, 9, 10, -2, -4, -5, -7, -9, -10, -12, -14, -16)

_ARPEGGIO_PATTERNS = (
    (0, 1, 2, 1),   # montee/descente
    (0, 1, 2, 2),   # montee simple
    (0, 2, 1, 0),   # arc
    (0, 2, 2, 1),   # syncope douce
)

_WAVEFORMS = ("sine", "triangle", "soft", "rich", "warm")

_BASE_TEMPO = 86.0
_TEMPO_SPREAD = 18.0


def _note_freq(semitone: int) -> float:
    """Frequence d'une note : 0 = do4 (261.63 Hz), +12 = octave au-dessus."""
    return 261.63 * (2 ** (semitone / 12.0))


def _envelope_adsd(n_samples: int, attack: float, decay: float, sustain: float,
                   release: float, sample_rate: int) -> np.ndarray:
    """Enveloppe ADSD (Attack-Decay-Sustain-Release) pour un son plus naturel."""
    a = max(1, int(attack * sample_rate))
    d = max(1, int(decay * sample_rate))
    r = max(1, int(release * sample_rate))

    env = np.ones(n_samples)

    # Attack
    if a < n_samples:
        env[:a] = np.linspace(0.0, 1.0, a)

    # Decay (vers sustain)
    d_end = min(a + d, n_samples)
    if d_end > a:
        env[a:d_end] = np.linspace(1.0, sustain, d_end - a)

    # Sustain (apres decay, avant release)
    if d_end < n_samples - r:
        env[d_end:n_samples - r] = sustain

    # Release
    if r < n_samples:
        env[-r:] *= np.linspace(1.0, 0.0, r)

    return env


def _envelope(n_samples: int, attack: float, release: float, sample_rate: int) -> np.ndarray:
    """Enveloppe d'attaque/relachement douce (anti-clic)."""
    return _envelope_adsd(n_samples, attack, 0.05, 1.0, release, sample_rate)


def _osc(freq: float, n_samples: int, amp: float, waveform: str,
         attack: float = 0.01, release: float = 0.02) -> np.ndarray:
    """Oscillateur avec timbre riche et enveloppe ADSD."""
    t = np.arange(n_samples) / SAMPLE_RATE
    phase = 2.0 * math.pi * freq * t

    if waveform == "triangle":
        wave_ = 2.0 * np.abs(2.0 * (phase / (2.0 * math.pi) - np.floor(0.5 + phase / (2.0 * math.pi)))) - 1.0
        wave_ = wave_ * 0.75
    elif waveform == "soft":
        # Sinusoïde + harmoniques douces
        wave_ = np.sin(phase) + 0.25 * np.sin(2.0 * phase) + 0.10 * np.sin(3.0 * phase)
        wave_ = wave_ / 1.35
    elif waveform == "rich":
        # Plus d'harmoniques pour un timbre plus plein
        wave_ = (np.sin(phase) + 0.35 * np.sin(2.0 * phase) + 0.20 * np.sin(3.0 * phase) +
                 0.10 * np.sin(4.0 * phase) + 0.05 * np.sin(5.0 * phase))
        wave_ = wave_ / 1.70
    elif waveform == "warm":
        # Chaleureux : moins d'harmoniques hautes
        wave_ = np.sin(phase) + 0.30 * np.sin(2.0 * phase) + 0.15 * np.sin(3.0 * phase)
        wave_ = wave_ / 1.45
    else:
        wave_ = np.sin(phase)

    env = _envelope(n_samples, attack, release, SAMPLE_RATE)
    return amp * wave_ * env


def _reverb_simple(sig: np.ndarray, decay: float = 0.2, delays_ms: list = None) -> np.ndarray:
    """Reverb artificielle simple."""
    if delays_ms is None:
        delays_ms = [23, 37, 53, 71]
    out = sig.copy()
    for d_ms in delays_ms:
        delay_samples = int(d_ms * SAMPLE_RATE / 1000)
        decay_factor = decay * (1.0 - d_ms / 100.0)
        delayed = np.zeros_like(sig)
        if delay_samples < len(sig):
            delayed[delay_samples:] = sig[:-delay_samples] * decay_factor
        out += delayed
    return out * 0.75


def _soft_compressor(sig: np.ndarray, threshold: float = 0.6, ratio: float = 3.0) -> np.ndarray:
    """Compression douce pour des dynamics plus naturelles."""
    abs_sig = np.abs(sig)
    mask = abs_sig > threshold
    if not np.any(mask):
        return sig
    compressed = sig.copy()
    excess = abs_sig[mask] - threshold
    compressed[mask] = np.sign(sig[mask]) * (threshold + excess / ratio)
    return compressed


def generate_background_music(
    duration_sec: float,
    output_path: str,
    seed: int = 0,
    tempo: int = 0,
) -> str:
    """Genere une nappe musicale douce de `duration_sec` et l'ecrit en WAV.

    v2.0 : plus organique, meilleurs timbres, reverb, compression douce.

    Args:
        duration_sec: duree de la musique.
        output_path: chemin WAV de sortie.
        seed: variation (progression + tonalite + tempo + arpege + timbre + melodie).
        tempo: tempo force (BPM), 0 = choisi selon seed.

    Returns:
        output_path en cas de succes.
    """
    rng = np.random.default_rng(seed)

    progression_idx = seed % len(_PROGRESSIONS)
    progression = _PROGRESSIONS[progression_idx]
    transposition = _TRANSPOSITIONS[seed % len(_TRANSPOSITIONS)]
    bpm = float(tempo) if tempo else _BASE_TEMPO + (seed % 37) * (_TEMPO_SPREAD * 2 / 36) - _TEMPO_SPREAD
    bpm = max(68.0, min(104.0, bpm))
    pattern = _ARPEGGIO_PATTERNS[(seed // 7) % len(_ARPEGGIO_PATTERNS)]
    waveform = _WAVEFORMS[(seed // 13) % len(_WAVEFORMS)]
    melody_on = (seed // 17) % 2 == 0
    melody_note = int(rng.integers(0, 5))

    bar_sec = 60.0 / bpm * 4.0
    n_bars = max(1, int(math.ceil(duration_sec / bar_sec)))

    frames_per_bar = int(bar_sec * SAMPLE_RATE)
    total = int(duration_sec * SAMPLE_RATE)
    buffer = np.zeros(total)

    def _chord_notes(chord):
        root, third, fifth = (d + transposition for d in chord)
        return (_note_freq(root), _note_freq(third), _note_freq(fifth))

    for bar in range(n_bars):
        start = bar * frames_per_bar
        length = min(frames_per_bar, total - start)
        if length <= 0:
            break
        chord = progression[bar % len(progression)]
        root, third, fifth = _chord_notes(chord)

        # Basse : fondamentale une octave plus bas, timbre riche
        buffer[start:start + length] += _osc(
            root / 2.0, length, 0.14, waveform, attack=0.2, release=0.2
        )

        # Pad : triade complete, enveloppe ADSD pour un son plus organique
        for f, amp in ((root, 0.045), (third, 0.04), (fifth, 0.04)):
            pad_env = _envelope_adsd(length, 0.3, 0.1, 0.7, 0.25, SAMPLE_RATE)
            t = np.arange(length) / SAMPLE_RATE
            phase = 2.0 * math.pi * f * t
            # Pad avec legere modulation pour eviter le "synthetiseur basique"
            mod = 1.0 + 0.003 * np.sin(2.0 * math.pi * 0.5 * t)
            signal = (np.sin(phase * mod) + 0.2 * np.sin(2.0 * phase * mod)) / 1.2
            buffer[start:start + length] += signal * amp * pad_env

        # Arpege : 8 croches par mesure, timbre "soft"
        n_notes = 8
        note_len = max(1, frames_per_bar // n_notes)
        for i in range(n_notes):
            n_start = start + i * note_len
            if n_start >= total:
                break
            n_end = min(n_start + note_len, total)
            idx = pattern[i % len(pattern)]
            freq = (root * 4.0, third * 4.0, fifth * 4.0)[idx]
            buffer[n_start:n_end] += _osc(
                freq, n_end - n_start, 0.07, "soft",
                attack=0.008, release=0.3,
            )

        # Melodie simple (1 mesure sur 2, si activee)
        if melody_on and bar % 2 == 0:
            m_start = start + int(frames_per_bar * 0.25)
            m_len = min(frames_per_bar // 2, total - m_start)
            if m_len > 0:
                degree = (melody_note + bar) % 5
                scale = (root, third * 2.0, fifth * 2.0, root * 2.0, third * 4.0)
                mel_freq = scale[degree % len(scale)]
                buffer[m_start:m_start + m_len] += _osc(
                    mel_freq, m_len, 0.05, waveform, attack=0.12, release=0.4
                )

    # Reverb legere pour un son plus "dans l'espace"
    buffer = _reverb_simple(buffer, decay=0.12, delays_ms=[20, 40, 60])

    # Compression douce
    buffer = _soft_compressor(buffer, threshold=0.65, ratio=2.5)

    # Normalisation + fondu de sortie final
    peak = float(np.max(np.abs(buffer))) or 1.0
    buffer = buffer * (0.82 / peak)
    fade = int(0.2 * SAMPLE_RATE)
    if fade < len(buffer):
        buffer[-fade:] *= np.linspace(1.0, 0.0, fade)

    # Stereo : arpège légèrement à gauche, pad/basse au centre
    left = buffer
    right = buffer * 0.90
    # Ajouter un leger delay sur le right pour plus de profondeur
    haas = int(0.008 * SAMPLE_RATE)
    right_delayed = np.roll(right, haas)
    right_delayed[:haas] = 0.0
    stereo = np.stack((left, right_delayed), axis=1)
    pcm = (np.clip(stereo, -1.0, 1.0) * 32767).astype(np.int16)

    with wave.open(output_path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())

    logger.info(
        f"[Music] Nappe generee: {duration_sec:.1f}s, {bpm:.0f} BPM, "
        f"progression #{progression_idx}, transpo {transposition:+d}, "
        f"pattern {pattern}, timbre {waveform}, melodie={melody_on} -> {output_path}"
    )
    return output_path
