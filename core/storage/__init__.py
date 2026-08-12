"""
core/storage — Couche de stockage persistant (galerie communautaire + métadonnées de tâches)

Sélection automatique du backend selon l'environnement :
- variables SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY définies → Supabase (persistant, Render)
- sinon → système de fichiers local (développement, comportement historique)

**Fallback automatique** : si Supabase renvoie 402 (quota dépassé) ou 403,
basculement transparent vers le backend local.

Usage (server.py) :
    from core.storage import get_community_store, get_task_store, init_persistent_storage
    store = get_community_store()
    result = store.publish(...)
"""

import logging
import time
from typing import Optional

from .base import CommunityStore, TaskStore
from . import local_backend, supabase_backend

logger = logging.getLogger(__name__)

_community_store: Optional[CommunityStore] = None
_task_store: Optional[TaskStore] = None


def storage_mode() -> str:
    """'supabase' si le stockage persistant est configuré, sinon 'local'."""
    return "supabase" if supabase_backend.is_configured() else "local"


def is_persistent_storage() -> bool:
    return storage_mode() == "supabase"


def _is_quota_error(e: Exception) -> bool:
    """Détecte les erreurs de quota Supabase (402/403) pour déclencher le fallback."""
    msg = str(e).lower()
    return any(code in msg for code in ("402", "403", "exceed_cached_egress_quota", "payment required", "quota"))


class _FallbackCommunityStore(CommunityStore):
    """Wrapper qui tente Supabase puis bascule en local sur erreur de quota (402/403)."""

    def __init__(self):
        self._supabase = supabase_backend.SupabaseCommunityStore() if is_persistent_storage() else None
        self._local = local_backend.LocalCommunityStore()
        self._use_supabase = self._supabase is not None
        logger.info(f"[Storage] CommunityStore initialisé (mode={'supabase+fallback' if self._use_supabase else 'local'}).")

    def _call(self, method_name: str, *args, **kwargs):
        if not self._use_supabase:
            return getattr(self._local, method_name)(*args, **kwargs)
        try:
            return getattr(self._supabase, method_name)(*args, **kwargs)
        except Exception as e:
            # v10.1: repli local (temporaire) sur TOUTE erreur Supabase
            # (quota 402/403, projet suspendu, réseau, RLS, etc.). La galerie
            # reste fonctionnelle tant que Supabase est indisponible, et
            # récupère automatiquement dès que la couche persistante est
            # rétablie (sans redémarrage).
            logger.warning(f"[Storage] Supabase '{method_name}' a échoué ({e}) → repli local (temporaire).")
            return getattr(self._local, method_name)(*args, **kwargs)

    # Méthodes abstraites (obligatoires pour instancier CommunityStore)
    def publish(self, *a, **kw): return self._call("publish", *a, **kw)
    def list_videos(self, *a, **kw): return self._call("list_videos", *a, **kw)
    def get_meta(self, *a, **kw): return self._call("get_meta", *a, **kw)
    def toggle_like(self, *a, **kw): return self._call("toggle_like", *a, **kw)
    def get_comments(self, *a, **kw): return self._call("get_comments", *a, **kw)
    def add_comment(self, *a, **kw): return self._call("add_comment", *a, **kw)
    def get_video(self, *a, **kw): return self._call("get_video", *a, **kw)
    def find_published(self, *a, **kw): return self._call("find_published", *a, **kw)
    def delete(self, *a, **kw): return self._call("delete", *a, **kw)

    # Méthodes concrètes (redéfinies pour déléguer au vrai backend au lieu du
    # comportement par défaut de base.py qui renverrait un no-op/False/vide)
    def is_liked(self, *a, **kw): return self._call("is_liked", *a, **kw)
    def save_task_video_backup(self, *a, **kw): return self._call("save_task_video_backup", *a, **kw)
    def get_profile(self, *a, **kw): return self._call("get_profile", *a, **kw)
    def save_profile(self, *a, **kw): return self._call("save_profile", *a, **kw)
    def get_user_videos(self, *a, **kw): return self._call("get_user_videos", *a, **kw)
    def get_avatar_path(self, *a, **kw): return self._call("get_avatar_path", *a, **kw)
    def follow_user(self, *a, **kw): return self._call("follow_user", *a, **kw)
    def unfollow_user(self, *a, **kw): return self._call("unfollow_user", *a, **kw)
    def is_following(self, *a, **kw): return self._call("is_following", *a, **kw)
    def get_follower_count(self, *a, **kw): return self._call("get_follower_count", *a, **kw)
    def get_following_count(self, *a, **kw): return self._call("get_following_count", *a, **kw)

    def backfill_thumbnails(self, limit: int = 60, delay: float = 1.5) -> dict:
        """Optimisation Supabase uniquement (local : no-op)."""
        if not self._use_supabase:
            return {"done": 0, "failed": 0, "skipped": 0}
        try:
            return self._supabase.backfill_thumbnails(limit=limit, delay=delay)
        except Exception as e:
            if _is_quota_error(e):
                logger.warning(f"[Storage] Quota Supabase atteint ({e}) → backfill ignoré.")
                return {"done": 0, "failed": 0, "skipped": 0}
            raise


