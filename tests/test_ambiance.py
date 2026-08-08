"""
tests/test_ambiance.py — Paysage sonore de scène des bots (v9.8)

L'utilisateur veut le « son réel » de la vidéo (comme Sora 2) et plus la
musique de fond. Le modèle t2v génère des vidéos muettes ; on synthétise donc
un paysage sonore procédural cohérent avec le prompt (core/audio/ambiance.py).
"""

import os
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.audio.ambiance import detect_scene, generate_scene_sound


class TestSceneDetection(unittest.TestCase):
    def test_detect_scene_keywords(self):
        cases = {
            "Une plage au coucher du soleil avec des vagues douces": "mer",
            "Il pleut fort sur la ville": "pluie",  # pluie prioritaire sur la ville
            "Il pleut fort dans la rue": "pluie",
            "Orage violent avec des éclairs": "orage",
            "Une forêt dense avec de grands arbres": "foret",
            "Des oiseaux chantent dans les arbres": "foret",  # foret avant oiseaux
            "Les rues animées de la ville la nuit": "ville",
            "Une foule dans un marché bondé": "foule",
            "Chute d'eau spectaculaire en montagne": "chute_eau",
            "Une rivière qui coule entre les rochers": "riviere",
            "Feu de camp dans le désert": "feu",  # feu avant desert
            "Un désert aride avec des dunes": "desert",
            "La neige tombe en hiver": "neige",
            "Voyage dans la galaxie": "espace",
            "Le vent souffle dans la plaine": "vent",
            "Un chat qui dort sur un canapé": "ambiant",
        }
        for prompt, expected in cases.items():
            self.assertEqual(
                detect_scene(prompt), expected,
                f"prompt: {prompt!r}",
            )

    def test_detect_scene_case_insensitive(self):
        self.assertEqual(detect_scene("STORM AT SEA"), "orage")
        self.assertEqual(detect_scene("CITY STREET"), "ville")

    def test_detect_scene_empty(self):
        self.assertEqual(detect_scene(""), "ambiant")
        self.assertEqual(detect_scene(None), "ambiant")


class TestSceneSound(unittest.TestCase):
    def test_generates_valid_wav(self):
        path = os.path.join(tempfile.mkdtemp(), "ambiance.wav")
        generate_scene_sound(6.0, path, prompt="Une plage avec des vagues", seed=7)
        self.assertTrue(os.path.exists(path))
        self.assertGreater(os.path.getsize(path), 50_000, "WAV trop petit")
        with wave.open(path) as w:
            dur = w.getnframes() / w.getframerate()
            self.assertAlmostEqual(dur, 6.0, delta=0.1)
            self.assertEqual(w.getnchannels(), 2)
            self.assertEqual(w.getsampwidth(), 2)

    def test_not_silent(self):
        # Le paysage sonore doit être audible (RMS significatif), pas un quasi-silence.
        d = tempfile.mkdtemp()
        for prompt in ("La pluie tombe", "Une forêt calme", "La ville la nuit"):
            p = os.path.join(d, "x.wav")
            generate_scene_sound(3.0, p, prompt=prompt, seed=3)
            with wave.open(p) as w:
                frames = w.readframes(w.getnframes())
            samples = __import__("array").array("h", frames)
            import numpy as np
            rms = float(np.sqrt(np.mean(np.asarray(samples, dtype=np.float64) ** 2)))
            self.assertGreater(rms, 300.0, f"ambiance quasi silencieuse pour {prompt!r} (rms={rms:.0f})")

    def test_seed_variation_same_scene(self):
        d = tempfile.mkdtemp()
        a = os.path.join(d, "a.wav")
        b = os.path.join(d, "b.wav")
        generate_scene_sound(4.0, a, prompt="La mer agitée", seed=1)
        generate_scene_sound(4.0, b, prompt="La mer agitée", seed=2)
        with open(a, "rb") as fa, open(b, "rb") as fb:
            self.assertNotEqual(fa.read(), fb.read(), "deux seeds doivent produire des ambiances différentes")

    def test_different_scenes_are_distinct(self):
        d = tempfile.mkdtemp()
        a = os.path.join(d, "a.wav")
        b = os.path.join(d, "b.wav")
        generate_scene_sound(4.0, a, prompt="Une plage avec des vagues", seed=5)
        generate_scene_sound(4.0, b, prompt="Une forêt avec des oiseaux", seed=5)
        with open(a, "rb") as fa, open(b, "rb") as fb:
            self.assertNotEqual(fa.read(), fb.read(), "deux scènes doivent produire des sons différents")

    def test_short_duration_no_crash(self):
        path = os.path.join(tempfile.mkdtemp(), "short.wav")
        generate_scene_sound(0.8, path, prompt="Un orage violent", seed=0)
        with wave.open(path) as w:
            dur = w.getnframes() / w.getframerate()
            self.assertAlmostEqual(dur, 0.8, delta=0.1)


if __name__ == "__main__":
    unittest.main()
