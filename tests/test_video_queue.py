"""Tests pour core/video/queue.py"""
import asyncio
import pytest
from core.video.queue import VideoQueue, TaskPriority, QueuedTask


@pytest.fixture
def queue():
    """Crée une file d'attente pour les tests."""
    return VideoQueue(max_concurrent=2, max_queue_size=10)


def test_task_priority_values():
    """Vérifie les valeurs de priorité (plus basse = plus prioritaire)."""
    assert TaskPriority.ADMIN.value < TaskPriority.PREMIUM.value
    assert TaskPriority.PREMIUM.value < TaskPriority.FREE.value


def test_queue_stats(queue):
    """Vérifie les statistiques initiales."""
    stats = queue.stats()
    assert stats["queue_size"] == 0
    assert stats["running"] == 0
    assert stats["completed"] == 0
    assert stats["max_concurrent"] == 2


async def test_queue_enqueue_dequeue(queue):
    """Test basique d'enqueue/dequeue."""
    await queue.start()

    result = []
    async def task_fn():
        result.append("done")
        return "result"

    task = await queue.enqueue("task1", TaskPriority.FREE, task_fn)
    assert task.status == "pending"

    # Attendre la completion
    res = await queue.wait("task1", timeout=5)
    assert res == "result"
    assert result == ["done"]

    await queue.stop()


async def test_queue_priority_order(queue):
    """Vérifie que les tâches sont exécutées par priorité."""
    await queue.start()

    results = []
    async def task_fn(name):
        results.append(name)
        return name

    # Ajouter des tâches dans un ordre quelconque
    await queue.enqueue("low1", TaskPriority.FREE, task_fn, "low1")
    await queue.enqueue("high1", TaskPriority.ADMIN, task_fn, "high1")
    await queue.enqueue("med1", TaskPriority.PREMIUM, task_fn, "med1")

    # Attendre toutes
    await asyncio.sleep(0.5)

    # La tâche admin devrait être exécutée en premier
    assert results[0] == "high1"

    await queue.stop()


async def test_queue_cancel(queue):
    """Test d'annulation d'une tâche en attente."""
    await queue.start()

    # Utiliser un événement pour bloquer l'exécution
    block_event = asyncio.Event()
    async def blocking_task():
        await block_event.wait()
        return "done"

    # Ajouter plusieurs tâches pour remplir la file
    await queue.enqueue("task1", TaskPriority.FREE, blocking_task)
    await queue.enqueue("task2", TaskPriority.FREE, blocking_task)
    await queue.enqueue("task3", TaskPriority.FREE, blocking_task)

    # Laisser le worker commencer task1 (qui est bloqué)
    await asyncio.sleep(0.2)

    # task2 et task3 sont en file — annuler task2
    cancelled = await queue.cancel("task2")
    assert cancelled is True

    # Libérer le blocage
    block_event.set()
    await asyncio.sleep(0.5)

    await queue.stop()


async def test_queue_full(queue):
    """Vérifie qu'une file pleine lève une erreur."""
    await queue.start()

    async def quick_task():
        return "done"

    # Remplir la file
    for i in range(10):
        await queue.enqueue(f"task{i}", TaskPriority.FREE, quick_task)

    # La 11e devrait échouer
    with pytest.raises(RuntimeError, match="Queue full"):
        await queue.enqueue("overflow", TaskPriority.FREE, quick_task)

    await queue.stop()


async def test_queue_get_status(queue):
    """Vérifie la récupération du statut d'une tâche."""
    await queue.start()

    async def task_fn():
        return "done"

    await queue.enqueue("task1", TaskPriority.FREE, task_fn)
    status = queue.get_status("task1")
    assert status is not None
    assert status.task_id == "task1"

    await queue.wait("task1", timeout=5)
    status = queue.get_status("task1")
    assert status.status == "completed"

    await queue.stop()
