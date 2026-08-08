"""
core/audio/ambiance.py — Paysage sonore de scène synthétisé (« son réel »)

L'utilisateur veut que les vidéos des bots aient le son de la scène (comme
Sora 2) et non une nappe musicale. Le modèle vidéo Agnes (agnes-video-v2.0)
génère des vidéos MUETTES : aucune piste audio native n'existe à conserver, et
Sora 2 (génération audio-vidéo) n'est pas accessible. Sans modèle dédié, on
synthétise un paysage sonore procédural cohérent avec le prompt de la vidéo :
vagues, pluie, orage, vent, feu, forêt, oiseaux, ville, foule, chute d'eau,
rivière, grillons de nuit, neige, désert, espace, ambiance neutre.

Conception :
  - 44.1 kHz stéréo, WAV 16-bit (module stdlib `wave`), numpy seul (aucune
    dépendance externe, comme core/audio/music.py)
  - bruits colorés (blanc / rose / brun) filtrés par FFT (rampes douces)
  - la scène est détectée par mots-clés FR/EN dans le prompt
  - le seed dérive du prompt : 2 prompts identiques → même son ; 2 prompts
    différents → scènes (et grains de détail) différents
  - fondu d'entrée/sortie anti-clic, normalisation douce, stéréo léger delay
"""

from __future__ import annotations

import logging
import math
import re
import wave
from typing import Callable, List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100

# ── Scènes détectées par mots-clés ──────────────────────────────────────────
# (nom, [(mot-clé, ...)]). La PREMIÈRE scène dont un mot-clé est trouvé dans le
# prompt gagne : l'ordre du tuple EST la priorité.
_SCENES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("orage",      ("orage", "storm", "thunder", "tonnerre", "éclair", "lightning", "eclair")),
    ("chute_eau",  ("cascade", "waterfall", "chute d'eau", "chutes")),
    ("pluie",      ("pluie", "pleut", "rain", "averse", "drizzle", "pluvieux", "rainy")),
    ("mer",        ("mer", "ocean", "océan", "sea", "vague", "waves", "beach", "plage", "mar", "lagon", "lagoon")),
    ("riviere",    ("rivière", "riviere", "river", "ruisseau", "stream", "creek", "torrent")),
    ("feu",        ("feu de camp", "campfire", "fireplace", "cheminée", "cheminee", "brasero", "flamme", "flame", "bonfire")),
    ("foret",      ("forêt", "foret", "forest", "jungle", "arbres", "trees", "bois sauvage")),
    ("oiseaux",    ("oiseau", "oiseaux", "bird", "birds", "chant des oiseaux")),
    # ville/foule AVANT nuit : « la ville la nuit » sonne ville (trafic),
    # « la nuit » seule sonne grillons.
    ("ville",      ("ville", "city", "urban", "rue", "street", "traffic", "circulation", "métropole", "metropole")),
    ("foule",      ("foule", "crowd", "marché", "marche", "market", "concert", "festival", "place publique")),
    ("nuit",       ("nuit", "night", "soir", "evening", "camping", "grillon", "cricket", "crickets")),
    ("neige",      ("neige", "snow", "hiver", "winter", "blizzard", "montagne enneigée")),
    ("desert",     ("désert", "desert", "dune", "sahara")),
    ("espace",     ("espace", "space", "galaxie", "galaxy", "cosmos", "univers", "nébuleuse", "nebula")),
    ("vent",       ("vent", "wind", "brise", "breeze", "rafale", "gust")),
)

# Scène par défaut si aucun mot-clé ne matche.
_DEFAULT_SCENE = "ambiant"


def detect_scene(prompt: str) -> str:
    """Détecte la scène d'un prompt par mots-clés FR/EN (insensible à la casse)."""
    text = (prompt or "").lower()
    for name, keywords in _SCENES:
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", text):
                return name
    return _DEFAULT_SCENE


# ── Utilitaires de synthèse ─────────────────────────────────────────────────

def _white(rng: np.random.Generator, n: int) -> np.ndarray:
    return rng.standard_normal(n).astype(np.float64)


def _brown(rng: np.random.Generator, n: int) -> np.ndarray:
    """Bruit brun (-6 dB/oct) : marche aléatoire, DC enlevé."""
    x = np.cumsum(_white(rng, n))
    x -= np.linspace(x[0], x[-1], n)  # enlève la dérive DC
    return x


