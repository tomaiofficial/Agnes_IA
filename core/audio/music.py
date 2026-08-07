"""
core/audio/music.py — Musique de fond synthétisée (pas de voix)

Le modèle vidéo Agnes génère des vidéos MUETTES : la seule piste sonore
possible est ajoutée après génération. Pour les bots Vibes, l'utilisateur
ne veut pas de voix de narration → on synthétise une nappe musicale douce
(style « chill / lo-fi ») avec numpy, sans aucune dépendance externe, puis
on la mixe sur la vidéo via le pipeline existant.

Conception :
  - 44.1 kHz stéréo, écriture WAV 16-bit (module stdlib `wave`)
  - progression d'accords au choix selon seed (variation entre vidéos)
  - basse + pad (nappe) + arpège léger, enveloppes sans clic
  - boucles par mesure, fondu de sortie final
"""

from __future__ import annotations

import logging
import math
import wave
from typing import List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100

# Progression d'accords (dans une tonalité, en notes absolues relatives à A4=440).
# Chaque accord = (fondamentale_deg, tierce_deg, quinte_deg) en degrés tempérés
# autour de la note de référence. Am-F-C-G et dérivés : très agréables, neutres.
# (0 = do, 2 = ré, 4 = mi, 5 = fa, 7 = sol, 9 = la, 11 = si)

_PROGRESSIONS: List[List[Tuple[int, int, int]]] = [
    [(9, 12, 16), (5, 8, 12), (0, 4, 7), (7, 11, 14)],  # Am  F  C  G
    [(0, 4, 7), (7, 11, 14), (9, 12, 16), (5, 8, 12)],  # C   G  Am F
    [(7, 11, 14), (2, 6, 9), (9, 12, 16), (0, 4, 7)],   # G   D  Em C
]

_TEMPI = (76, 80, 84, 88)


def _note_freq(semitone: int) -> float:
    """Fréquence d'une note : 0 = do4 (261.63 Hz), +12 = octave au-dessus."""
    return 261.63 * (2 ** (semitone / 12.0))


def _envelope(n_samples: int, attack: float, release: float, sample_rate: int) -> np.ndarray:
    """Enveloppe d'attaque/relâchement douce (évite les clics)."""
    a = max(1, int(attack * sample_rate))
    r = max(1, int(release * sample_rate))
    env = np.ones(n_samples)
    if a < n_samples:
        env[:a] = np.linspace(0.0, 1.0, a)
    if r < n_samples:
        env[-r:] *= np.linspace(1.0, 0.0, r)
    return env


def _tone(freq: float, n_samples: int, amp: float, attack: float = 0.01, release: float = 0.02) -> np.ndarray:
    """Sinusoïde simple avec enveloppe anti-clic."""
    t = np.arange(n_samples) / SAMPLE_RATE
    wave_ = np.sin(2.0 * math.pi * freq * t)
    return amp * wave_ * _envelope(n_samples, attack, release, SAMPLE_RATE)


def generate_background_music(
    duration_sec: float,
    output_path: str,
    seed: int = 0,
    tempo: int = 0,
) -> str:
    """Génère une nappe musicale douce de `duration_sec` et l'écrit en WAV.

    Args:
        duration_sec: durée de la musique (≈ durée de la vidéo).
        output_path: chemin WAV de sortie.
        seed: variation (progression d'accords + tempo) entre les vidéos.
        tempo: tempo forcé (BPM), 0 = choisi selon seed.

    Returns:
        output_path en cas de succès. Lève une exception en cas d'échec.
    """
    rng = np.random.default_rng(seed)
    progression = _PROGRESSIONS[seed % len(_PROGRESSIONS)]
    bpm = tempo or _TEMPI[seed % len(_TEMPI)]
    bar_sec = 60.0 / bpm * 4.0
    n_bars = max(1, int(math.ceil(duration_sec / bar_sec)))

    frames_per_bar = int(bar_sec * SAMPLE_RATE)
    total = int(duration_sec * SAMPLE_RATE)
    buffer = np.zeros(total)

    for bar in range(n_bars):
        start = bar * frames_per_bar
        length = min(frames_per_bar, total - start)
        if length <= 0:
            break
        chord = progression[bar % len(progression)]
        root, third, fifth = (_note_freq(d) for d in chord)

        # Basse : fondamentale une octave plus bas
        buffer[start:start + length] += _tone(
            root / 2.0, length, 0.16, attack=0.15, release=0.15
        )
        # Pad : triade complète, très doux
        for f, amp in ((root, 0.05), (third, 0.045), (fifth, 0.045)):
            buffer[start:start + length] += _tone(f, length, amp, attack=0.25, release=0.2)
        # Arpège : 8 croches par mesure (montée/descente), léger
        n_notes = 8
        note_len = max(1, frames_per_bar // n_notes)
        pattern = (0, 2, 1, 2)  # indices 0=fond., 1=tierce, 2=quinte
        for i in range(n_notes):
            n_start = start + i * note_len
            if n_start >= total:
                break
            n_end = min(n_start + note_len, total)
            idx = pattern[i % len(pattern)]
            freq = (root * 4.0, third * 4.0, fifth * 4.0)[idx]
            buffer[n_start:n_end] += _tone(
                freq, n_end - n_start, 0.09, attack=0.005, release=0.35
            )

    # Normalisation douce + fondu de sortie final (anti-clic)
    peak = float(np.max(np.abs(buffer))) or 1.0
    buffer = buffer * (0.85 / peak)
    fade = int(0.15 * SAMPLE_RATE)
    if fade < len(buffer):
        buffer[-fade:] *= np.linspace(1.0, 0.0, fade)

    # Stéréo : arpège légèrement à gauche, pad/basse au centre
    left = buffer
    right = buffer * 0.92
    stereo = np.stack((left, right), axis=1)
    pcm = (np.clip(stereo, -1.0, 1.0) * 32767).astype(np.int16)

    with wave.open(output_path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())

    logger.info(
        f"[Music] Nappe générée: {duration_sec:.1f}s, {bpm} BPM, "
        f"progression #{seed % len(_PROGRESSIONS)} -> {output_path}"
    )
    return output_path
