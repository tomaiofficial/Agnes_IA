"""Tests du moteur de créateurs IA autonomes (personas + scheduler)."""

import sys
import unittest
from datetime import datetime

sys.path.insert(0, ".")

from core.agents import AGENT_PERSONAS, AgentScheduler, get_persona  # noqa: E402


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
