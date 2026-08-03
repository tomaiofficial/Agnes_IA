"""Tests pour l'auto-reprise des tâches interrompues au démarrage (v8.3).

Vérifie que server._auto_resume_interrupted :
- relance les tâches running/queued dont l'état local a survécu au redémarrage ;
- ignore les tâches completed ou dont l'état est introuvable ;
- ne fait rien avec une liste vide.
"""
import asyncio
import json
import os

import pytest

import server
from core.config import REGRESSION_WORKING_DIR_ENV


class _DummyPipeline:
    task_id = ""


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Working dir temporaire (via la variable d'env officielle) + mocks."""
    monkeypatch.setenv(REGRESSION_WORKING_DIR_ENV, str(tmp_path))
    recorded = []
    monkeypatch.setattr(server, "_create_pipeline_for_type",
                        lambda *a, **k: _DummyPipeline())
    monkeypatch.setattr(server, "_launch_background_task",
                        lambda coro: (recorded.append(coro), coro.close()))
    monkeypatch.setattr(server, "active_pipelines", {})
    monkeypatch.setattr(server, "_pipeline_locks", {})
    return tmp_path, recorded


def _write_task(working_dir, task_id, dir_name, status="running", video_id=""):
    task_dir = os.path.join(working_dir, dir_name)
    os.makedirs(task_dir, exist_ok=True)
    data = {
        "task_id": task_id,
        "dir_name": dir_name,
        "task_type": "simple",
        "status": status,
        "prompt": "un test",
        "video_id": video_id,
    }
    with open(os.path.join(task_dir, "task_state.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def test_auto_resume_empty(env):
    """Liste vide → aucun effet."""
    tmp, recorded = env
    asyncio.run(server._auto_resume_interrupted([]))
    assert recorded == []
    assert server.active_pipelines == {}


def test_auto_resume_running_task(env):
    """Tâche running avec état local → pipeline relancé + enregistré."""
    tmp, recorded = env
    _write_task(tmp, "task_a", "dir_a", status="running", video_id="vid_123")
    asyncio.run(server._auto_resume_interrupted([("task_a", "dir_a")]))
    assert "task_a" in server.active_pipelines
    assert len(recorded) == 1


def test_auto_resume_skips_completed(env):
    """Tâche déjà completed → non relancée."""
    tmp, recorded = env
    _write_task(tmp, "task_b", "dir_b", status="completed")
    asyncio.run(server._auto_resume_interrupted([("task_b", "dir_b")]))
    assert server.active_pipelines == {}
    assert recorded == []


def test_auto_resume_skips_missing_state(env):
    """Tâche dont task_state.json n'existe pas (redéploiement) → ignorée."""
    tmp, recorded = env
    asyncio.run(server._auto_resume_interrupted([("ghost", "ghost_dir")]))
    assert server.active_pipelines == {}
    assert recorded == []


def test_auto_resume_respects_cap(env):
    """La reprise est plafonnée (max 3) pour ne pas saturer le plan Free."""
    tmp, recorded = env
    for i in range(6):
        _write_task(tmp, f"task_{i}", f"dir_{i}", status="running", video_id=f"vid_{i}")
    tasks = [(f"task_{i}", f"dir_{i}") for i in range(6)]
    asyncio.run(server._auto_resume_interrupted(tasks))
    assert len(recorded) == 3
    assert len(server.active_pipelines) == 3
