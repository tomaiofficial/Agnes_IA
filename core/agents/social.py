"""
core/agents/social.py — Vie sociale des créateurs IA (v9.3)

Les bots se comportent comme de vrais membres de la communauté Vibes :
  - ils likent les vidéos des autres (humains ET bots), sans jamais retirer
    un like par accident (vérification `is_liked` avant `toggle_like`) ;
  - ils s'abonnent entre eux et aux créateurs humains actifs, une seule
    fois (`is_following` avant `follow_user`) ;
  - l'activité suit un rythme réaliste : quasi silencieuse la nuit,
    soutenue le jour et en soirée.

Le moteur ne consomme AUCUN quota Agnes (pas de chat / image / vidéo) :
il agit uniquement sur le CommunityStore. Toutes les écritures sont
précédées d'une lecture de vérification → strictement idempotent, safe
vis-à-vis des redéploiements (le store est persistant).

Note concurrence (backend local) : publish/toggle_like font un
read-modify-write sans verrou ; le social tourne ~1 s toutes les 15 min,
donc la fenêtre de collision avec une publication de bot (≤1/h) ou un
like humain simultané est négligeable et identique au comportement
multi-utilisateurs existant.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from typing import Callable, Optional

from core.agents.personas import AGENT_PERSONAS
from core.storage import CommunityStore

logger = logging.getLogger(__name__)

# Rythme selon l'heure (0-23) : probabilité qu'un bot agisse à un tick donné.
# Nuit (0-6h) quasi silencieux, aube/soirée timide, journée active.
def activity_probability(hour: int) -> float:
    if 0 <= hour < 7:
        return 0.10
    if 7 <= hour < 9 or hour >= 22:
        return 0.40
    return 0.80


_MAX_LIKES_PER_BOT = 2    # likes max par bot et par tick
_MAX_FOLLOWS_PER_BOT = 1  # abonnement max par bot et par tick
_MAX_TOTAL_LIKES = 16     # garde globale par tick (8 bots × 2)
_MAX_TOTAL_FOLLOWS = 8    # garde globale par tick
_BOT_FOLLOW_SEED = 3      # chaque bot s'abonne à 3 autres bots (graphe stable)
_SOCIAL_INTERVAL_S = 900  # 15 min entre deux ticks (appelé par le scheduler)

# v10.1: likeurs de foule — visiteurs anonymes simulés qui likent les vidéos
# fraîches, pour que les compteurs continuent de monter au-delà du plafond
# naturel des 15 bots (16 personas − l'auteur). Le pool est déterministe
# (crowd-0001 … crowd-N) et idempotent via toggle_like, comme les bots :
# aucune consommation de quota Agnes, aucun retrait de like.
_CROWD_SIZE = 300        # taille du pool de visiteurs simulés (plafond par vidéo)
_CROWD_FRESH_H = 96      # une vidéo attire la foule pendant 4 jours
_CROWD_VIDEOS = 5        # seules les vidéos les plus fraîches attirent la foule
_CROWD_MAX_PER_TICK = 3  # likes de foule max par tick (garde globale)
_CROWD_ATTEMPTS = 8      # tentatives max pour trouver un likeur pas encore passé


class AgentSocial:
    """Activité sociale (likes + abonnements) des créateurs IA."""

    def __init__(
        self,
        store_provider: Callable[[], CommunityStore],
        tz: Optional[str] = None,
    ):
        self._store_provider = store_provider
        self._tz = tz
        self._total_likes = 0
        self._total_follows = 0
        self._last_activity = 0.0
        self._last_tick = 0.0

    # ── Heure courante (fuseau AGENTS_TZ ou locale) ──────────────────
    def _now(self) -> datetime:
        if self._tz:
            try:
                from zoneinfo import ZoneInfo
                return datetime.now(ZoneInfo(self._tz)).replace(tzinfo=None)
            except Exception:
                pass
        return datetime.now()

    def _store(self) -> CommunityStore:
        return self._store_provider()

    def _enabled_personas(self) -> list:
        """Les bots actifs (même filtre que le scheduler de publication)."""
        try:
            from core.agents.scheduler import get_scheduler
            sched = get_scheduler()
            if sched is not None:
                return [p for p in AGENT_PERSONAS if sched.is_enabled(p)]
        except Exception:
            pass
        return list(AGENT_PERSONAS)

    # ── Tick principal ───────────────────────────────────────────────
    def run_tick(self) -> dict:
        """Un tour d'activité sociale. Retourne les compteurs du tick.

        À lancer au plus toutes les 15 min (voir _SOCIAL_INTERVAL_S).
        Fonction SYNC (le store est synchrone) : l'appelant l'exécute dans
        un thread via asyncio.to_thread pour ne pas geler l'event loop.
        """
        now = self._now()
        proba = activity_probability(now.hour)
        stats = {"likes": 0, "follows": 0, "acted_bots": 0}
        try:
            gallery = self._store().list_videos(page=1, per_page=50)
        except Exception as e:
            logger.warning(f"[Agents.Social] Galerie inaccessible: {e}")
            self._last_activity = time.time()
            return stats
        videos = gallery.get("videos") or []
        personas = self._enabled_personas()
        if not videos or not personas:
            self._last_activity = time.time()
            return stats

        self._tick_likes(personas, videos, proba, stats)
        self._tick_crowd_likes(videos, stats)
        self._tick_follows(personas, videos, proba, stats)

        self._total_likes += stats["likes"]
        self._total_follows += stats["follows"]
        self._last_activity = time.time()
        if stats["likes"] or stats["follows"]:
            crowd = stats.get("crowd", 0)
            logger.info(
                f"[Agents.Social] Tick {now:%H:%M}: {stats['likes']} like(s) "
                f"(dont {crowd} de foule), {stats['follows']} abonnement(s), "
                f"{stats['acted_bots']} bot(s) actifs"
            )
        return stats

    # ── Likes ────────────────────────────────────────────────────────
    def _tick_likes(self, personas, videos, proba: float, stats: dict) -> None:
        store = self._store()
        remaining = _MAX_TOTAL_LIKES
        for persona in personas:
            if remaining <= 0:
                break
            if random.random() > proba:
                continue
            done = 0
            for video in videos:
                if done >= _MAX_LIKES_PER_BOT or remaining <= 0:
                    break
                vid = video.get("id")
                owner = (video.get("user_id") or "").strip()
                if not vid or owner == persona.user_id:
                    continue
                try:
                    if store.is_liked(vid, persona.user_id):
                        continue
                    store.toggle_like(vid, persona.user_id)
                    done += 1
                    remaining -= 1
                    stats["likes"] += 1
                except KeyError:
                    continue  # vidéo supprimée entre la liste et le like
                except Exception as e:
                    logger.debug(f"[Agents.Social] Like {persona.id} → {vid}: {e}")
                    continue
            if done:
                stats["acted_bots"] += 1

    # ── Likes de foule (v10.1) ─────────────────────────────────────────
    def _tick_crowd_likes(self, videos, stats: dict) -> None:
        """Likes de visiteurs anonymes simulés sur les vidéos fraîches.

        Sans cette couche, les compteurs plafonnent à 15 likes : seuls les
        16 bots likent (l'auteur s'exclut lui-même). La foule fait monter
        les compteurs au fil du temps, avec un rythme réaliste : seules les
        vidéos récentes attirent, les anciennes refroidissent.
        """
        store = self._store()
        now = time.time()
        fresh = [
            v for v in videos
            if v.get("id") and now - float(v.get("published_at") or 0) < _CROWD_FRESH_H * 3600
        ]
        if not fresh:
            return
        fresh.sort(key=lambda v: float(v.get("published_at") or 0), reverse=True)
        fresh = fresh[:_CROWD_VIDEOS]
        remaining = _CROWD_MAX_PER_TICK
        for video in fresh:
            if remaining <= 0:
                break
            vid = video["id"]
            for _per_video in range(2):  # max 2 likes de foule par vidéo et par tick
                if remaining <= 0:
                    break
                liked_ok = False
                for _attempt in range(_CROWD_ATTEMPTS):
                    liker = "crowd-%04d" % random.randint(1, _CROWD_SIZE)
                    try:
                        result = store.toggle_like(vid, liker)
                    except KeyError:
                        return  # vidéo supprimée entre la liste et le like
                    except Exception as e:
                        logger.debug(f"[Agents.Social] Crowd like {vid}: {e}")
                        return
                    if result.get("liked"):
                        liked_ok = True
                        break
                if not liked_ok:
                    break  # pool saturé sur cette vidéo (tirage sans succès)
                remaining -= 1
                stats["likes"] += 1
                stats["crowd"] = stats.get("crowd", 0) + 1

    # ── Abonnements ──────────────────────────────────────────────────
    def _tick_follows(self, personas, videos, proba: float, stats: dict) -> None:
        store = self._store()
        remaining = _MAX_TOTAL_FOLLOWS
        persona_ids = [p.user_id for p in personas]

        # 1) Graphe stable inter-bots : chaque bot suit _BOT_FOLLOW_SEED autres bots.
        for persona in personas:
            if remaining <= 0:
                return
            if random.random() > proba:
                continue
            if store.get_following_count(persona.user_id) >= _BOT_FOLLOW_SEED:
                continue
            targets = [u for u in persona_ids if u != persona.user_id]
            random.shuffle(targets)
            for target in targets:
                if remaining <= 0:
                    return
                try:
                    if store.is_following(persona.user_id, target):
                        continue
                    store.follow_user(persona.user_id, target)
                    stats["follows"] += 1
                    remaining -= 1
                    stats["acted_bots"] += 1
                except Exception as e:
                    logger.debug(f"[Agents.Social] Follow {persona.id} → {target}: {e}")
                break  # un seul follow par bot par tick

        # 2) Suivre les créateurs humains actifs (vidéos récentes non bots).
        for persona in personas:
            if remaining <= 0:
                return
            if random.random() > proba:
                continue
            if store.get_following_count(persona.user_id) >= _BOT_FOLLOW_SEED + 3:
                continue
            for video in videos:
                if remaining <= 0:
                    return
                owner = (video.get("user_id") or "").strip()
                if not owner or owner.startswith("agent:") or owner == persona.user_id:
                    continue
                try:
                    if store.is_following(persona.user_id, owner):
                        continue
                    store.follow_user(persona.user_id, owner)
                    stats["follows"] += 1
                    remaining -= 1
                    stats["acted_bots"] += 1
                except Exception as e:
                    logger.debug(f"[Agents.Social] Follow humain {persona.id} → {owner}: {e}")
                break  # un seul follow humain par bot par tick

    # ── Statut public ────────────────────────────────────────────────
    def status(self) -> dict:
        return {
            "interval_s": _SOCIAL_INTERVAL_S,
            "likes_total": self._total_likes,
            "follows_total": self._total_follows,
            "last_activity": self._last_activity,
            "last_tick_ago_s": round(time.time() - self._last_tick, 1) if self._last_tick else None,
        }
