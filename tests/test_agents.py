"""Tests du moteur de créateurs IA autonomes (personas + scheduler + social)."""

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, ".")

from core.agents import AGENT_PERSONAS, AgentScheduler, AgentSocial, get_persona  # noqa: E402
from core.agents.personas import VIDEO_GENRES, pick_editorial  # noqa: E402


class TestPersonas(unittest.TestCase):
    def test_personas_count_and_fields(self):
        self.assertGreaterEqual(len(AGENT_PERSONAS), 8)
        seen_ids = set()
        for p in AGENT_PERSONAS:
            self.assertNotIn(p.id, seen_ids, f"ID dupliqué: {p.id}")
            seen_ids.add(p.id)
            self.assertTrue(p.author.strip(), f"{p.id}: author vide")
            self.assertTrue(p.user_id.startswith("agent:"), f"{p.id}: user_id invalide {p.user_id}")
            self.assertTrue(p.voice.startswith("fr-FR"), f"{p.id}: voix non française {p.voice}")
            self.assertTrue(p.schedule, f"{p.id}: planning vide")
            self.assertEqual(p.duration, 15)

    def test_get_persona(self):
        self.assertEqual(get_persona("lea-martin").author, "Léa Martin")
        self.assertIsNone(get_persona("inconnu"))

    def test_all_schedules_use_0_23(self):
        for p in AGENT_PERSONAS:
            for h in p.schedule:
                self.assertGreaterEqual(h, 0)
                self.assertLessEqual(h, 23)


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.sched = AgentScheduler(api_key_provider=lambda: "test-key")

    def test_slot_key_deterministic(self):
        now = datetime(2026, 8, 1, 14, 30)
        self.assertEqual(AgentScheduler._slot_key(now), "2026-08-01_14")

    def test_task_id_for(self):
        now = datetime(2026, 8, 1, 14, 30)
        p = get_persona("lea-martin")
        self.assertEqual(
            self.sched._task_id_for(p, now),
            "agent_lea-martin_2026-08-01_14",
        )

    def test_status_shape(self):
        st = self.sched.status()
        self.assertTrue(st["ok"])
        self.assertEqual(len(st["agents"]), len(AGENT_PERSONAS))
        first = st["agents"][0]
        for key in ("id", "author", "theme", "schedule", "enabled", "next_hour"):
            self.assertIn(key, first)

    def test_toggle_unknown(self):
        self.assertFalse(self.sched.set_enabled("inconnu", True))

    def test_attempted_initialized(self):
        # v9.3: regression — self._attempted était utilisé sans être initialisé
        self.assertIsInstance(self.sched._attempted, set)


class TestSocial(unittest.TestCase):
    """v9.3: vie sociale des bots (likes + abonnements) sur le store local."""

    def setUp(self):
        import tempfile
        import shutil
        from core.agents.social import activity_probability
        from core.storage import local_backend as lb
        from core.storage.local_backend import LocalCommunityStore

        self._shutil = shutil
        self._tmp = tempfile.mkdtemp(prefix="agents_social_")
        self._orig_wd = lb.get_working_dir
        lb.get_working_dir = lambda: self._tmp
        self.store = LocalCommunityStore()
        self.social = AgentSocial(store_provider=lambda: self.store)
        self._orig_prob = activity_probability
        # Déterministe : tous les bots agissent, quelle que soit l'heure du test
        import core.agents.social as social_mod
        social_mod.activity_probability = lambda h: 1.0
        self._fake = os.path.join(self._tmp, "fake.mp4")
        with open(self._fake, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42" + b"fake-video-bytes")

    def tearDown(self):
        import core.agents.social as social_mod
        from core.storage import local_backend as lb
        lb.get_working_dir = self._orig_wd
        social_mod.activity_probability = self._orig_prob
        self._shutil.rmtree(self._tmp, ignore_errors=True)

    def _publish(self, task_id, author, user_id, i):
        return self.store.publish(
            task_id=task_id, author=author, prompt=f"Vidéo test {i}",
            duration=5.0, resolution="1024x576", video_path=self._fake, user_id=user_id,
        )

    def test_is_liked_local_backend(self):
        v = self._publish("t1", "A", "u1", 0)["video_id"]
        self.assertFalse(self.store.is_liked(v, "agent:lea-martin"))
        self.store.toggle_like(v, "agent:lea-martin")
        self.assertTrue(self.store.is_liked(v, "agent:lea-martin"))
        # is_liked est en lecture seule : il ne bascule pas le like
        self.assertTrue(self.store.is_liked(v, "agent:lea-martin"))

    def test_social_likes_and_follows(self):
        vids = [self._publish(f"h{i}", f"Humain {i}", f"u{i}", i)["video_id"] for i in range(3)]
        bot_vid = self._publish("b1", "Léa Martin", "agent:lea-martin", 9)["video_id"]
        stats = self.social.run_tick()
        self.assertGreater(stats["likes"], 0)
        self.assertGreater(stats["follows"], 0)
        # Les vidéos humaines ont été likées par au moins un bot
        any_liked = any(
            self.store.is_liked(v, p.user_id)
            for v in vids
            for p in AGENT_PERSONAS
        )
        self.assertTrue(any_liked)
        # Un bot ne like jamais sa propre vidéo
        self.assertFalse(self.store.is_liked(bot_vid, "agent:lea-martin"))
        # Idempotence : un second tick n'inverse aucun like (pas d'unlike)
        likes_before = sum(len(self.store.get_meta(v)["likes"]) for v in vids)
        self.social.run_tick()
        likes_after = sum(len(self.store.get_meta(v)["likes"]) for v in vids)
        self.assertGreaterEqual(likes_after, likes_before)
        # Abonnements : chaque bot a suivi au moins un créateur (bot ou humain)
        self.assertGreaterEqual(self.store.get_following_count("agent:lea-martin"), 1)


class TestGenres(unittest.TestCase):
    """v10.0: variété des bots — genres de mini-films (comédie, horreur, action…)."""

    def test_genres_count_and_fields(self):
        self.assertGreaterEqual(len(VIDEO_GENRES), 10)
        seen_ids = set()
        for g in VIDEO_GENRES:
            self.assertNotIn(g.id, seen_ids, f"Genre dupliqué: {g.id}")
            seen_ids.add(g.id)
            self.assertTrue(g.name.strip(), f"{g.id}: name vide")
            self.assertTrue(g.instruction.strip(), f"{g.id}: instruction vide")
            self.assertGreaterEqual(len(g.prompts), 4, f"{g.id}: trop peu de prompts")

    def test_genres_include_fun_and_horror(self):
        names = {g.id for g in VIDEO_GENRES}
        self.assertIn("comedie", names)
        self.assertIn("horreur", names)

    def test_pick_editorial_shape(self):
        # L'éditorial tiré pour une publication est toujours exploitable
        # par le runner (label + instruction + prompts non vides).
        for persona in AGENT_PERSONAS:
            for _ in range(20):
                ed = pick_editorial(persona)
                self.assertTrue(ed.label.strip())
                self.assertTrue(ed.instruction.strip())
                self.assertGreaterEqual(len(ed.prompts), 1)

    def test_pick_editorial_varies(self):
        # Sur 200 tirages pour un même bot, on doit voir plusieurs genres
        # différents (et pas uniquement son thème unique) : c'est le cœur
        # du correctif « les bots refont toujours le même type ».
        persona = get_persona("lea-martin")
        labels = {pick_editorial(persona).label for _ in range(200)}
        self.assertGreaterEqual(len(labels), 5, f"Trop peu de variété: {labels}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