class _FallbackTaskStore(TaskStore):
    """Wrapper qui tente Supabase puis bascule en local sur erreur de quota (402/403)."""

    def __init__(self):
        self._supabase = supabase_backend.SupabaseTaskStore() if is_persistent_storage() else None
        self._local = local_backend.LocalTaskStore()
        self._use_supabase = self._supabase is not None
        logger.info(f"[Storage] TaskStore initialisé (mode={'supabase+fallback' if self._use_supabase else 'local'}).")

    def _call(self, method_name: str, *args, **kwargs):
        if not self._use_supabase:
            return getattr(self._local, method_name)(*args, **kwargs)
        try:
            return getattr(self._supabase, method_name)(*args, **kwargs)
        except Exception as e:
            # v10.1: repli local temporaire sur TOUTE erreur Supabase (voir
            # CommunityStore) — réessaie Supabase ensuite pour récupération
            # automatique dès que la couche persistante est rétablie.
            logger.warning(f"[Storage] Supabase '{method_name}' a échoué ({e}) → repli local (temporaire).")
            return getattr(self._local, method_name)(*args, **kwargs)

    # Méthodes abstraites (obligatoires pour instancier TaskStore)
    def upsert_meta(self, *a, **kw): return self._call("upsert_meta", *a, **kw)
    def get_meta(self, *a, **kw): return self._call("get_meta", *a, **kw)
    def list_meta(self, *a, **kw): return self._call("list_meta", *a, **kw)
    def delete_meta(self, *a, **kw): return self._call("delete_meta", *a, **kw)
    def mark_interrupted(self, *a, **kw): return self._call("mark_interrupted", *a, **kw)


def init_persistent_storage() -> None:
    """Initialise le backend persistant (schéma + bucket). Best-effort : les
    erreurs sont loguées sans bloquer le démarrage du serveur."""
    if not is_persistent_storage():
        logger.info("[Storage] Mode local (aucune config Supabase détectée).")
        return
    try:
        supabase_backend.ensure_schema()
    except Exception as e:
        logger.error(f"[Storage] Initialisation du schéma impossible: {e}")
    try:
        supabase_backend.ensure_bucket(supabase_backend._get_client())
    except Exception as e:
        logger.error(f"[Storage] Initialisation du bucket impossible: {e}")
    try:
        n = get_task_store().mark_interrupted(
            "Interrompu: le serveur a redémarré (état restauré depuis la base)"
        )
        if n:
            logger.info(f"[Storage] {n} tâche(s) marquée(s) interrompue(s).")
    except Exception as e:
        logger.warning(f"[Storage] Marquage des tâches interrompues impossible: {e}")
    try:
        from core.config import restore_config_from_storage

        restore_config_from_storage()
    except Exception as e:
        logger.warning(f"[Storage] Restauration de la configuration impossible: {e}")