def _pink(rng: np.random.Generator, n: int) -> np.ndarray:
    """Bruit rose (-3 dB/oct) via FFT."""
    spec = np.fft.rfft(_white(rng, n))
    freqs = np.fft.rfftfreq(n, 1.0 / SAMPLE_RATE)
    freqs[0] = 1.0
    spec = spec / np.sqrt(freqs)
    x = np.fft.irfft(spec, n)
    peak = float(np.max(np.abs(x))) or 1.0
    return x / peak


def _bandpass(sig: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Passe-bande doux par FFT (rampes sigmoïdes en échelle log)."""
    n = len(sig)
    spec = np.fft.rfft(sig)
    freqs = np.fft.rfftfreq(n, 1.0 / SAMPLE_RATE)
    f = np.log10(np.maximum(freqs, 1e-9))
    mask = 1.0 / (1.0 + np.exp(-(f - np.log10(max(lo, 1.0))) * 14.0))
    mask *= 1.0 / (1.0 + np.exp((f - np.log10(max(hi, lo + 1.0))) * 14.0))
    spec *= mask
    return np.fft.irfft(spec, n)


def _lfo(freq: float, n: int, phase: float = 0.0) -> np.ndarray:
    """Oscillateur lent 0→1 (pour moduler l'amplitude)."""
    t = np.arange(n) / SAMPLE_RATE
    return 0.5 * (1.0 + np.sin(2.0 * math.pi * freq * t + phase))


def _fade(sig: np.ndarray, fade_in: float, fade_out: float) -> np.ndarray:
    out = sig.copy()
    fi = int(fade_in * SAMPLE_RATE)
    fo = int(fade_out * SAMPLE_RATE)
    if fi > 0 and fi < len(out):
        out[:fi] *= np.linspace(0.0, 1.0, fi)
    if fo > 0 and fo < len(out):
        out[-fo:] *= np.linspace(1.0, 0.0, fo)
    return out


def _normalize(sig: np.ndarray, peak: float = 0.8) -> np.ndarray:
    m = float(np.max(np.abs(sig))) or 1.0
    return sig * (peak / m)


# ── Générateurs par scène ───────────────────────────────────────────────────

def _scene_waves(rng, n, duration):
    """Mer : houle basse + ressac (éclaboussures) alternés."""
    base = _bandpass(_brown(rng, n), 40, 350)
    swash = _bandpass(_white(rng, n), 500, 2800)
    swell = _lfo(0.08 + rng.uniform(0.0, 0.05), n)
    swash_mod = _lfo(0.11 + rng.uniform(0.0, 0.04), n, phase=1.7)
    return base * (0.65 + 0.5 * swell) + swash * 0.22 * swash_mod


def _scene_rain(rng, n, duration):
    """Pluie : bruit dense haute fréquence, grain rapide."""
    rain = _bandpass(_white(rng, n), 1000, 9500)
    grain = rng.uniform(0.85, 1.15, n)
    return rain * grain


def _scene_storm(rng, n, duration):
    """Orage : pluie soutenue + coups de tonnerre lointains."""
    rain = _bandpass(_white(rng, n), 800, 8000) * rng.uniform(0.9, 1.1, n)
    thunder = np.zeros(n)
    n_coups = int(rng.integers(3, 6))
    for _ in range(n_coups):
        t0 = int(rng.uniform(0.0, max(duration - 2.5, 0.01)) * SAMPLE_RATE)
        length = int(rng.uniform(1.2, 3.0) * SAMPLE_RATE)
        if t0 + length > n:
            length = n - t0
        if length <= 0:
            continue
        body = _bandpass(_brown(rng, length), 40, 160)
        env = np.exp(-np.linspace(0.0, 4.5, length))  # décroissance lente
        thunder[t0:t0 + length] += body * env * rng.uniform(0.8, 1.4)
    return rain * 0.55 + thunder


def _scene_wind(rng, n, duration):
    """Vent : bruit rose modulé par des rafales lentes."""
    wind = _bandpass(_pink(rng, n), 150, 1800)
    gust = _lfo(rng.uniform(0.06, 0.22), n) * _lfo(rng.uniform(0.5, 1.1), n, phase=2.0)
    return wind * (0.5 + 0.5 * gust)


def _scene_fire(rng, n, duration):
    """Feu de camp : grondement bas + crépitements secs."""
    base = _bandpass(_brown(rng, n), 60, 600)
    crackle = np.zeros(n)
    n_pops = int(duration * rng.uniform(10.0, 22.0))
    for _ in range(n_pops):
        t0 = int(rng.uniform(0.0, max(duration - 0.1, 0.01)) * SAMPLE_RATE)
        length = int(rng.uniform(0.02, 0.09) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        pop = _bandpass(_white(rng, length), 1200, 6500)
        env = np.exp(-np.linspace(0.0, 6.0, length))
        crackle[t0:t0 + length] += pop * env * rng.uniform(0.3, 1.0)
    return base * 0.5 + crackle * 0.55


def _chirp(rng, n, sr=SAMPLE_RATE):
    """Un chant d'oiseau : sinusoïde FM montante courte."""
    f0 = rng.uniform(2200.0, 3600.0)
    f1 = rng.uniform(3800.0, 5600.0)
    t = np.arange(n) / sr
    phase = 2.0 * math.pi * (f0 * t + (f1 - f0) * t * t / (2.0 * max(n / sr, 1e-9)))
    env = np.sin(np.linspace(0.0, math.pi, n)) ** 2  # arche douce
    return np.sin(phase) * env


def _scene_forest(rng, n, duration):
    """Forêt : vent doux dans les feuilles + chants d'oiseaux."""
    wind = _bandpass(_pink(rng, n), 200, 1400) * (0.35 + 0.3 * _lfo(rng.uniform(0.1, 0.3), n))
    rustle = _bandpass(_white(rng, n), 2500, 8500) * 0.08
    birds = np.zeros(n)
    n_chirps = int(duration * rng.uniform(0.6, 1.6))
    for _ in range(n_chirps):
        t0 = int(rng.uniform(0.0, max(duration - 0.4, 0.05)) * SAMPLE_RATE)
        length = int(rng.uniform(0.12, 0.45) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        birds[t0:t0 + length] += _chirp(rng, length) * rng.uniform(0.25, 0.6)
    return wind + rustle + birds


def _scene_birds(rng, n, duration):
    """Oiseaux dominants (même base que la forêt, plus de chants)."""
    wind = _bandpass(_pink(rng, n), 200, 1400) * 0.3
    birds = np.zeros(n)
    n_chirps = int(duration * rng.uniform(2.0, 4.0))
    for _ in range(n_chirps):
        t0 = int(rng.uniform(0.0, max(duration - 0.4, 0.05)) * SAMPLE_RATE)
        length = int(rng.uniform(0.1, 0.4) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        birds[t0:t0 + length] += _chirp(rng, length) * rng.uniform(0.3, 0.7)
    return wind + birds


def _scene_night(rng, n, duration):
    """Nuit : grillons réguliers + vent très léger."""
    wind = _bandpass(_pink(rng, n), 150, 900) * 0.25
    crickets = np.zeros(n)
    period = SAMPLE_RATE / rng.uniform(2.0, 3.2)
    pulse = int(period * 0.22)
    t0 = 0
    while t0 + pulse < n:
        t = np.arange(pulse) / SAMPLE_RATE
        f = rng.uniform(4000.0, 4600.0)
        env = (np.sin(np.linspace(0.0, math.pi, pulse)) ** 2) * 0.35
        crickets[t0:t0 + pulse] += np.sin(2.0 * math.pi * f * t) * env
        t0 += int(period)
    return wind + crickets


def _scene_city(rng, n, duration):
    """Ville : ronronnement lointain + circulation qui passe."""
    hum = 0.12 * np.sin(2.0 * math.pi * 60.0 * np.arange(n) / SAMPLE_RATE)
    hum += 0.05 * np.sin(2.0 * math.pi * 120.0 * np.arange(n) / SAMPLE_RATE)
    traffic = _bandpass(_brown(rng, n), 80, 500)
    pass_by = _lfo(rng.uniform(0.05, 0.12), n) ** 3  # crêtes espacées
    return hum + traffic * (0.35 + 0.6 * pass_by)


def _scene_crowd(rng, n, duration):
    """Foule : murmure dense et mouvant."""
    babble = _bandpass(_pink(rng, n), 250, 2600)
    waves = _lfo(rng.uniform(0.2, 0.8), n) * _lfo(rng.uniform(1.5, 3.0), n, phase=1.0)
    return babble * (0.5 + 0.5 * waves)


def _scene_waterfall(rng, n, duration):
    """Chute d'eau : souffle blanc puissant + grondement."""
    sizzle = _bandpass(_white(rng, n), 1200, 10000)
    rumble = _bandpass(_brown(rng, n), 50, 350)
    return sizzle * 0.8 + rumble * 0.5


def _scene_river(rng, n, duration):
    """Rivière : gargouillis large, doucement ondulé."""
    flow = _bandpass(_white(rng, n), 300, 4200)
    return flow * (0.6 + 0.4 * _lfo(rng.uniform(0.15, 0.45), n))


def _scene_snow(rng, n, duration):
    """Neige : vent feutré + tintements glacés très rares."""
    wind = _bandpass(_pink(rng, n), 200, 1100) * 0.4
    chimes = np.zeros(n)
    n_rings = max(1, int(duration * 0.8))
    for _ in range(n_rings):
        t0 = int(rng.uniform(0.0, max(duration - 1.0, 0.05)) * SAMPLE_RATE)
        length = int(rng.uniform(0.3, 1.2) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        f = rng.uniform(4200.0, 7800.0)
        t = np.arange(length) / SAMPLE_RATE
        env = np.exp(-t * 6.0)
        chimes[t0:t0 + length] += np.sin(2.0 * math.pi * f * t) * env * 0.25
    return wind + chimes


def _scene_desert(rng, n, duration):
    """Désert : vent sec et régulier, aucun oiseau."""
    wind = _bandpass(_pink(rng, n), 250, 1200)
    return wind * (0.55 + 0.3 * _lfo(rng.uniform(0.05, 0.12), n))


def _scene_space(rng, n, duration):
    """Espace : nappe grave éthérée, très spacieuse."""
    t = np.arange(n) / SAMPLE_RATE
    drone = 0.20 * np.sin(2.0 * math.pi * 55.0 * t)
    drone += 0.10 * np.sin(2.0 * math.pi * 82.5 * t + 0.5)
    drone += 0.07 * np.sin(2.0 * math.pi * 110.0 * t + 1.1)
    shimmer = _bandpass(_white(rng, n), 2000, 9000) * 0.04
    slow = 1.0 + 0.06 * np.sin(2.0 * math.pi * 0.07 * t)  # vibrato lent
    return (drone + shimmer) * slow


def _scene_ambiant(rng, n, duration):
    """Défaut : vent très léger, neutre et inoffensif."""
    wind = _bandpass(_pink(rng, n), 150, 800) * 0.3
    return wind * (0.6 + 0.3 * _lfo(rng.uniform(0.1, 0.2), n))


_SCENE_GENERATORS: dict = {
    "orage": _scene_storm,
    "chute_eau": _scene_waterfall,
    "pluie": _scene_rain,
    "mer": _scene_waves,
    "riviere": _scene_river,
    "feu": _scene_fire,
    "foret": _scene_forest,
    "oiseaux": _scene_birds,
    "nuit": _scene_night,
    "ville": _scene_city,
    "foule": _scene_crowd,
    "neige": _scene_snow,
    "desert": _scene_desert,
    "espace": _scene_space,
    "vent": _scene_wind,
    "ambiant": _scene_ambiant,
}


def generate_scene_sound(
    duration_sec: float,
    output_path: str,
    prompt: str,
    seed: int = 0,
) -> str:
    """Génère le paysage sonore de la scène décrite par `prompt` et l'écrit en WAV.

    Args:
        duration_sec: durée du son (≈ durée de la vidéo).
        output_path: chemin WAV de sortie.
        prompt: prompt de la vidéo (détection de scène par mots-clés FR/EN).
        seed: variation du grain (dérivé du prompt → déterministe par prompt).

    Returns:
        output_path en cas de succès. Lève une exception en cas d'échec.
    """
    scene = detect_scene(prompt)
    rng = np.random.default_rng(seed)

    duration_sec = max(0.5, float(duration_sec))
    n = int(duration_sec * SAMPLE_RATE)

    generator = _SCENE_GENERATORS[scene]
    mix = generator(rng, n, duration_sec)

    mix = _fade(mix, 0.05, 0.25)
    mix = _normalize(mix, peak=0.8)

    # Stéréo : léger décalage temporel (Haas) → profondeur sans artefacts.
    haas = int(0.009 * SAMPLE_RATE)
    right = np.roll(mix, haas)
    right[:haas] = 0.0
    stereo = np.stack((mix, right * 0.97), axis=1)
    pcm = (np.clip(stereo, -1.0, 1.0) * 32767).astype(np.int16)

    with wave.open(output_path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())

    logger.info(
        f"[Ambiance] Scène « {scene} » ({duration_sec:.1f}s, seed {seed}) "
        f"-> {output_path}"
    )
    return output_path
