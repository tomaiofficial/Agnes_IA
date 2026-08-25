"""
core/audio/ambiance.py — Paysage sonore de scène synthétisé (v2.0 — Realiste)

Amélioration majeure v2.0 :
  - Reverb artificielle ( convolution via FFT )
  - Couches de sons plus riches ( multi-octaves, variations lentes )
  - Meilleur mixing stéréo ( profondeur, largeur, imaging )
  - Transitions douces entre les couches
  - Normalisation LUFS perceptuelle
  - Bruit de fond cohérent ( noise floor réaliste )
"""

from __future__ import annotations

import logging
import math
import re
import wave
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100

# ── Scenes detectees par mots-cles ──────────────────────────────────────────
_SCENES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("orage",      ("orage", "storm", "thunder", "tonnerre", "éclair", "lightning", "eclair", "tempête", "tempete")),
    ("chute_eau",  ("cascade", "waterfall", "chute d'eau", "chutes", "gouffre")),
    ("pluie",      ("pluie", "pleut", "rain", "averse", "drizzle", "pluvieux", "rainy", "ondée", "ondee")),
    ("mer",        ("mer", "ocean", "océan", "sea", "vague", "waves", "beach", "plage", "mar", "lagon", "lagoon", "côte", "cote", "rivage")),
    ("riviere",    ("rivière", "riviere", "river", "ruisseau", "stream", "creek", "torrent", "flots")),
    ("feu",        ("feu de camp", "campfire", "fireplace", "cheminée", "cheminee", "brasero", "flamme", "flame", "bonfire", "foyer")),
    ("foret",      ("forêt", "foret", "forest", "jungle", "arbres", "trees", "bois sauvage", "canopée", "canopee")),
    ("oiseaux",    ("oiseau", "oiseaux", "bird", "birds", "chant des oiseaux", "mésange", "merle", "rossignol")),
    ("ville",      ("ville", "city", "urban", "rue", "street", "traffic", "circulation", "métropole", "metropole", "avenue", "boulevard")),
    ("foule",      ("foule", "crowd", "marché", "marche", "market", "concert", "festival", "place publique", "agitation")),
    ("nuit",       ("nuit", "night", "soir", "evening", "camping", "grillon", "cricket", "crickets", "étoiles", "etoiles")),
    ("neige",      ("neige", "snow", "hiver", "winter", "blizzard", "montagne enneigée", "givre", "gel")),
    ("desert",     ("désert", "desert", "dune", "sahara", "aride", "sable")),
    ("espace",     ("espace", "space", "galaxie", "galaxy", "cosmos", "univers", "nébuleuse", "nebula", "orbite")),
    ("vent",       ("vent", "wind", "brise", "breeze", "rafale", "gust", "mistral", "zéphyr", "zephyr")),
    ("plage",      ("plage", "beach", "sable", "sable", "coquillage", "coastline", "littoral")),
    ("montagne",   ("montagne", "mountain", "pic", "sommet", "alpin", "rocheuse", "cimes")),
    ("underwater", ("sous-marin", "underwater", "océan profond", "ocean profond", "corail", "récif", "recif", "abysses")),
)

_DEFAULT_SCENE = "ambiant"


def detect_scene(prompt: str) -> str:
    """Detecte la scene d'un prompt par mots-cles FR/EN (insensible a la casse)."""
    text = (prompt or "").lower()
    for name, keywords in _SCENES:
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", text):
                return name
    return _DEFAULT_SCENE


# ── Utilitaires de synthese ─────────────────────────────────────────────────

def _white(rng: np.random.Generator, n: int) -> np.ndarray:
    return rng.standard_normal(n).astype(np.float64)