def get_community_store() -> CommunityStore:
    global _community_store
    if _community_store is None:
        _community_store = _FallbackCommunityStore()
    return _community_store


def get_task_store() -> TaskStore:
    global _task_store
    if _task_store is None:
        _task_store = _FallbackTaskStore()
    return _task_store


def export_meta(state, dir_name: str) -> dict:
    """Extrait les métadonnées persistables d'un état de tâche (BaseTaskState)."""
    task_type = getattr(state, "task_type", None)
    status = getattr(state, "status", None)
    prompt = ""
    if hasattr(state, "prompt"):
        prompt = state.prompt or ""
    elif hasattr(state, "idea"):
        prompt = state.idea or ""
    elif hasattr(state, "manuscript_text"):
        prompt = state.manuscript_text or ""
    elif hasattr(state, "script_text"):
        prompt = state.script_text or ""
    elif hasattr(state, "poem_text"):
        prompt = state.poem_text or ""
    now = time.time()

    # v8.14: paramètres de génération persistés → reprise automatique après
    # redéploiement (disque éphémère effacé). Prompt moins tronqué (2000)
    # pour que la relance du mode avancé garde un prompt complet.
    params = {}
    if hasattr(state, "duration"):
        mode = getattr(state, "mode", None)
        params = {
            "duration": getattr(state, "duration", None),
            "video_width": getattr(state, "video_width", None),
            "video_height": getattr(state, "video_height", None),
            "seed": getattr(state, "seed", None),
            "negative_prompt": getattr(state, "negative_prompt", None),
            "system_prompt": getattr(state, "system_prompt", ""),
            "mode": mode.value if hasattr(mode, "value") else str(mode or ""),
            "audio_enabled": getattr(state, "audio_enabled", None),
            "audio_voice": getattr(state, "audio_voice", None),
            "audio_rate": getattr(state, "audio_rate", None),
            "quality_boost": getattr(state, "quality_boost", False),
            # Mode avancé (v8.14)
            "advanced_mode": getattr(state, "advanced_mode", False),
            "quality": getattr(state, "quality", None),
            "style": getattr(state, "style", None),
            "denoise": getattr(state, "denoise", None),
            "face_enhance": getattr(state, "face_enhance", None),
            "motion_enhance": getattr(state, "motion_enhance", None),
            "hdr": getattr(state, "hdr", None),
            "color_correct": getattr(state, "color_correct", None),
            "compress": getattr(state, "compress", None),
            "optimize_prompt": getattr(state, "optimize_prompt", None),
        }

    return {
        "task_id": getattr(state, "task_id", "") or "",
        "dir_name": dir_name or "",
        "task_type": task_type.value if hasattr(task_type, "value") else str(task_type or ""),
        "creative_name": getattr(state, "creative_name", "") or "",
        "user_id": getattr(state, "user_id", "") or "",
        "status": status.value if hasattr(status, "value") else str(status or "pending"),
        "prompt": (prompt or "")[:2000],
        "current_message": getattr(state, "current_message", "") or "",
        "final_video_file": getattr(state, "final_video_file", "") or "",
        "video_backup_url": getattr(state, "video_backup_url", "") or "",
        "params": params,
        "resume_attempts": int(getattr(state, "resume_attempts", 0) or 0),
        "created_at": _created_at_from_dir(dir_name),
        "updated_at": now,
    }


def _created_at_from_dir(dir_name: str) -> Optional[float]:
    """Timestamp de création estimé depuis 'YYYYMMDD_HHMMSS_xxx' (ou None)."""
    from .supabase_backend import _dir_name_to_ts

    return _dir_name_to_ts(dir_name)
