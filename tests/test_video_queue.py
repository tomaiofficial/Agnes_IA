"""tests/test_video_queue.py — Tests de la file d'attente vidéo (VideoQueue).

Historique CI : le fichier test_video_queue.py d'origine (118 lignes) bloquait la
CI car le worker de la file restait actif après la fin du test, empêchant la
fermeture propre de l'event loop asyncio (voir commit 7611b02 qui l'a retiré
temporairement : « remove blocking queue tests temporarily »).

Ce fichier reprend la couverture avec une fixture asyncio qui garantit
l'arrêt du worker (await queue.stop()) dans le teardown, quel que soit le
résultat du test. Ainsi aucun worker ne survit à un test.
"""

import asyncio

import pytest

from core.video.queue import TaskPriority, VideoQueue


@pytest.fixture
async def queue():
    """File d'attente avec arrêt garanti du worker (anti-blocage CI)."""
    q = VideoQueue(max_concurrent=2)
    await q.start()
    yield q
    # Teardown : arrêter systématiquement le worker pour ne pas bloquer la loop.
    await q.stop()


async def _noop(delay: float = 0.0, value: str = "ok") -> str:
    """Tâche asynchrone minimale pour les tests."""
    if delay:
        await asyncio.sleep(delay)
    return value


# ══════════════════════════════════════════════════════════════════
# Priorités & ordre d'exécution
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_enqueue_and_wait(queue):
    """Enfile une tâche et attend son résultat."""
    task = await queue.enqueue("t1", TaskPriority.FREE, _noop, value="hello")
    assert task.status == "pending"
    result = await queue.wait("t1", timeout=10)
    assert result == "hello"
    assert queue.get_status("t1").status == "completed"


@pytest.mark.asyncio
async def test_priority_order(queue):
    """Les tâches prioritaires passent avant les tâches gratuites."""
    order: list[str] = []

    async def rec(label: str) -> str:
        order.append(label)
        return label

    await queue.enqueue("free1", TaskPriority.FREE, rec, "free1")
    await queue.enqueue("prem1", TaskPriority.PREMIUM, rec, "prem1")
    await queue.enqueue("admin1", TaskPriority.ADMIN, rec, "admin1")
    await queue.enqueue("free2", TaskPriority.FREE, rec, "free2")

    await queue.wait("free2", timeout=15)
    # La file traite une tâche à la fois (max_concurrent=1 n'est pas forcé ici,
    # mais avec des tâches sans délai l'ordre d'enfilement priorisé est respecté).
    assert order.index("admin1") < order.index("prem1")
    assert order.index("prem1") < order.index("free1")
    assert order.index("free1") < order.index("free2")


@pytest.mark.asyncio
async def test_concurrency_limited(queue):
    """max_concurrent limite le nombre de tâches en parallèle."""
    running = 0
    peak = 0

    async def tracked(delay: float) -> str:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(delay)
        running -= 1
        return "done"

    for i in range(5):
        await queue.enqueue(f"c{i}", TaskPriority.FREE, tracked, 0.1)

    await queue.wait("c4", timeout=20)
    assert peak <= 2  # max_concurrent=2
    assert queue.stats()["completed"] == 5


@pytest.mark.asyncio
async def test_queue_full_raises(queue):
    """Une file pleine lève RuntimeError."""
    q = VideoQueue(max_concurrent=1, max_queue_size=2)
    await q.start()
    try:
        await q.enqueue("q1", TaskPriority.FREE, _noop)
        await q.enqueue("q2", TaskPriority.FREE, _noop)
        with pytest.raises(RuntimeError, match="Queue full"):
            await q.enqueue("q3", TaskPriority.FREE, _noop)
    finally:
        await q.stop()


@pytest.mark.asyncio
async def test_cancel_pending(queue):
    """Annule une tâche en attente."""
    # Occupe le seul slot pendant 0.5s, pendant que t2 attend dans la file.
    q = VideoQueue(max_concurrent=1)
    await q.start()
    try:
        await q.enqueue("slow", TaskPriority.FREE, _noop, 0.5)
        await asyncio.sleep(0.05)
        await q.enqueue("doomed", TaskPriority.FREE, _noop)
        cancelled = await q.cancel("doomed")
        assert cancelled is True
        with pytest.raises(asyncio.CancelledError):
            await q.wait("doomed", timeout=5)
    finally:
        await q.stop()


@pytest.mark.asyncio
async def test_failure_propagates(queue):
    """Une tâche qui échoue lève son exception dans wait()."""

    async def boom() -> str:
        raise ValueError("boom")

    await queue.enqueue("bad", TaskPriority.FREE, boom)
    with pytest.raises(ValueError, match="boom"):
        await queue.wait("bad", timeout=10)
    assert queue.get_status("bad").status == "failed"


@pytest.mark.asyncio
async def test_wait_unknown_task_raises_keyerror(queue):
    """wait() sur une tâche inconnue lève KeyError."""
    with pytest.raises(KeyError):
        await queue.wait("nope", timeout=2)


@pytest.mark.asyncio
async def test_stats(queue):
    """Les statistiques reflètent l'état de la file."""
    stats = queue.stats()
    assert stats["max_concurrent"] == 2
    assert stats["queue_size"] == 0
    assert stats["running"] == 0
    assert stats["completed"] == 0


@pytest.mark.asyncio
async def test_worker_stops_cleanly(queue):
    """start()/stop() peuvent être appelés plusieurs fois sans erreur."""
    await queue.stop()  # déjà arrêté par teardown → ne doit pas lever
    await queue.start()  # redémarrage autorisé
    await queue.enqueue("again", TaskPriority.FREE, _noop, value="x")
    assert await queue.wait("again", timeout=10) == "x"
    await queue.stop()
