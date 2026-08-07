"""
core/audio/music.py — Musique de fond synthétisée (pas de voix)

Le modèle vidéo Agnes génère des vidéos MUETTES : la seule piste sonore
possible est ajoutée après génération. Pour les bots Vibes, l'utilisateur
ne veut pas de voix de narration → on synthétise une nappe musicale douce
(style « chill / lo-fi ») avec numpy, sans aucune dépendance externe, puis
on la mixe sur la vidéo via le pipeline existant.

v9.6 — variété réelle entre vidéos (l'utilisateur trouvait que « c'est
toujours le même son ») :
  - 16 progressions d'accords (majeur / mineur / ambiances différentes)
  - transposition aléatoire de la tonalité (le seed décale la fondamentale)
  - tempo continu 68-104 BPM (au lieu de 4 valeurs fixes)
  - 4 patterns d'arpège + sonorité (sinusoïde / triangle / douce) selon seed
  - mélodie simple ajoutée selon seed (1 chance sur 2), note aléatoire
  - la durée/nb de mesures reste dérivé du prompt → 2 prompts identiques
    donnent TOUJOURS la même musique (seed dérivé du prompt), mais 2 prompts
    différents ne tombent quasi jamais sur la même combinaison.

Conception :
  - 44.1 kHz stéréo, écriture WAV 16-bit (module stdlib `wave`)
  - basse + pad (nappe) + arpège léger (+ mélodie optionnelle)
  - enveloppes sans clic, fondu de sortie final
"""

from __future__ import annotations

import logging
import math
import wave
from typing import List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100

# Progression d'accords (en degrés tempérés autour de la fondamentale).
# Chaque accord = (fondamentale, tierce, quinte) en demi-tons RELATIFS.
# La transposition finale est appliquée selon le seed. 16 progressions :
# majeur pop, mineur émotionnel, dorien, ambiances neutres…
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
    [(0, 3, 7), (7, 10, 14), (5, 8, 12), (0, 3, 7)],     # i  v  iv i (cinéma)
    [(0, 4, 7), (0, 3, 7), (0, 4, 7), (5, 8, 12)],       # I  i  I  iv (tension)
]

# Transposition possible de la fondamentale (demi-tons) — couvre les 12 tonalités.
_TRANSPOSITIONS = (0, 2, 3, 5, 7, 9, 10, -2, -4, -5, -7, -9, -10, -12, -14, -16)

# Patterns d'arpège : indices dans (fondamentale, tierce, quinte) × octaves
_ARPEGGIO_PATTERNS = (
    (0, 1, 2, 1),             # montée/descente
    (0, 1, 2, 2),             # montée simple
    (0, 2, 1, 0),             # arc
    (0, 2, 2, 1),             # syncope douce
)

_WAVEFORMS = ("sine", "triangle", "soft")  # sonorités différentes

_BASE_TEMPO = 86.0
_TEMPO_SPREAD = 18.0  # ±18 BPM autour de la base → 68-104 BPM


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


def _osc(freq: float, n_samples: int, amp: float, waveform: str,
         attack: float = 0.01, release: float = 0.02) -> np.ndarray:
    """Oscillateur (sinusoïde / triangle / douce) avec enveloppe anti-clic."""
    t = np.arange(n_samples) / SAMPLE_RATE
    phase = 2.0 * math.pi * freq * t
    if waveform == "triangle":
        wave_ = 2.0 * np.abs(2.0 * (phase / (2.0 * math.pi) - np.floor(0.5 + phase / (2.0 * math.pi)))) - 1.0
        wave_ = wave_ * 0.75  # un peu plus doux que le sin
    elif waveform == "soft":
        # Sinusoïde + une harmonique douce → timbre plus riche
        wave_ = np.sin(phase) + 0.30 * np.sin(2.0 * phase) + 0.12 * np.sin(3.0 * phase)
        wave_ = wave_ / 1.42
    else:
        wave_ = np.sin(phase)
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
        seed: variation (progression + tonalité + tempo + arpège + timbre + mélodie).
        tempo: tempo forcé (BPM), 0 = choisi selon seed.

    Returns:
        output_path en cas de succès. Lève une exception en cas d'échec.
    """
    rng = np.random.default_rng(seed)

    progression_idx = seed % len(_PROGRESSIONS)
    progression = _PROGRESSIONS[progression_idx]
    transposition = _TRANSPOSITIONS[seed % len(_TRANSPOSITIONS)]
    bpm = float(tempo) if tempo else _BASE_TEMPO + (seed % 37) * (_TEMPO_SPREAD * 2 / 36) - _TEMPO_SPREAD
    bpm = max(68.0, min(104.0, bpm))
    pattern = _ARPEGGIO_PATTERNS[(seed // 7) % len(_ARPEGGIO_PATTERNS)]
    waveform = _WAVEFORMS[(seed // 13) % len(_WAVEFORMS)]
    melody_on = (seed // 17) % 2 == 0   # mélodie simple 1 fois sur 2
    melody_note = int(rng.integers(0, 5))  # degré de la mélodie

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

        # Basse : fondamentale une octave plus bas
        buffer[start:start + length] += _osc(
            root / 2.0, length, 0.16, waveform, attack=0.15, release=0.15
        )
        # Pad : triade complète, très doux
        for f, amp in ((root, 0.05), (third, 0.045), (fifth, 0.045)):
            buffer[start:start + length] += _osc(f, length, amp, waveform, attack=0.25, release=0.2)
        # Arpège : 8 croches par mesure, pattern selon seed
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
                freq, n_end - n_start, 0.09, "soft" if waveform == "sine" else waveform,
                attack=0.005, release=0.35,
            )
        # Mélodie simple (1 mesure sur 2, si activée) : note tenue, très douce
        if melody_on and bar % 2 == 0:
            m_start = start + int(frames_per_bar * 0.25)
            m_len = min(frames_per_bar // 2, total - m_start)
            if m_len > 0:
                degree = (melody_note + bar) % 5
                scale = (root, third * 2.0, fifth * 2.0, root * 2.0, third * 4.0)
                mel_freq = scale[degree % len(scale)]
                buffer[m_start:m_start + m_len] += _osc(
                    mel_freq, m_len, 0.06, waveform, attack=0.1, release=0.4
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
        f"[Music] Nappe générée: {duration_sec:.1f}s, {bpm:.0f} BPM, "
        f"progression #{progression_idx}, transpo {transposition:+d}, "
        f"pattern {pattern}, timbre {waveform}, mélodie={melody_on} -> {output_path}"
    )
    return output_path
