"""Tests pour l'auto-reprise après redéploiement (v8.14).

Vérifie que server._auto_resume_from_backup :
- relance les tâches simple/advanced marquées « Interrompu… » dont l'état
  Supabase contient des params (disque éphémère effacé → état reconstruit) ;
- ignore les tâches sans params (créées avant v8.14), avec backup Supabase,
  dont l'état local a survécu, trop anciennes (> 6 h) ou hors type simple ;
- plafonne à 2 relances par démarrage et incrémente resume_attempts.
"""
import asyncio
import json
import os
import time

import pytest

import server
from core.config import REGRESSION_WORKING_DIR_ENV


class _DummyPipeline:
    task_id = ""


class _FakeStore:
    def __init__(self, metas):
        self.metas = list(metas)
        self.upserted = []

    def list_meta(self):
        return list(self.metas)

    def upsert_meta(self, meta):
        self.upserted.append(dict(meta))


def _meta(task_id="task_a", dir_name="dir_a", status="failed",
          message="Interrompu: le serveur a redémarré (état restauré depuis la base)",
          backup_url="", attempts=0, updated_at=None, params=None,
          task_type="simple"):
    return {
        "task_id": task_id,
        "dir_name": dir_name,
        "task_type": task_type,
        "creative_name": "",
        "user_id": "",
        "status": status,
        "prompt": "Un chat qui joue dans un jardin ensoleillé",
        "current_message": message,
        "final_video_file": "",
        "video_backup_url": backup_url,
        "params": params if params is not None else {
            "duration": 15,
            "video_width": 832,
            "video_height": 1088,
            "seed": 42,
            "negative_prompt": "deformation",
            "system_prompt": "",
            "mode": "t2v",
            "audio_enabled": True,
            "audio_voice": "fr-FR-DeniseNeural",
            "audio_rate": "+0%",
            "quality_boost": False,
            "advanced_mode": False,
        },
        "resume_attempts": attempts,
        "created_at": time.time(),
        "updated_at": updated_at if updated_at is not None else time.time(),
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Mocks : stockage Supabase, lanceur de tâches, is_persistent_storage."""
    monkeypatch.setenv(REGRESSION_WORKING_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(server, "is_persistent_storage", lambda: True)
    monkeypatch.setattr(server, "get_api_key", lambda: "test-key")
    monkeypatch.setattr(server, "_create_pipeline_for_type",
                        lambda *a, **k: _DummyPipeline())
    recorded = []
    monkeypatch.setattr(server, "_launch_background_task",
                        lambda coro: (recorded.append(coro), coro.close()))
    monkeypatch.setattr(server, "active_pipelines", {})
    return tmp_path, recorded


def _run(store):
    return asyncio.run(server._auto_resume_from_backup()), store


def test_resume_backup_simple(env, monkeypatch):
    """Tâche simple interrompue avec params → relancée + attempts incrémenté."""
    tmp, recorded = env
    store = _FakeStore([_meta()])
    monkeypatch.setattr(server, "get_task_store", lambda: store)
    _run(store)
    assert len(recorded) == 1
    assert recorded[0].cr_code.co_name == "_run_pipeline_with_concurrency"
    # Le compteur est persisté AVANT le lancement (idempotence crash)
    assert store.upserted and store.upserted[0]["resume_attempts"] == 1
    assert store.upserted[0]["status"] == "queued"


def test_resume_backup_advanced(env, monkeypatch):
    """Tâche avancée interrompue → _run_advanced_pipeline lancé."""
    tmp, recorded = env
    params = _meta()["params"]
    params["advanced_mode"] = True
    store = _FakeStore([_meta(params=params)])
    monkeypatch.setattr(server, "get_task_store", lambda: store)
    _run(store)
    assert len(recorded) == 1
    assert recorded[0].cr_code.co_name == "_run_advanced_pipeline"


def test_resume_skips_without_params(env, monkeypatch):
    """Tâche créée avant v8.14 (params vides) → non relancée."""
    tmp, recorded = env
    store = _FakeStore([_meta(params={})])
    monkeypatch.setattr(server, "get_task_store", lambda: store)
    _run(store)
    assert recorded == []


def test_resume_skips_with_backup(env, monkeypatch):
    """Tâche avec video_backup_url → restaurée par le bloc v8.4, pas relancée."""
    tmp, recorded = env
    store = _FakeStore([_meta(backup_url="https://x/supabase/video.mp4")])
    monkeypatch.setattr(server, "get_task_store", lambda: store)
    _run(store)
    assert recorded == []


def test_resume_skips_local_state_survived(env, monkeypatch):
    """État local présent → géré par v8.3, pas par la reprise Supabase."""
    tmp, recorded = env
    task_dir = os.path.join(tmp, "dir_a")
    os.makedirs(task_dir, exist_ok=True)
    with open(os.path.join(task_dir, "task_state.json"), "w", encoding="utf-8") as f:
        json.dump({"status": "running"}, f)
    store = _FakeStore([_meta()])
    monkeypatch.setattr(server, "get_task_store", lambda: store)
    _run(store)
    assert recorded == []


def test_resume_skips_old_task(env, monkeypatch):
    """Tâche interrompue il y a plus de 6 h → ne pas ressusciter."""
    tmp, recorded = env
    store = _FakeStore([_meta(updated_at=time.time() - 8 * 3600)])
    monkeypatch.setattr(server, "get_task_store", lambda: store)
    _run(store)
    assert recorded == []


def test_resume_skips_user_stopped(env, monkeypatch):
    """Tâche stoppée volontairement (message différent) → non relancée."""
    tmp, recorded = env
    store = _FakeStore([_meta(message="Arrêté par l'utilisateur")])
    monkeypatch.setattr(server, "get_task_store", lambda: store)
    _run(store)
    assert recorded == []


def test_resume_skips_max_attempts(env, monkeypatch):
    """Budget épuisé (2 reprises déjà faites) → non relancée."""
    tmp, recorded = env
    store = _FakeStore([_meta(attempts=2)])
    monkeypatch.setattr(server, "get_task_store", lambda: store)
    _run(store)
    assert recorded == []


def test_resume_cap_two_per_boot(env, monkeypatch):
    """Maximum 2 relances par démarrage."""
    tmp, recorded = env
    metas = [_meta(task_id=f"task_{i}", dir_name=f"dir_{i}") for i in range(5)]
    store = _FakeStore(metas)
    monkeypatch.setattr(server, "get_task_store", lambda: store)
    _run(store)
    assert len(recorded) == 2


def test_resume_skips_non_simple(env, monkeypatch):
    """Les types autres que simple ne sont pas concernés."""
    tmp, recorded = env
    store = _FakeStore([_meta(task_type="creative")])
    monkeypatch.setattr(server, "get_task_store", lambda: store)
    _run(store)
    assert recorded == []
