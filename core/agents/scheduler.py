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
from core.agents.social import AgentSocial, _SOCIAL_INTERVAL_S
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
        self._retry: dict = {}  # slot -> {"attempts": n, "next_at": epoch} (API down → retry)
        self._current_hour: Optional[str] = None
        self._attempted: Set[str] = set()  # créneaux déjà tentés dans l'heure courante (v9.3: fix initialisation manquante)
        self._max_attempts = 6      # 1 essai + 5 retries par créneau
        self._retry_delay = 600     # 10 min entre deux essais (API Agnes instable)
        # v9.3: vie sociale des bots (likes + abonnements), rythmée, sans quota Agnes
        self._social = AgentSocial(store_provider=get_community_store, tz=tz)
        self._social_last_tick = 0.0
        self._social_running = False
        # État local : {persona_id: {"enabled": bool}}
        self._state: dict = {}
        self._load_state()
        # v9.5: génération des photos de profil IA des personas (une fois au boot)
        self._avatars_started = False

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
        # v9.3: activé par défaut — les publications des bots sont en qualité
        # réduite (720p/10s) imposée par agent_runner : plus d'OOM du plan
        # Free 512 Mo. Un état explicitement désactivé via POST /api/agents/toggle
        # reste respecté (persisté dans agents_state.json).
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
        # v9.5: photos de profil IA des personas, en tâche de fond (pas bloquant).
        if not self._avatars_started:
            self._avatars_started = True
            task = asyncio.create_task(self._ensure_avatars(), name="agents-avatars")
            self._background.add(task)
            task.add_done_callback(self._background.discard)

    async def _ensure_avatars(self) -> None:
        """Génère et enregistre les avatars manquants des personas (idempotent)."""
        try:
            api_key = self._api_key_provider()
            if not api_key:
                return
            from core.agents.avatars import ensure_agent_avatars
            await ensure_agent_avatars(api_key)
        except Exception as e:
            logger.warning(f"[Agents.Avatars] Échec initialisation: {e}")

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
            self._retry.clear()  # nouvelle heure : on oublie les échecs précédents
        if self._api_key_provider():
            for persona in AGENT_PERSONAS:
                if now.hour in persona.schedule and self.is_enabled(persona):
                    slot = self._slot_key(now)
                    # Réessai espacé si la génération précédente a échoué (API down)
                    retry = self._retry.get(slot)
                    if retry:
                        if retry["attempts"] >= self._max_attempts:
                            continue  # créneau abandonné après trop d'échecs
                        if time.time() < retry["next_at"]:
                            continue  # pas encore l'heure du prochain essai
                    if self._slot_published(persona, now):
                        self._retry.pop(slot, None)
                        continue
                    # espacement minimal de 90s entre deux lancements de bots
                    if time.time() - self._last_launch_at < 90:
                        continue
                    if self._semaphore.locked():
                        continue
                    await self._launch(persona, now, slot)
                    break

        # v9.3: vie sociale des bots — toutes les 15 min, en tâche de fond
        # (to_thread : le store est synchrone), jamais deux ticks en parallèle.
        # Indépendant de l'API Agnes (aucun quota consommé).
        if (
            time.time() - self._social_last_tick >= _SOCIAL_INTERVAL_S
            and not self._social_running
        ):
            self._social_last_tick = time.time()
            self._social_running = True
            task = asyncio.create_task(self._run_social(), name="agents-social")
            self._background.add(task)
            task.add_done_callback(self._background.discard)

    async def _run_social(self) -> None:
        """Exécute un tick social des bots (dans un thread, hors event loop)."""
        try:
            await asyncio.to_thread(self._social.run_tick)
        except Exception as e:
            logger.warning(f"[Agents.Social] Tick échoué: {e}")
        finally:
            self._social_running = False

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
                    # v9.5: task_id DÉTERMINISTE du créneau → l'anti-doublon
                    # `find_published` fonctionne enfin : chaque bot publie UNE
                    # fois par créneau, le feed varie (plus "toujours Thomas").
                    task_id=self._task_id_for(persona, now),
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
            "social": self._social.status(),
            "agents": items,
        }


# ── Singleton accessible depuis server.py ──────────────────────────────
_scheduler: Optional[AgentScheduler] = None


def get_scheduler() -> Optional[AgentScheduler]:
    return _scheduler


def set_scheduler(scheduler: AgentScheduler) -> None:
    global _scheduler
    _scheduler = scheduler