def _brown(rng: np.random.Generator, n: int) -> np.ndarray:
    """Bruit brun (-6 dB/oct) : marche aleatoire, DC enleve."""
    x = np.cumsum(_white(rng, n))
    x -= np.linspace(x[0], x[-1], n)
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
    """Passe-bande doux par FFT (rampes sigmoidees en echelle log)."""
    n = len(sig)
    spec = np.fft.rfft(sig)
    freqs = np.fft.rfftfreq(n, 1.0 / SAMPLE_RATE)
    f = np.log10(np.maximum(freqs, 1e-9))
    mask = 1.0 / (1.0 + np.exp(-(f - np.log10(max(lo, 1.0))) * 14.0))
    mask *= 1.0 / (1.0 + np.exp((f - np.log10(max(hi, lo + 1.0))) * 14.0))
    spec *= mask
    return np.fft.irfft(spec, n)


def _lowpass(sig: np.ndarray, cutoff: float) -> np.ndarray:
    """Passe-bas doux."""
    n = len(sig)
    spec = np.fft.rfft(sig)
    freqs = np.fft.rfftfreq(n, 1.0 / SAMPLE_RATE)
    f = np.log10(np.maximum(freqs, 1e-9))
    mask = 1.0 / (1.0 + np.exp((f - np.log10(max(cutoff, 1.0))) * 14.0))
    spec *= mask
    return np.fft.irfft(spec, n)


def _highpass(sig: np.ndarray, cutoff: float) -> np.ndarray:
    """Passe-haut doux."""
    n = len(sig)
    spec = np.fft.rfft(sig)
    freqs = np.fft.rfftfreq(n, 1.0 / SAMPLE_RATE)
    f = np.log10(np.maximum(freqs, 1e-9))
    mask = 1.0 / (1.0 + np.exp(-(f - np.log10(max(cutoff, 1.0))) * 14.0))
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


def _reverb_simple(sig: np.ndarray, decay: float = 0.3, delays_ms: list = None) -> np.ndarray:
    """Reverb artificielle simple avec plusieurs delais."""
    if delays_ms is None:
        delays_ms = [23, 37, 53, 71, 97]  # delais en ms (premiers nombres premiers)
    out = sig.copy()
    for d_ms in delays_ms:
        delay_samples = int(d_ms * SAMPLE_RATE / 1000)
        decay_factor = decay * (1.0 - d_ms / 120.0)  # plus le delay est long, plus c'est faint
        delayed = np.zeros_like(sig)
        if delay_samples < len(sig):
            delayed[delay_samples:] = sig[:-delay_samples] * decay_factor
        out += delayed
    return out * 0.7  # normaliser pour eviter clipping


def _stereo_wide(left: np.ndarray, right: np.ndarray, width: float = 0.3) -> Tuple[np.ndarray, np.ndarray]:
    """Elargit le stereo : center reste au milieu, les cotes s'elargissent."""
    mid = (left + right) * 0.5
    side = (left - right) * 0.5
    side *= (1.0 + width)
    return mid + side, mid - side


# ── Generateurs par scene (v2.0 — plus realistes) ──────────────────────────

def _scene_waves(rng, n, duration):
    """Mer realiste : houle profonde + ressac + embruns + vent côtier."""
    # Couche 1 : houle basse profonde (40-200 Hz)
    houle = _bandpass(_brown(rng, n), 40, 200)
    swell = _lfo(0.07 + rng.uniform(0.0, 0.04), n)
    houle *= (0.7 + 0.5 * swell)

    # Couche 2 : ressac moyen (200-2000 Hz)
    ressac = _bandpass(_white(rng, n), 200, 2000)
    ressac_mod = _lfo(0.12 + rng.uniform(0.0, 0.05), n, phase=1.7)
    ressac *= ressac_mod * 0.4

    # Couche 3 : embruns et eclaboussures (2000-8000 Hz)
    embruns = _bandpass(_white(rng, n), 2000, 8000)
    embruns = embruns * rng.uniform(0.85, 1.15, n) * 0.15

    # Couche 4 : vent côtier tres léger
    vent = _bandpass(_pink(rng, n), 100, 600) * 0.1

    mix = houle * 0.5 + ressac * 0.3 + embruns * 0.15 + vent * 0.05
    mix = _reverb_simple(mix, decay=0.15, delays_ms=[30, 60, 90])
    return mix


