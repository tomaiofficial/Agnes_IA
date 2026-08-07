"""
tests/test_music.py — Musique de fond synthétisée des bots (v9.5)

Le modèle t2v génère des vidéos muettes ; les bots publient désormais avec
une nappe musicale (core/audio/music.py) à la place de la narration TTS.
"""

import os
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.audio.music import generate_background_music


class TestBackgroundMusic(unittest.TestCase):
    def test_generates_valid_wav(self):
        path = os.path.join(tempfile.mkdtemp(), "music.wav")
        generate_background_music(6.0, path, seed=7)
        self.assertTrue(os.path.exists(path))
        self.assertGreater(os.path.getsize(path), 50_000, "WAV trop petit")
        with wave.open(path) as w:
            dur = w.getnframes() / w.getframerate()
            self.assertAlmostEqual(dur, 6.0, delta=0.1)
            self.assertEqual(w.getnchannels(), 2)
            self.assertEqual(w.getsampwidth(), 2)

    def test_seed_variation(self):
        d = tempfile.mkdtemp()
        a = os.path.join(d, "a.wav")
        b = os.path.join(d, "b.wav")
        generate_background_music(4.0, a, seed=1)
        generate_background_music(4.0, b, seed=2)
        with open(a, "rb") as fa, open(b, "rb") as fb:
            self.assertNotEqual(fa.read(), fb.read(), "deux seeds doivent produire des musiques différentes")

    def test_many_seeds_are_distinct(self):
        # v9.6: l'utilisateur entendait « toujours le même son » → la variété
        # doit être RÉELLE : sur 20 seeds, la grande majorité doit produire
        # des musiques distinctes (au moins 15/20 uniques).
        d = tempfile.mkdtemp()
        hashes = set()
        for s in range(20):
            p = os.path.join(d, f"m{s}.wav")
            generate_background_music(4.0, p, seed=s)
            with open(p, "rb") as f:
                hashes.add(hash(f.read()))
        self.assertGreaterEqual(
            len(hashes), 15,
            f"trop peu de musiques distinctes: {len(hashes)}/20 (seed → même son)",
        )

    def test_short_duration_no_crash(self):
        path = os.path.join(tempfile.mkdtemp(), "short.wav")
        generate_background_music(0.8, path, seed=0)  # moins d'une mesure
        with wave.open(path) as w:
            dur = w.getnframes() / w.getframerate()
            self.assertAlmostEqual(dur, 0.8, delta=0.1)


if __name__ == "__main__":
    unittest.main()
