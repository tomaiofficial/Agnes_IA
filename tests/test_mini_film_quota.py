"""Tests du quota quotidien de mini-films (v10.2).

VÃ©rifie que server._mini_film_count_today :
- ne compte que les tÃ¢ches creative du mÃªme user_id ;
- ne compte que celles crÃ©Ã©es aujourd'hui (rolling day UTC) ;
- ignore les autres types de tÃ¢ches et les autres visiteurs.

Et que POST /api/tasks/creative refuse (429) une fois le quota atteint.
"""
import time

import pytest
from fastapi.testclient import TestClient

import server
from models.task import TaskType


class _FakeStore:
    def __init__(self, metas):
        self.metas = list(metas)

    def list_meta(self):
        return list(self.metas)

    def upsert_meta(self, meta):
        # Simule la persistance : la tÃ¢che fraÃ®chement crÃ©Ã©e apparaÃ®t ensuite
        # dans list_meta() (comportement du backend Supabase en production).
        for i, m in enumerate(self.metas):
            if m.get("task_id") == meta.get("task_id"):
                self.metas[i] = dict(meta)
                return
        self.metas.append(dict(meta))


def _meta(task_id="mf_001", user_id="visitor-a", task_type="creative",
          created_at=None):
    return {
        "task_id": task_id,
        "dir_name": f"20260811_120000_{task_id}",
        "task_type": task_type,
        "creative_name": "",
        "user_id": user_id,
        "status": "completed",
        "prompt": "Un robot jardinier dans une serre gÃ©ante",
        "current_message": "",
        "final_video_file": "",
        "video_backup_url": "",
        "params": {},
        "resume_attempts": 0,
        "created_at": created_at if created_at is not None else time.time(),
        "updated_at": time.time(),
    }


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "get_api_key", lambda: "test-key")
    monkeypatch.setattr(server, "MINI_FILM_DAILY_LIMIT", 3)
    # Isole le working dir des tÃ¢ches crÃ©Ã©es par la route (pas de fuite disque)
    from core.config import REGRESSION_WORKING_DIR_ENV
    monkeypatch.setenv(REGRESSION_WORKING_DIR_ENV, str(tmp_path))
    return monkeypatch


def _patch_store(monkeypatch, store):
    """Le store est lu par server (quota) ET par core.storage (TaskManager)."""
    monkeypatch.setattr(server, "get_task_store", lambda: store)
    import core.storage
    monkeypatch.setattr(core.storage, "get_task_store", lambda: store)


def test_count_ignores_other_users_and_types(env):
    store = _FakeStore([
        _meta("a", user_id="visitor-a", task_type="creative"),
        _meta("b", user_id="visitor-b", task_type="creative"),
        _meta("c", user_id="visitor-a", task_type="simple"),
        _meta("d", user_id="", task_type="creative"),
    ])
    _patch_store(env, store)
    assert server._mini_film_count_today("visitor-a") == 1


def test_count_ignores_old_tasks(env):
    yesterday = int(time.time() // 86400) * 86400 - 3600
    store = _FakeStore([
        _meta("old", user_id="visitor-a", created_at=yesterday),
        _meta("now", user_id="visitor-a"),
    ])
    _patch_store(env, store)
    assert server._mini_film_count_today("visitor-a") == 1


def test_count_no_user_id_is_unlimited(env):
    assert server._mini_film_count_today("") == 0


def test_quota_endpoint_reports_remaining(env):
    store = _FakeStore([_meta("a", user_id="visitor-a")])
    _patch_store(env, store)
    client = TestClient(server.app)
    r = client.get("/api/community/mini-films/quota",
                   headers={"X-User-Id": "visitor-a"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["used"] == 1
    assert data["limit"] == 3
    assert data["remaining"] == 2


def test_creative_task_rejected_when_quota_reached(env, monkeypatch):
    # 3 mini-films dÃ©jÃ  crÃ©Ã©s aujourd'hui â†’ 4e refusÃ© en 429
    store = _FakeStore([
        _meta("a", user_id="visitor-a"),
        _meta("b", user_id="visitor-a"),
        _meta("c", user_id="visitor-a"),
    ])
    _patch_store(env, store)
    launched = []
    monkeypatch.setattr(server, "_create_pipeline_for_type",
                        lambda *a, **k: object())
    monkeypatch.setattr(server, "active_pipelines", {})
    monkeypatch.setattr(server, "_launch_background_task",
                        lambda coro: (launched.append(coro), coro.close()))

    client = TestClient(server.app)
    r = client.post("/api/tasks/creative",
                    data={"idea": "Un voyage en montgolfiÃ¨re au coucher du soleil"},
                    headers={"X-User-Id": "visitor-a"})
    assert r.status_code == 429
    assert "Limite" in r.json()["detail"]
    assert launched == []


def test_creative_task_accepted_under_quota(env, monkeypatch):
    store = _FakeStore([_meta("a", user_id="visitor-a")])
    _patch_store(env, store)
    launched = []
    monkeypatch.setattr(server, "_create_pipeline_for_type",
                        lambda *a, **k: object())
    monkeypatch.setattr(server, "active_pipelines", {})
    monkeypatch.setattr(server, "_launch_background_task",
                        lambda coro: (launched.append(coro), coro.close()))

    client = TestClient(server.app)
    r = client.post("/api/tasks/creative",
                    data={"idea": "Un voyage en montgolfiÃ¨re au coucher du soleil"},
                    headers={"X-User-Id": "visitor-a"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(launched) == 1
    # La tÃ¢che crÃ©Ã©e doit compter dÃ¨s maintenant (retour du compteur â‰¥ 2)
    assert server._mini_film_count_today("visitor-a") == 2