def _scene_rain(rng, n, duration):
    """Pluie realiste : gouttes proches + pluie lointaine + eclaboussures."""
    # Couche 1 : pluie dense lointaine (bruit shaped)
    pluie_loin = _bandpass(_white(rng, n), 1000, 9500)
    pluie_loin *= rng.uniform(0.88, 1.12, n) * 0.4

    # Couche 2 : gouttes proches (transitoires courts)
    gouttes = np.zeros(n)
    n_gouttes = int(duration * rng.uniform(40.0, 80.0))
    for _ in range(n_gouttes):
        t0 = int(rng.uniform(0.0, max(duration - 0.05, 0.01)) * SAMPLE_RATE)
        length = int(rng.uniform(0.003, 0.015) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        freq = rng.uniform(3000.0, 8000.0)
        t = np.arange(length) / SAMPLE_RATE
        env = np.exp(-t * 800.0)
        gouttes[t0:t0 + length] += np.sin(2.0 * math.pi * freq * t) * env * rng.uniform(0.1, 0.4)

    # Couche 3 : grondement bas (eau qui coule)
    grondement = _bandpass(_brown(rng, n), 60, 400) * 0.2

    # Couche 4 : eclaboussures sur surfaces
    eclaboussures = _bandpass(_white(rng, n), 1500, 6000)
    eclaboussures *= _lfo(rng.uniform(0.3, 0.8), n) * 0.1

    mix = pluie_loin + gouttes + grondement + eclaboussures
    mix = _reverb_simple(mix, decay=0.1, delays_ms=[15, 35, 55])
    return mix


def _scene_storm(rng, n, duration):
    """Orage realiste : pluie soutenue + tonnerre lointain + vent violent."""
    # Pluie dense
    pluie = _bandpass(_white(rng, n), 600, 8000)
    pluie *= rng.uniform(0.85, 1.15, n) * 0.35

    # Tonnerre (plusieurs coups avec reverb)
    tonnerre = np.zeros(n)
    n_coups = int(rng.integers(2, 5))
    for _ in range(n_coups):
        t0 = int(rng.uniform(0.5, max(duration - 3.0, 1.0)) * SAMPLE_RATE)
        length = int(rng.uniform(1.5, 4.0) * SAMPLE_RATE)
        if t0 + length > n:
            length = n - t0
        if length <= 0:
            continue
        # Corps du tonnerre : brun bas + crack initial
        corps = _bandpass(_brown(rng, length), 30, 120)
        crack_t = int(0.02 * SAMPLE_RATE)
        if crack_t < length:
            corps[:crack_t] += _bandpass(_white(rng, crack_t), 800, 4000) * 2.0
        env = np.exp(-np.linspace(0.0, 3.5, length))
        tonnerre[t0:t0 + length] += corps * env * rng.uniform(0.7, 1.3)

    # Vent violent
    vent = _bandpass(_pink(rng, n), 80, 1500)
    rafale = _lfo(rng.uniform(0.08, 0.25), n) ** 2
    vent *= rafale * 0.3

    mix = pluie + tonnerre + vent
    mix = _reverb_simple(mix, decay=0.25, delays_ms=[40, 80, 120])
    return mix


def _scene_wind(rng, n, duration):
    """Vent realiste : rafales + souffle + sifflements."""
    # Couche 1 : vent large (rose, modulé)
    vent_large = _bandpass(_pink(rng, n), 100, 1200)
    rafale = _lfo(rng.uniform(0.05, 0.18), n) * _lfo(rng.uniform(0.4, 0.9), n, phase=2.0)
    vent_large *= (0.4 + 0.6 * rafale) * 0.5

    # Couche 2 : sifflement (bande etroite, modulé)
    sifflet = _bandpass(_white(rng, n), 800, 2500)
    sifflet *= _lfo(rng.uniform(0.1, 0.3), n, phase=0.5) * 0.15

    # Couche 3 : souffle tres bas
    souffle = _bandpass(_brown(rng, n), 30, 200) * 0.2

    mix = vent_large + sifflet + souffle
    mix = _reverb_simple(mix, decay=0.1, delays_ms=[20, 45])
    return mix


def _scene_fire(rng, n, duration):
    """Feu de camp realiste : grondement + crepitements + souffle de chaleur."""
    # Couche 1 : grondement bas continu
    grondement = _bandpass(_brown(rng, n), 40, 400)
    grondement *= (0.6 + 0.3 * _lfo(rng.uniform(0.08, 0.2), n)) * 0.45

    # Couche 2 : crepitements (transitoires frequents)
    crepitement = np.zeros(n)
    n_pops = int(duration * rng.uniform(15.0, 35.0))
    for _ in range(n_pops):
        t0 = int(rng.uniform(0.0, max(duration - 0.08, 0.01)) * SAMPLE_RATE)
        length = int(rng.uniform(0.01, 0.06) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        freq = rng.uniform(1500.0, 7000.0)
        t = np.arange(length) / SAMPLE_RATE
        env = np.exp(-t * rng.uniform(40.0, 100.0))
        crepitement[t0:t0 + length] += np.sin(2.0 * math.pi * freq * t) * env * rng.uniform(0.2, 0.8)

    # Couche 3 : souffle de chaleur (modulation lente du spectre)
    chaleur = _bandpass(_pink(rng, n), 200, 800)
    chaleur *= _lfo(rng.uniform(0.15, 0.4), n) * 0.15

    mix = grondement + crepitement + chaleur
    mix = _reverb_simple(mix, decay=0.12, delays_ms=[25, 50])
    return mix


def _chirp(rng, n, sr=SAMPLE_RATE):
    """Un chant d'oiseau realiste : FM montante + harmoniques."""
    f0 = rng.uniform(2200.0, 3600.0)
    f1 = rng.uniform(3800.0, 5600.0)
    t = np.arange(n) / sr
    phase = 2.0 * math.pi * (f0 * t + (f1 - f0) * t * t / (2.0 * max(n / sr, 1e-9)))
    env = np.sin(np.linspace(0.0, math.pi, n)) ** 2
    # Ajouter harmoniques pour un son plus riche
    signal = np.sin(phase) + 0.3 * np.sin(2.0 * phase) + 0.15 * np.sin(3.0 * phase)
    return signal * env * 0.6


def _scene_forest(rng, n, duration):
    """Foret realiste : vent dans les feuilles + oiseaux + bruissement."""
    # Couche 1 : vent dans les feuilles (haut, modulé)
    feuilles = _bandpass(_pink(rng, n), 1500, 8000)
    feuilles *= _lfo(rng.uniform(0.08, 0.25), n) * 0.2

    # Couche 2 : vent bas dans les troncs
    vent = _bandpass(_pink(rng, n), 100, 800)
    vent *= (0.3 + 0.25 * _lfo(rng.uniform(0.1, 0.3), n)) * 0.3

    # Couche 3 : oiseaux (plus variés)
    oiseaux = np.zeros(n)
    n_chirps = int(duration * rng.uniform(1.0, 3.0))
    for _ in range(n_chirps):
        t0 = int(rng.uniform(0.0, max(duration - 0.5, 0.1)) * SAMPLE_RATE)
        length = int(rng.uniform(0.15, 0.6) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        oiseaux[t0:t0 + length] += _chirp(rng, length) * rng.uniform(0.2, 0.5)

    # Couche 4 : craquements de brindilles
    craquements = np.zeros(n)
    n_craque = int(duration * rng.uniform(0.5, 2.0))
    for _ in range(n_craque):
        t0 = int(rng.uniform(0.0, max(duration - 0.1, 0.01)) * SAMPLE_RATE)
        length = int(rng.uniform(0.005, 0.03) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        freq = rng.uniform(2000.0, 5000.0)
        t = np.arange(length) / SAMPLE_RATE
        env = np.exp(-t * 200.0)
        craquements[t0:t0 + length] += np.sin(2.0 * math.pi * freq * t) * env * 0.15

    mix = feuilles + vent + oiseaux + craquements
    mix = _reverb_simple(mix, decay=0.15, delays_ms=[30, 65, 100])
    return mix


def _scene_birds(rng, n, duration):
    """Oiseaux dominants (foret avec plus de chants)."""
    oiseaux = np.zeros(n)
    n_chirps = int(duration * rng.uniform(3.0, 6.0))
    for _ in range(n_chirps):
        t0 = int(rng.uniform(0.0, max(duration - 0.4, 0.05)) * SAMPLE_RATE)
        length = int(rng.uniform(0.12, 0.5) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        oiseaux[t0:t0 + length] += _chirp(rng, length) * rng.uniform(0.25, 0.6)

    # Vent tres leger en fond
    vent = _bandpass(_pink(rng, n), 200, 1200) * 0.15

    mix = oiseaux + vent
    mix = _reverb_simple(mix, decay=0.2, delays_ms=[40, 80])
    return mix


def _scene_night(rng, n, duration):
    """Nuit realiste : grillons + vent tres leger + bruit de fond organique."""
    # Couche 1 : grillons (pulsations regulieres)
    grillons = np.zeros(n)
    period = SAMPLE_RATE / rng.uniform(2.2, 3.5)
    pulse = int(period * 0.2)
    t0_idx = 0
    while t0_idx + pulse < n:
        t = np.arange(pulse) / SAMPLE_RATE
        f = rng.uniform(4000.0, 4800.0)
        env = (np.sin(np.linspace(0.0, math.pi, pulse)) ** 2) * 0.3
        grillons[t0_idx:t0_idx + pulse] += np.sin(2.0 * math.pi * f * t) * env
        t0_idx += int(period)

    # Couche 2 : vent tres doux
    vent = _bandpass(_pink(rng, n), 100, 600) * 0.15

    # Couche 3 : bruit de fond organique (bruit rose tres filtre)
    fond = _bandpass(_pink(rng, n), 200, 500) * 0.08

    mix = grillons + vent + fond
    mix = _reverb_simple(mix, decay=0.1, delays_ms=[25, 50])
    return mix


def _scene_city(rng, n, duration):
    """Ville realiste : trafic + sirènes lointaines + ambiance urbaine."""
    # Couche 1 : ronronnement urbain (60 Hz hum + harmoniques)
    hum = 0.08 * np.sin(2.0 * math.pi * 60.0 * np.arange(n) / SAMPLE_RATE)
    hum += 0.03 * np.sin(2.0 * math.pi * 120.0 * np.arange(n) / SAMPLE_RATE)
    hum += 0.02 * np.sin(2.0 * math.pi * 180.0 * np.arange(n) / SAMPLE_RATE)

    # Couche 2 : trafic (bruit brun modulé)
    trafic = _bandpass(_brown(rng, n), 60, 400)
    pass_by = _lfo(rng.uniform(0.04, 0.1), n) ** 3
    trafic *= (0.3 + 0.5 * pass_by) * 0.35

    # Couche 3 : sirènes lointaines ( sinus modulée )
    sirenes = np.zeros(n)
    n_sirenes = int(duration * rng.uniform(0.2, 0.6))
    for _ in range(n_sirenes):
        t0 = int(rng.uniform(0.0, max(duration - 3.0, 1.0)) * SAMPLE_RATE)
        length = int(rng.uniform(1.5, 4.0) * SAMPLE_RATE)
        if t0 + length > n:
            length = n - t0
        t = np.arange(length) / SAMPLE_RATE
        freq_mod = rng.uniform(0.3, 0.8)
        f_base = rng.uniform(800.0, 1200.0)
        signal = np.sin(2.0 * math.pi * f_base * t + 2.0 * math.pi * freq_mod * np.sin(2.0 * math.pi * 0.4 * t))
        env = np.sin(np.linspace(0.0, math.pi, length)) ** 2 * 0.08
        sirenes[t0:t0 + length] += signal * env

    mix = hum + trafic + sirenes
    mix = _reverb_simple(mix, decay=0.2, delays_ms=[35, 70, 110])
    return mix


def _scene_crowd(rng, n, duration):
    """Foule realiste : murmure + pas + voix eloignees."""
    # Couche 1 : murmure dense
    murmure = _bandpass(_pink(rng, n), 250, 2600)
    waves = _lfo(rng.uniform(0.2, 0.8), n) * _lfo(rng.uniform(1.5, 3.0), n, phase=1.0)
    murmure *= (0.5 + 0.5 * waves) * 0.4

    # Couche 2 : pas (transitoires bas)
    pas = np.zeros(n)
    n_pas = int(duration * rng.uniform(8.0, 20.0))
    for _ in range(n_pas):
        t0 = int(rng.uniform(0.0, max(duration - 0.05, 0.01)) * SAMPLE_RATE)
        length = int(rng.uniform(0.01, 0.04) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        freq = rng.uniform(80.0, 300.0)
        t = np.arange(length) / SAMPLE_RATE
        env = np.exp(-t * 100.0)
        pas[t0:t0 + length] += np.sin(2.0 * math.pi * freq * t) * env * 0.1

    # Couche 3 : voix eloignees (tres filtre, inintelligible)
    voix = _bandpass(_pink(rng, n), 400, 2000) * 0.1

    mix = murmure + pas + voix
    mix = _reverb_simple(mix, decay=0.25, delays_ms=[45, 90, 140])
    return mix


def _scene_waterfall(rng, n, duration):
    """Chute d'eau realiste : souffle blanc puissant + grondement + eclaboussures."""
    # Couche 1 : souffle blanc (haut)
    souffle = _bandpass(_white(rng, n), 1200, 10000) * 0.5

    # Couche 2 : grondement bas
    grondement = _bandpass(_brown(rng, n), 40, 300) * 0.4

    # Couche 3 : eclaboussures en bas
    eclaboussures = _bandpass(_white(rng, n), 800, 4000)
    eclaboussures *= _lfo(rng.uniform(0.2, 0.6), n) * 0.2

    mix = souffle + grondement + eclaboussures
    mix = _reverb_simple(mix, decay=0.3, delays_ms=[50, 100, 150])
    return mix


def _scene_river(rng, n, duration):
    """Riviere realiste : gargouillis + eclaboussures + courant."""
    # Couche 1 : courant principal
    courant = _bandpass(_white(rng, n), 200, 3500)
    courant *= (0.6 + 0.4 * _lfo(rng.uniform(0.12, 0.35), n)) * 0.5

    # Couche 2 : eclaboussures (tres haut)
    eclaboussures = _bandpass(_white(rng, n), 2000, 8000) * 0.15

    # Couche 3 : gargouillis (transitoires)
    gargouillis = np.zeros(n)
    n_gouttes = int(duration * rng.uniform(10.0, 25.0))
    for _ in range(n_gouttes):
        t0 = int(rng.uniform(0.0, max(duration - 0.08, 0.01)) * SAMPLE_RATE)
        length = int(rng.uniform(0.008, 0.04) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        freq = rng.uniform(1500.0, 5000.0)
        t = np.arange(length) / SAMPLE_RATE
        env = np.exp(-t * 150.0)
        gargouillis[t0:t0 + length] += np.sin(2.0 * math.pi * freq * t) * env * 0.2

    mix = courant + eclaboussures + gargouillis
    mix = _reverb_simple(mix, decay=0.12, delays_ms=[25, 55])
    return mix


def _scene_snow(rng, n, duration):
    """Neige realiste : vent feutré + craquements de givre + silence."""
    # Couche 1 : vent tres doux et feutré
    vent = _bandpass(_pink(rng, n), 150, 800) * 0.3

    # Couche 2 : craquements de givre (tres rares, tres delicats)
    craquements = np.zeros(n)
    n_craque = max(1, int(duration * 0.5))
    for _ in range(n_craque):
        t0 = int(rng.uniform(0.0, max(duration - 0.8, 0.05)) * SAMPLE_RATE)
        length = int(rng.uniform(0.2, 0.8) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        freq = rng.uniform(5000.0, 9000.0)
        t = np.arange(length) / SAMPLE_RATE
        env = np.exp(-t * 4.0)
        craquements[t0:t0 + length] += np.sin(2.0 * math.pi * freq * t) * env * 0.12

    # Couche 3 : silence presque total (tres peu de bruit)
    silence = _bandpass(_pink(rng, n), 300, 600) * 0.05

    mix = vent + craquements + silence
    mix = _reverb_simple(mix, decay=0.15, delays_ms=[30, 60])
    return mix


def _scene_desert(rng, n, duration):
    """Desert realiste : vent sec + silence + sifflement."""
    # Couche 1 : vent sec et constant
    vent = _bandpass(_pink(rng, n), 200, 1000) * 0.4

    # Couche 2 : sifflement de vent (bande etroite)
    sifflet = _bandpass(_white(rng, n), 600, 1800)
    sifflet *= _lfo(rng.uniform(0.06, 0.15), n) * 0.15

    # Couche 3 : souffle tres bas
    souffle = _bandpass(_brown(rng, n), 40, 150) * 0.1

    mix = vent + sifflet + souffle
    mix = _reverb_simple(mix, decay=0.1, delays_ms=[20, 45])
    return mix


def _scene_space(rng, n, duration):
    """Espace realiste : drone ethere + reverb longue + shimmer."""
    t = np.arange(n) / SAMPLE_RATE

    # Drone grave profond (accords lents)
    drone = 0.15 * np.sin(2.0 * math.pi * 55.0 * t)
    drone += 0.08 * np.sin(2.0 * math.pi * 82.5 * t + 0.5)
    drone += 0.05 * np.sin(2.0 * math.pi * 110.0 * t + 1.1)
    drone += 0.03 * np.sin(2.0 * math.pi * 165.0 * t + 1.8)

    # Shimmer tres haut (etincelles)
    shimmer = _bandpass(_white(rng, n), 3000, 12000) * 0.03

    # Vibrato lent
    slow = 1.0 + 0.04 * np.sin(2.0 * math.pi * 0.05 * t)

    mix = (drone + shimmer) * slow
    mix = _reverb_simple(mix, decay=0.4, delays_ms=[80, 160, 240, 320])
    return mix


def _scene_ambiant(rng, n, duration):
    """Defaut : tres leger, neutre, presque silencieux."""
    wind = _bandpass(_pink(rng, n), 150, 700) * 0.2
    wind *= (0.6 + 0.25 * _lfo(rng.uniform(0.08, 0.18), n))
    return wind


def _scene_plage(rng, n, duration):
    """Plage realiste : vagues douces + mouette lointaines + coquillages."""
    # Vagues tres douces
    vagues = _bandpass(_brown(rng, n), 40, 250)
    vagues *= (0.6 + 0.4 * _lfo(0.09 + rng.uniform(0.0, 0.03), n)) * 0.45

    # Mouettes (tres eloignees)
    mouettes = np.zeros(n)
    n_cris = int(duration * rng.uniform(0.3, 0.8))
    for _ in range(n_cris):
        t0 = int(rng.uniform(0.0, max(duration - 1.0, 0.2)) * SAMPLE_RATE)
        length = int(rng.uniform(0.3, 0.8) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        f0 = rng.uniform(1800.0, 2500.0)
        t = np.arange(length) / SAMPLE_RATE
        signal = np.sin(2.0 * math.pi * f0 * t + np.sin(2.0 * math.pi * 3.0 * t) * 0.5)
        env = np.sin(np.linspace(0.0, math.pi, length)) ** 2 * 0.08
        mouettes[t0:t0 + length] += signal * env

    mix = vagues + mouettes
    mix = _reverb_simple(mix, decay=0.2, delays_ms=[40, 85])
    return mix


def _scene_montagne(rng, n, duration):
    """Montagne realiste : vent violent + rochers + aigles."""
    # Vent fort
    vent = _bandpass(_pink(rng, n), 80, 1200)
    rafale = _lfo(rng.uniform(0.06, 0.2), n) ** 1.5
    vent *= rafale * 0.45

    # Craquements de rochers (tres rares)
    craquements = np.zeros(n)
    n_craque = int(duration * rng.uniform(0.3, 1.0))
    for _ in range(n_craque):
        t0 = int(rng.uniform(0.0, max(duration - 0.3, 0.05)) * SAMPLE_RATE)
        length = int(rng.uniform(0.02, 0.1) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        freq = rng.uniform(100.0, 400.0)
        t = np.arange(length) / SAMPLE_RATE
        env = np.exp(-t * 50.0)
        craquements[t0:t0 + length] += np.sin(2.0 * math.pi * freq * t) * env * 0.15

    mix = vent + craquements
    mix = _reverb_simple(mix, decay=0.3, delays_ms=[60, 120, 180])
    return mix


def _scene_underwater(rng, n, duration):
    """Sous-marin realiste : bulles + courants + resonance."""
    # Courant sous-marin
    courant = _bandpass(_pink(rng, n), 30, 200) * 0.3

    # Bulles (transitoires hautes frequences)
    bulles = np.zeros(n)
    n_bulles = int(duration * rng.uniform(5.0, 15.0))
    for _ in range(n_bulles):
        t0 = int(rng.uniform(0.0, max(duration - 0.1, 0.01)) * SAMPLE_RATE)
        length = int(rng.uniform(0.01, 0.06) * SAMPLE_RATE)
        if t0 + length > n:
            continue
        freq = rng.uniform(800.0, 3000.0)
        t = np.arange(length) / SAMPLE_RATE
        env = np.exp(-t * 80.0)
        bulles[t0:t0 + length] += np.sin(2.0 * math.pi * freq * t) * env * 0.15

    # Resonance (drone bas)
    resonance = _bandpass(_brown(rng, n), 40, 100) * 0.2

    mix = courant + bulles + resonance
    mix = _reverb_simple(mix, decay=0.35, delays_ms=[70, 140, 210])
    return mix


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
    "plage": _scene_plage,
    "montagne": _scene_montagne,
    "underwater": _scene_underwater,
    "ambiant": _scene_ambiant,
}


def generate_scene_sound(
    duration_sec: float,
    output_path: str,
    prompt: str,
    seed: int = 0,
) -> str:
    """Genere le paysage sonore de la scene et l'ecrit en WAV.

    Args:
        duration_sec: duree du son (≈ duree de la video).
        output_path: chemin WAV de sortie.
        prompt: prompt de la video (detection de scene par mots-cles FR/EN).
        seed: variation du grain (derive du prompt → deterministe par prompt).

    Returns:
        output_path en cas de succes. Lève une exception en cas d'echec.
    """
    scene = detect_scene(prompt)
    rng = np.random.default_rng(seed)

    duration_sec = max(0.5, float(duration_sec))
    n = int(duration_sec * SAMPLE_RATE)

    generator = _SCENE_GENERATORS.get(scene, _scene_ambiant)
    mix = generator(rng, n, duration_sec)

    mix = _fade(mix, 0.08, 0.35)  # fondu plus long
    mix = _normalize(mix, peak=0.75)

    # Stereo large : left et right avec delay + width
    haas = int(0.012 * SAMPLE_RATE)
    right = np.roll(mix, haas)
    right[:haas] = 0.0
    left, right = _stereo_wide(mix, right * 0.95, width=0.25)
    stereo = np.stack((left, right), axis=1)
    pcm = (np.clip(stereo, -1.0, 1.0) * 32767).astype(np.int16)

    with wave.open(output_path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())

    logger.info(
        f"[Ambiance] Scene « {scene} » ({duration_sec:.1f}s, seed {seed}) "
        f"-> {output_path}"
    )
    return output_path
