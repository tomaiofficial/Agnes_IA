"""
core/agents/scheduler.py — Planificateur horaire des créateurs IA

Boucle asyncio qui vérifie chaque minute si un persona doit publier,
selon son planning (heures locales ou fuseau AGENTS_TZ), puis lance la
génération en arrière-plan.

Anti-doublon robuste : le task_id de publication est DÉTERMINISTE par
créneau (`agent_{persona}_{YYYY-MM-DD}_{HH}`). Avant chaque publication,
on interroge la galerie via `find_published(task_id)` : si le créneau est
déjà publié (même après redéploiement), on saute.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Callable, Optional, Set

from core.agents.agent_runner import generate_and_publish
from core.agents.personas import AGENT_PERSONAS, AgentPersona
from core.config import get_working_dir
from core.storage import get_community_store, get_task_store
from core.video import VideoMonitor, VideoQueue

logger = logging.getLogger(__name__)

_STATE_FILE = "agents_state.json"
_STATE_KEY = "__agents_state__"


class AgentScheduler:
    """Planificateur autonome des créateurs IA."""

    def __init__(
        self,
        api_key_provider: Callable[[], str],
        queue: Optional[VideoQueue] = None,
        monitor: Optional[VideoMonitor] = None,
        tz: Optional[str] = None,
    ):
        self._api_key_provider = api_key_provider
        self._queue = queue
        self._monitor = monitor
        self._tz = tz
        self._loop_task: Optional[asyncio.Task] = None
        self._background: Set[asyncio.Task] = set()
        self._semaphore = asyncio.Semaphore(1)  # un seul bot à la fois (rate limit 16/min)
        self._last_launch_at: float = 0.0
        self._attempted: set = set()  # créneaux déjà tentés cette heure (anti-boucle en cas d'échec)
        self._current_hour: Optional[str] = None
        # État local : {persona_id: {"enabled": bool}}
        self._state: dict = {}
        self._load_state()

    # ── Heure courante (fuseau AGENTS_TZ ou locale) ──────────────────
    def _now(self) -> datetime:
        if self._tz:
            try:
                from zoneinfo import ZoneInfo
                return datetime.now(ZoneInfo(self._tz)).replace(tzinfo=None)
            except Exception:
                pass
        return datetime.now()

    # ── État activé/désactivé ────────────────────────────────────────
    def _state_path(self) -> str:
        return os.path.join(get_working_dir(), _STATE_FILE)

    def _load_state(self) -> None:
        try:
            path = self._state_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    self._state = json.load(f)
                logger.info(f"[Agents] État chargé depuis {path}")
        except Exception as e:
            logger.warning(f"[Agents] État local illisible: {e}")

    def _save_state(self) -> None:
        try:
            path = self._state_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            logger.warning(f"[Agents] Sauvegarde état impossible: {e}")

    def set_enabled(self, agent_id: str, enabled: bool) -> bool:
        persona = next((p for p in AGENT_PERSONAS if p.id == agent_id), None)
        if not persona:
            return False
        self._state.setdefault(agent_id, {})["enabled"] = bool(enabled)
        self._save_state()
        logger.info(f"[Agents] {persona.author} {'activé' if enabled else 'désactivé'}")
        return True

    def is_enabled(self, persona: AgentPersona) -> bool:
        return bool(self._state.get(persona.id, {}).get("enabled", True))

    # ── Slot / anti-doublon ──────────────────────────────────────────
    @staticmethod
    def _slot_key(now: datetime) -> str:
        return f"{now:%Y-%m-%d}_{now.hour:02d}"

    def _task_id_for(self, persona: AgentPersona, now: datetime) -> str:
        return f"agent_{persona.id}_{self._slot_key(now)}"

    def _slot_published(self, persona: AgentPersona, now: datetime) -> bool:
        try:
            task_id = self._task_id_for(persona, now)
            return get_community_store().find_published(task_id) is not None
        except Exception as e:
            logger.warning(f"[Agents] Vérification galerie impossible: {e}")
            return False

    # ── Boucle principale ────────────────────────────────────────────
    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._loop_task = asyncio.create_task(self._run_loop(), name="agents-scheduler")
        logger.info("[Agents] Scheduler démarré (%d personas)", len(AGENT_PERSONAS))

    async def stop(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        if self._background:
            for t in self._background:
                t.cancel()
            await asyncio.gather(*self._background, return_exceptions=True)
        logger.info("[Agents] Scheduler arrêté")

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[Agents] Tick échoué: {e}")
            await asyncio.sleep(60)

    async def _tick(self) -> None:
        now = self._now()
        hour_key = f"{now:%Y-%m-%d}_{now.hour:02d}"
        if hour_key != self._current_hour:
            self._current_hour = hour_key
            self._attempted.clear()  # nouvelle heure : on oublie les échecs précédents
        if self._api_key_provider():
            for persona in AGENT_PERSONAS:
                if now.hour in persona.schedule and self.is_enabled(persona):
                    slot = self._slot_key(now)
                    if slot in self._attempted:
                        continue  # déjà tenté ce créneau (échec) : on n'insiste pas
                    if self._slot_published(persona, now):
                        self._attempted.add(slot)
                        continue
                    # espacement minimal de 90s entre deux lancements de bots
                    if time.time() - self._last_launch_at < 90:
                        continue
                    if self._semaphore.locked():
                        continue
                    await self._launch(persona, now, slot)
                    break

    async def _launch(self, persona: AgentPersona, now: datetime, slot: str) -> None:
        """Lance la génération d'un bot en arrière-plan (un à la fois)."""
        self._last_launch_at = time.time()
        task = asyncio.create_task(self._run_one(persona, now, slot), name=f"agent-run-{persona.id}")
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _run_one(self, persona: AgentPersona, now: datetime, slot: str) -> None:
        async with self._semaphore:
            try:
                logger.info(f"[Agents] {persona.author} → créneau {slot} ({persona.theme})")
                await generate_and_publish(
                    persona,
                    api_key=self._api_key_provider(),
                    queue=self._queue,
                    monitor=self._monitor,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[Agents] {persona.author} échec créneau {slot}: {e}")
            finally:
                self._attempted.add(slot)

    # ── Publication immédiate (endpoint run-now) ─────────────────────
    async def run_now(self, agent_id: str) -> dict:
        persona = next((p for p in AGENT_PERSONAS if p.id == agent_id), None)
        if not persona:
            return {"ok": False, "error": f"Persona inconnu: {agent_id}"}
        if not self._api_key_provider():
            return {"ok": False, "error": "API key non configurée"}
        if self._semaphore.locked():
            return {"ok": False, "error": "Un autre bot est en cours de génération"}
        now = self._now()
        slot = self._slot_key(now)
        if slot in self._attempted:
            return {"ok": False, "error": f"Créneau {slot} déjà tenté pour {persona.author} (réessai à la prochaine heure)"}
        if self._slot_published(persona, now):
            self._attempted.add(slot)
            return {"ok": False, "error": f"Créneau {slot} déjà publié par {persona.author}"}
        await self._launch(persona, now, slot)
        return {"ok": True, "message": f"Lancement de {persona.author} pour le créneau {slot}"}

    # ── Statut public ────────────────────────────────────────────────
    def status(self) -> dict:
        now = self._now()
        items = []
        for persona in AGENT_PERSONAS:
            published = self._slot_published(persona, now)
            next_hour = next(
                (h for h in sorted(persona.schedule) if h > now.hour),
                min(persona.schedule) if persona.schedule else None,
            )
            items.append({
                "id": persona.id,
                "author": persona.author,
                "theme": persona.theme,
                "voice": persona.voice,
                "schedule": list(persona.schedule),
                "enabled": self.is_enabled(persona),
                "current_slot_published": published,
                "next_hour": next_hour,
            })
        return {
            "ok": True,
            "scheduler_running": bool(self._loop_task and not self._loop_task.done()),
            "api_key_configured": bool(self._api_key_provider()),
            "agents": items,
        }


# ── Singleton accessible depuis server.py ──────────────────────────────
_scheduler: Optional[AgentScheduler] = None


def get_scheduler() -> Optional[AgentScheduler]:
    return _scheduler


def set_scheduler(scheduler: AgentScheduler) -> None:
    global _scheduler
    _scheduler = scheduler
