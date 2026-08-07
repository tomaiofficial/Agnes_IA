"""
core/storage/supabase_backend.py — Backend de stockage persistant Supabase

Fournit deux stores résilients au redéploiement Render :
- SupabaseCommunityStore : vidéos → Supabase Storage (bucket public), métadonnées
  (prompt, auteur, likes, commentaires) → tables Postgres.
- SupabaseTaskStore : métadonnées de tâches → table Postgres (survit aux redémarrages).

Configuration (variables d'environnement) :
- SUPABASE_URL                 (obligatoire) ex. https://abcd.supabase.co
- SUPABASE_SERVICE_ROLE_KEY    (obligatoire) clé service (bypass RLS, serveur uniquement)
- SUPABASE_DATABASE_URL        (conseillé) chaîne Postgres pour la création auto du schéma
- SUPABASE_STORAGE_BUCKET      (optionnel) nom du bucket, défaut "agnes-community"

Schéma : voir supabase/schema.sql dans le dépôt (création auto au démarrage si
SUPABASE_DATABASE_URL est fournie, sinon à exécuter manuellement dans le SQL Editor).
"""

import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from typing import List, Optional, Set

from .base import CommunityStore, TaskStore

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "") or ""
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") or ""
SUPABASE_DATABASE_URL = os.environ.get("SUPABASE_DATABASE_URL", "") or ""
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "") or "agnes-community"

DEFAULT_VIDEO_MIME = "video/mp4"

# Vignettes : convention de nommage `thumbnails/{video_id}.jpg` dans le bucket
# (pas de colonne SQL : les vignettes sont dérivées du video_id et détectées
# par un list du dossier — fonctionne sans migration de schéma).
_THUMB_PREFIX = "thumbnails/"
_THUMB_MIME = "image/jpeg"

# ffmpeg statique (imageio-ffmpeg) pour extraire la 1ère frame des vidéos.
try:
    import imageio_ffmpeg

    _FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:  # pragma: no cover — environnement sans imageio-ffmpeg
    _FFMPEG_EXE = ""

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS community_videos (
    id            TEXT PRIMARY KEY,
    task_id       TEXT NOT NULL DEFAULT '',
    author        TEXT NOT NULL DEFAULT 'Anonyme',
    prompt        TEXT NOT NULL DEFAULT '',
    duration      DOUBLE PRECISION NOT NULL DEFAULT 0,
    resolution    TEXT NOT NULL DEFAULT '',
    published_at  DOUBLE PRECISION NOT NULL,
    storage_path  TEXT NOT NULL DEFAULT '',
    created_at    DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS community_likes (
    video_id     TEXT NOT NULL REFERENCES community_videos(id) ON DELETE CASCADE,
    visitor_hash TEXT NOT NULL,
    created_at   DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (video_id, visitor_hash)
);

CREATE TABLE IF NOT EXISTS community_comments (
    id         TEXT PRIMARY KEY,
    video_id   TEXT NOT NULL REFERENCES community_videos(id) ON DELETE CASCADE,
    author     TEXT NOT NULL DEFAULT 'Anonyme',
    text       TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);

-- Profils utilisateurs (façon TikTok/Instagram) : pseudo/bio/avatar persistés
-- par user_id (le même identifiant opaque X-User-Id que les publications).
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id     TEXT PRIMARY KEY,
    pseudo      TEXT NOT NULL DEFAULT '',
    bio         TEXT NOT NULL DEFAULT '',
    avatar_path TEXT NOT NULL DEFAULT '',
    created_at  DOUBLE PRECISION NOT NULL,
    updated_at  DOUBLE PRECISION NOT NULL
);

-- Abonnements entre profils (follower → followed), dédoublonnés par PK.
CREATE TABLE IF NOT EXISTS profile_follows (
    follower_id TEXT NOT NULL,
    followed_id TEXT NOT NULL,
    created_at  DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (follower_id, followed_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id          TEXT PRIMARY KEY,
    dir_name         TEXT NOT NULL DEFAULT '',
    task_type        TEXT NOT NULL DEFAULT '',
    creative_name    TEXT NOT NULL DEFAULT '',
    user_id          TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'pending',
    prompt           TEXT NOT NULL DEFAULT '',
    current_message  TEXT NOT NULL DEFAULT '',
    final_video_file TEXT NOT NULL DEFAULT '',
    video_backup_url TEXT NOT NULL DEFAULT '',
    created_at       DOUBLE PRECISION,
    updated_at       DOUBLE PRECISION
);

-- Migration idempotente (table déjà créée avant l'ajout de user_id) :
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT '';

-- Migration idempotente : URL de sauvegarde Supabase de la vidéo finale
-- (lecture possible après redéploiement, disque éphémère effacé) :
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS video_backup_url TEXT NOT NULL DEFAULT '';

-- Migration idempotente (v8.14) : paramètres de génération JSON + compteur de
-- reprises automatiques. Permettent de RELANCER une tâche simple/advanced
-- interrompue par un redéploiement (état reconstruit depuis la base).
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS params JSONB NOT NULL DEFAULT '{}';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS resume_attempts INT NOT NULL DEFAULT 0;

-- Migration idempotente : user_id du créateur d'une publication galerie
-- ('' = publication héritée, créée avant l'isolation par créateur).
ALTER TABLE community_videos ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT '';

-- Configuration applicative (clé API, filigrane, modèles, domaine, workspaces…)
-- : survit aux redéploiements Render (miroir + restauration au démarrage)
CREATE TABLE IF NOT EXISTS app_config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT '{}',
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_community_likes_video   ON community_likes(video_id);
CREATE INDEX IF NOT EXISTS idx_community_comments_video ON community_comments(video_id);
CREATE INDEX IF NOT EXISTS idx_tasks_updated           ON tasks(updated_at);
CREATE INDEX IF NOT EXISTS idx_tasks_user             ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_profile_follows_followed ON profile_follows(followed_id);

-- RLS activé sur toutes les tables (idempotent) : seules les clés de rôle
-- service/postgres y accèdent (l'application n'utilise jamais la clé anon).
ALTER TABLE community_videos   ENABLE ROW LEVEL SECURITY;
ALTER TABLE community_likes    ENABLE ROW LEVEL SECURITY;
ALTER TABLE community_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles     ENABLE ROW LEVEL SECURITY;
ALTER TABLE profile_follows   ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks              ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_config         ENABLE ROW LEVEL SECURITY;
"""


def is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def ensure_schema() -> None:
    """Crée les tables (idempotent) via la chaîne Postgres fournie.

    Sans SUPABASE_DATABASE_URL, on laisse l'opérateur exécuter supabase/schema.sql
    manuellement (un warning est émis).
    """
    if not is_configured():
        return
    if not SUPABASE_DATABASE_URL:
        logger.warning(
            "[Storage] SUPABASE_DATABASE_URL absent : exécuter supabase/schema.sql "
            "dans le SQL Editor Supabase pour créer les tables."
        )
        return
    import psycopg2

    conn = None
    try:
        conn = psycopg2.connect(SUPABASE_DATABASE_URL, connect_timeout=15)
        with conn.cursor() as cur:
            cur.execute(SCHEMA_DDL)
        conn.commit()
        logger.info("[Storage] Schéma Supabase vérifié (tables prêtes).")
    except Exception as e:
        logger.error(f"[Storage] Échec de l'initialisation du schéma: {e}")
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def ensure_bucket(client) -> None:
    """Crée le bucket public (idempotent) si nécessaire."""
    try:
        client.storage.get_bucket(SUPABASE_STORAGE_BUCKET)
        logger.info(f"[Storage] Bucket '{SUPABASE_STORAGE_BUCKET}' déjà présent.")
        return
    except Exception:
        pass
    try:
        client.storage.create_bucket(SUPABASE_STORAGE_BUCKET, options={"public": True})
        logger.info(f"[Storage] Bucket public '{SUPABASE_STORAGE_BUCKET}' créé.")
    except Exception as e:
        logger.warning(f"[Storage] Création du bucket impossible (créer manuellement): {e}")


_client_cache = None


def _get_client():
    """Client Supabase paresseux (service role key — côté serveur uniquement)."""
    global _client_cache
    if _client_cache is None:
        from supabase import create_client

        _client_cache = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _client_cache


# ═══════════════════════════════════════════════════
# Configuration applicative persistante (app_config)
# ═══════════════════════════════════════════════════

APP_CONFIG_ROW = "main"


def mirror_config(config: dict) -> None:
    """Persiste la configuration applicative (clé API, filigrane, modèles, domaine…)
    dans la table app_config. Best-effort : un échec ne casse jamais la sauvegarde locale."""
    if not is_configured():
        return
    try:
        _get_client().table("app_config").upsert(
            {
                "key": APP_CONFIG_ROW,
                "value": json.dumps(config or {}, ensure_ascii=False),
                "updated_at": time.time(),
            },
            on_conflict="key",
        ).execute()
    except Exception as e:
        logger.warning(f"[Storage] Échec du miroir de configuration Supabase: {e}")


def restore_config() -> Optional[dict]:
    """Recharge la configuration persistée depuis app_config (ou None si absente).

    Utilisée au démarrage : après un redéploiement Render, le fichier local
    n'existe plus mais la config est restituée depuis la base."""
    if not is_configured():
        return None
    try:
        res = (
            _get_client()
            .table("app_config")
            .select("value")
            .eq("key", APP_CONFIG_ROW)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.warning(f"[Storage] Lecture de la configuration Supabase impossible: {e}")
        return None
    rows = res.data or []
    if not rows:
        return None
    try:
        value = json.loads(rows[0].get("value") or "{}")
    except Exception:
        logger.warning("[Storage] Configuration Supabase illisible (JSON invalide).")
        return None
    return value if isinstance(value, dict) else None


def _dir_name_to_ts(dir_name: str) -> Optional[float]:
    """Extrait un timestamp depuis un nom de dossier 'YYYYMMDD_HHMMSS_xxx'."""
    m = re.match(r"(\d{8})_(\d{6})", dir_name or "")
    if not m:
        return None
    try:
        dt = datetime.strptime(f"{m.group(1)}{m.group(2)}", "%Y%m%d%H%M%S")
        return dt.timestamp()
    except ValueError:
        return None


def _norm_meta(row: dict) -> dict:
    """Normalise une ligne `tasks` lue depuis PostgREST (JSONB → dict)."""
    row = dict(row)
    params = row.get("params") or {}
    if isinstance(params, str):
        try:
            params = json.loads(params) or {}
        except (ValueError, TypeError):
            params = {}
    row["params"] = params if isinstance(params, dict) else {}
    try:
        row["resume_attempts"] = int(row.get("resume_attempts") or 0)
    except (ValueError, TypeError):
        row["resume_attempts"] = 0
    return row


class SupabaseCommunityStore(CommunityStore):
    """Galerie communautaire persistante (Storage + Postgres)."""

    def _storage(self):
        return _get_client().storage.from_(SUPABASE_STORAGE_BUCKET)

    def _public_url(self, storage_path: str) -> str:
        try:
            return self._storage().get_public_url(storage_path)
        except Exception:
            return f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/{storage_path}"

    def _extract_frame(self, source: str, out_path: str, position: float = 0.5,
                       timeout: int = 40) -> bool:
        """Extrait une frame (JPEG) d'une vidéo locale ou d'une URL publique.

        `source` peut être un chemin local ou une URL http(s) : ffmpeg sait
        lire les deux (seek rapide pour les URLs, quelques centaines de Ko
        téléchargés seulement). Retourne False en cas d'échec (jamais d'exception).
        """
        if not _FFMPEG_EXE or not source:
            return False
        try:
            cmd = [
                _FFMPEG_EXE, "-y", "-loglevel", "error",
                "-ss", str(position),
                "-i", source,
                "-frames:v", "1", "-q:v", "4",
                out_path,
            ]
            proc = subprocess.run(
                cmd, capture_output=True, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if proc.returncode != 0:
                logger.warning(f"[CommunityStore] Extraction frame échouée: {proc.stderr[:200]}")
                return False
            return os.path.exists(out_path) and os.path.getsize(out_path) > 0
        except Exception as e:
            logger.warning(f"[CommunityStore] Extraction frame impossible: {e}")
            return False

    def _upload_thumbnail(self, video_id: str, jpg_path: str) -> bool:
        """Publie la vignette `thumbnails/{video_id}.jpg` dans le bucket."""
        try:
            with open(jpg_path, "rb") as f:
                data = f.read()
            self._storage().upload(f"{_THUMB_PREFIX}{video_id}.jpg", data,
                                   {"content-type": _THUMB_MIME})
            return True
        except Exception as e:
            logger.warning(f"[CommunityStore] Upload vignette {video_id} impossible: {e}")
            return False

    def _thumbnail_url(self, video_id: str) -> str:
        return self._public_url(f"{_THUMB_PREFIX}{video_id}.jpg")

    def publish(self, task_id, author, prompt, duration, resolution, video_path,
                user_id: str = "") -> dict:
        import uuid

        client = _get_client()
        video_id = uuid.uuid4().hex[:12]
        storage_path = f"videos/{video_id}.mp4"
        with open(video_path, "rb") as f:
            data = f.read()
        self._storage().upload(storage_path, data, {"content-type": DEFAULT_VIDEO_MIME})
        now = time.time()
        client.table("community_videos").insert({
            "id": video_id,
            "task_id": task_id,
            "author": author or "Anonyme",
            "prompt": prompt,
            "duration": duration,
            "resolution": resolution,
            "published_at": now,
            "storage_path": storage_path,
            "created_at": now,
            "user_id": user_id or "",
        }).execute()
        logger.info(
            f"[CommunityStore] Published {video_id} -> supabase storage "
            f"({len(data)} octets, bucket={SUPABASE_STORAGE_BUCKET})"
        )
        # Vignette : extraire la 1ère frame et la publier (non bloquant — un
        # échec ne retire pas la vidéo du flux, le front affiche alors un fond).
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = tmp.name
            if self._extract_frame(video_path, tmp_path):
                self._upload_thumbnail(video_id, tmp_path)
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception as e:
            logger.warning(f"[CommunityStore] Vignette {video_id} ignorée: {e}")
        return {"video_id": video_id, "video_url": self._public_url(storage_path)}

    def save_task_video_backup(self, task_id: str, video_path: str) -> Optional[str]:
        """Sauvegarde la vidéo finale d'une tâche (copie privée de secours).

        Upload vers `backup/{task_id}.mp4` dans le bucket Supabase et retourne
        l'URL publique, ou None en cas d'échec. Ne publie rien dans la galerie :
        c'est une copie de secours, référencée par `tasks.video_backup_url` pour
        rester lisible après un redéploiement Render (disque éphémère effacé).
        """
        try:
            if not task_id or not video_path or not os.path.exists(video_path):
                return None
            storage_path = f"backup/{task_id}.mp4"
            with open(video_path, "rb") as f:
                data = f.read()
            self._storage().upload(storage_path, data, {"content-type": DEFAULT_VIDEO_MIME})
            logger.info(
                f"[CommunityStore] Backup vidéo {task_id} -> supabase storage "
                f"({len(data)} octets, bucket={SUPABASE_STORAGE_BUCKET})"
            )
            return self._public_url(storage_path)
        except Exception as e:
            logger.warning(f"[CommunityStore] Échec sauvegarde vidéo {task_id}: {e}")
            return None

    def _row_to_video(self, row: dict, like_counts: dict, comment_counts: dict,
                      avatars: Optional[dict] = None,
                      verified: Optional[dict] = None,
                      thumbnail_ids: Optional[Set[str]] = None) -> dict:
        vid = row["id"]
        prompt = row.get("prompt", "") or ""
        avatars = avatars or {}
        verified = verified or {}
        has_thumb = bool(thumbnail_ids) and vid in thumbnail_ids
        return {
            "id": vid,
            "title": prompt[:80] if prompt else "Untitled",
            "author": row.get("author") or "Anonyme",
            "prompt": prompt,
            "duration": row.get("duration", 0) or 0,
            "resolution": row.get("resolution", "") or "",
            "published_at": row.get("published_at", 0) or 0,
            "user_id": row.get("user_id", "") or "",
            "avatar_url": avatars.get(row.get("user_id") or "", "") or "",
            "author_verified": bool(verified.get(row.get("user_id") or "")),
            "likes": like_counts.get(vid, 0),
            "comments_count": comment_counts.get(vid, 0),
            "video_url": self._public_url(row.get("storage_path") or f"videos/{vid}.mp4"),
            # Vraie vignette JPEG si elle existe, sinon "" → le front affiche un
            # fond de chargement au lieu d'un écran noir (façon TikTok).
            "thumbnail": self._thumbnail_url(vid) if has_thumb else "",
        }

    def _list_thumbnail_ids(self) -> Set[str]:
        """IDs des vidéos ayant une vignette, en une seule requête storage."""
        try:
            res = self._storage().list(_THUMB_PREFIX.rstrip("/"), {"limit": 2000})
            out = set()
            for item in res or []:
                name = (item.get("name") or "").strip()
                if name.endswith(".jpg"):
                    out.add(name[:-4])
            return out
        except Exception as e:
            logger.warning(f"[CommunityStore] Liste des vignettes impossible: {e}")
            return set()

    def _avatars_by_user(self, user_ids: list) -> dict:
        """Avatar (URL publique) par user_id, en une seule requête groupée."""
        ids = sorted({uid for uid in (user_ids or []) if uid and uid.strip()})
        if not ids:
            return {}
        try:
            res = (
                _get_client().table("user_profiles")
                .select("user_id", "avatar_path")
                .in_("user_id", ids)
                .execute()
            )
        except Exception as e:
            logger.warning(f"[CommunityStore] Lecture des avatars impossible: {e}")
            return {}
        out = {}
        for row in res.data or []:
            path = (row.get("avatar_path") or "").strip()
            if path:
                out[row["user_id"]] = self._public_url(path)
        return out

    def _videos_with_counts(self, rows: list, avatars: Optional[dict] = None,
                            verified: Optional[dict] = None) -> list:
        """Attache likes/commentaires/avatars/certification à des lignes community_videos."""
        client = _get_client()
        ids = [r["id"] for r in rows]
        like_counts: dict = {}
        comment_counts: dict = {}
        if ids:
            try:
                likes_res = (
                    client.table("community_likes").select("video_id").in_("video_id", ids).execute()
                )
                for like in likes_res.data or []:
                    like_counts[like["video_id"]] = like_counts.get(like["video_id"], 0) + 1
            except Exception as e:
                logger.warning(f"[CommunityStore] Lecture des likes impossible: {e}")
            try:
                comments_res = (
                    client.table("community_comments").select("video_id").in_("video_id", ids).execute()
                )
                for c in comments_res.data or []:
                    comment_counts[c["video_id"]] = comment_counts.get(c["video_id"], 0) + 1
            except Exception as e:
                logger.warning(f"[CommunityStore] Lecture des commentaires impossible: {e}")
        if avatars is None:
            avatars = self._avatars_by_user([r.get("user_id", "") for r in rows])
        if verified is None:
            verified = self._verified_by_user([r.get("user_id", "") for r in rows])
        thumbnail_ids = self._list_thumbnail_ids()
        return [
            self._row_to_video(r, like_counts, comment_counts, avatars, verified, thumbnail_ids)
            for r in rows
        ]

    def list_videos(self, page=1, per_page=20) -> dict:
        client = _get_client()
        start = (page - 1) * per_page
        res = (
            client.table("community_videos")
            .select("*")
            .order("published_at", desc=True)
            .limit(per_page)
            .offset(start)
            .execute()
        )
        rows = res.data or []
        total = 0
        try:
            total_res = (
                client.table("community_videos").select("id", count="exact").limit(1).execute()
            )
            total = total_res.count or 0
        except Exception:
            total = len(rows)
        return {
            "videos": self._videos_with_counts(rows),
            "total": total,
        }

    def get_meta(self, video_id: str) -> Optional[dict]:
        res = (
            _get_client().table("community_videos")
            .select("*").eq("id", video_id).limit(1).execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    def toggle_like(self, video_id: str, visitor_hash: str) -> dict:
        client = _get_client()
        if not self.get_meta(video_id):
            raise KeyError(video_id)
        existing = (
            client.table("community_likes")
            .select("visitor_hash")
            .eq("video_id", video_id)
            .eq("visitor_hash", visitor_hash)
            .limit(1)
            .execute()
        )
        liked = bool(existing.data)
        if liked:
            (
                client.table("community_likes")
                .delete().eq("video_id", video_id).eq("visitor_hash", visitor_hash)
                .execute()
            )
        else:
            client.table("community_likes").insert({
                "video_id": video_id,
                "visitor_hash": visitor_hash,
                "created_at": time.time(),
            }).execute()
        count_res = (
            client.table("community_likes")
            .select("visitor_hash", count="exact").eq("video_id", video_id).execute()
        )
        return {"ok": True, "likes": count_res.count or 0, "liked": not liked}

    def is_liked(self, video_id: str, visitor_hash: str) -> bool:
        """True si `visitor_hash` a déjà liké la vidéo (lecture seule)."""
        if not self.get_meta(video_id):
            raise KeyError(video_id)
        res = (
            _get_client().table("community_likes")
            .select("visitor_hash")
            .eq("video_id", video_id)
            .eq("visitor_hash", visitor_hash)
            .limit(1)
            .execute()
        )
        return bool(res.data)

    def get_comments(self, video_id: str) -> List[dict]:
        if not self.get_meta(video_id):
            raise KeyError(video_id)
        res = (
            _get_client().table("community_comments")
            .select("id", "author", "text", "created_at")
            .eq("video_id", video_id)
            .order("created_at", desc=False)
            .execute()
        )
        return [dict(c) for c in (res.data or [])]

    def add_comment(self, video_id: str, author: str, text: str) -> dict:
        import uuid

        client = _get_client()
        if not self.get_meta(video_id):
            raise KeyError(video_id)
        comment = {
            "id": uuid.uuid4().hex[:8],
            "author": author or "Anonyme",
            "text": text,
            "created_at": time.time(),
        }
        client.table("community_comments").insert({
            "id": comment["id"],
            "video_id": video_id,
            "author": comment["author"],
            "text": comment["text"],
            "created_at": comment["created_at"],
        }).execute()
        count_res = (
            client.table("community_comments")
            .select("id", count="exact").eq("video_id", video_id).execute()
        )
        return {
            "ok": True,
            "comment": comment,
            "comments_count": count_res.count or 0,
        }

    def get_video(self, video_id: str) -> Optional[str]:
        meta = self.get_meta(video_id)
        if not meta:
            return None
        return self._public_url(meta.get("storage_path") or f"videos/{video_id}.mp4")

    def find_published(self, task_id: str) -> Optional[dict]:
        res = (
            _get_client().table("community_videos")
            .select("*").eq("task_id", task_id)
            .order("published_at", desc=True).limit(1).execute()
        )
        rows = res.data or []
        if not rows:
            return None
        row = rows[0]
        storage_path = row.get("storage_path") or f"videos/{row['id']}.mp4"
        url = self._public_url(storage_path)
        return {"video_id": row["id"], "video_url": url, "video_target": url}

    # ── Profils utilisateurs (façon TikTok/Instagram) ─────────────────────

    def get_profile(self, user_id: str) -> Optional[dict]:
        if not user_id:
            return None
        res = (
            _get_client().table("user_profiles")
            .select("*").eq("user_id", user_id).limit(1).execute()
        )
        rows = res.data or []
        if not rows:
            return None
        row = rows[0]
        avatar_path = (row.get("avatar_path") or "").strip()
        return {
            "user_id": row["user_id"],
            "pseudo": row.get("pseudo") or "",
            "bio": row.get("bio") or "",
            "avatar_url": self._public_url(avatar_path) if avatar_path else "",
            "created_at": row.get("created_at", 0) or 0,
            "updated_at": row.get("updated_at", 0) or 0,
        }

    def save_profile(
        self,
        user_id: str,
        pseudo: str = "",
        bio: str = "",
        avatar_bytes: Optional[bytes] = None,
        avatar_content_type: str = "",
    ) -> dict:
        client = _get_client()
        now = time.time()
        existing_res = (
            client.table("user_profiles").select("*").eq("user_id", user_id).limit(1).execute()
        )
        existing = (existing_res.data or [None])[0]
        avatar_path = ""
        if avatar_bytes:
            ext = {"image/jpeg": "jpg", "image/webp": "webp",
                   "image/gif": "gif"}.get(avatar_content_type or "", "png")
            avatar_path = f"avatars/{user_id}.{ext}"
            if existing and (existing.get("avatar_path") or "") != avatar_path:
                old = (existing.get("avatar_path") or "").strip()
                if old:
                    try:
                        self._storage().remove([old])
                    except Exception as e:
                        logger.warning(f"[CommunityStore] Suppression ancien avatar {old}: {e}")
            self._storage().upload(
                avatar_path, avatar_bytes,
                {"content-type": avatar_content_type or "image/png"},
            )
        if existing:
            updates = {
                "pseudo": (pseudo or "").strip()[:30],
                "bio": (bio or "").strip()[:160],
                "updated_at": now,
            }
            if avatar_path:
                updates["avatar_path"] = avatar_path
            client.table("user_profiles").update(updates).eq("user_id", user_id).execute()
        else:
            client.table("user_profiles").insert({
                "user_id": user_id,
                "pseudo": (pseudo or "").strip()[:30],
                "bio": (bio or "").strip()[:160],
                "avatar_path": avatar_path,
                "created_at": now,
                "updated_at": now,
            }).execute()
        logger.info(f"[CommunityStore] Profil enregistré pour {user_id} "
                    f"(pseudo={pseudo!r}, avatar={'oui' if avatar_path else 'non'})")
        return self.get_profile(user_id)

    def get_user_videos(self, user_id: str, page: int = 1, per_page: int = 50) -> dict:
        if not user_id:
            return {"videos": [], "total": 0}
        client = _get_client()
        start = (page - 1) * per_page
        res = (
            client.table("community_videos")
            .select("*")
            .eq("user_id", user_id)
            .order("published_at", desc=True)
            .limit(per_page)
            .offset(start)
            .execute()
        )
        rows = res.data or []
        total = 0
        try:
            total_res = (
                client.table("community_videos").select("id", count="exact")
                .eq("user_id", user_id).limit(1).execute()
            )
            total = total_res.count or 0
        except Exception:
            total = len(rows)
        avatars = self._avatars_by_user([user_id])
        verified = self._verified_by_user([user_id])
        return {"videos": self._videos_with_counts(rows, avatars=avatars, verified=verified),
                "total": total}

    def get_avatar_path(self, user_id: str) -> Optional[str]:
        if not user_id:
            return None
        try:
            res = (
                _get_client().table("user_profiles")
                .select("avatar_path").eq("user_id", user_id).limit(1).execute()
            )
            rows = res.data or []
        except Exception:
            return None
        if not rows:
            return None
        path = (rows[0].get("avatar_path") or "").strip()
        if not path:
            return None
        return self._public_url(path)

    # ── Abonnements (follow) ─────────────────────────────────────────────

    def follow_user(self, follower_id: str, followed_id: str) -> dict:
        """Abonne `follower_id` à `followed_id` (idempotent grâce à la PK)."""
        if not follower_id or not followed_id or follower_id == followed_id:
            return {"following": False,
                    "follower_count": self.get_follower_count(followed_id)}
        try:
            _get_client().table("profile_follows").insert({
                "follower_id": follower_id,
                "followed_id": followed_id,
                "created_at": time.time(),
            }).execute()
        except Exception:
            pass  # déjà abonné (violation de PK) — état idempotent
        return {"following": True,
                "follower_count": self.get_follower_count(followed_id)}

    def unfollow_user(self, follower_id: str, followed_id: str) -> dict:
        if not follower_id or not followed_id:
            return {"following": False,
                    "follower_count": self.get_follower_count(followed_id)}
        try:
            (_get_client().table("profile_follows").delete()
             .eq("follower_id", follower_id)
             .eq("followed_id", followed_id).execute())
        except Exception:
            pass
        return {"following": False,
                "follower_count": self.get_follower_count(followed_id)}

    def is_following(self, follower_id: str, followed_id: str) -> bool:
        if not follower_id or not followed_id:
            return False
        res = (
            _get_client().table("profile_follows").select("follower_id")
            .eq("follower_id", follower_id)
            .eq("followed_id", followed_id).limit(1).execute()
        )
        return bool(res.data)

    def get_follower_count(self, user_id: str) -> int:
        if not user_id:
            return 0
        res = (
            _get_client().table("profile_follows").select("follower_id", count="exact")
            .eq("followed_id", user_id).limit(1).execute()
        )
        return res.count or 0

    def get_following_count(self, user_id: str) -> int:
        if not user_id:
            return 0
        res = (
            _get_client().table("profile_follows").select("followed_id", count="exact")
            .eq("follower_id", user_id).limit(1).execute()
        )
        return res.count or 0

    # ── Certification (badge bleu à partir de 5 vidéos publiées) ─────────

    def _verified_by_user(self, user_ids: list) -> dict:
        """user_id → True si l'utilisateur a publié ≥ 5 vidéos (requête groupée)."""
        ids = sorted({uid for uid in (user_ids or []) if uid and uid.strip()})
        if not ids:
            return {}
        try:
            res = (
                _get_client().table("community_videos")
                .select("user_id").in_("user_id", ids).execute()
            )
        except Exception as e:
            logger.warning(f"[CommunityStore] Lecture des compteurs vidéo impossible: {e}")
            return {}
        counts: dict = {}
        for row in res.data or []:
            uid = (row.get("user_id") or "").strip()
            if uid:
                counts[uid] = counts.get(uid, 0) + 1
        return {uid: counts.get(uid, 0) >= 5 for uid in ids}

    def delete(self, video_id: str, user_id: str = "") -> None:
        meta = self.get_meta(video_id)
        if not meta:
            raise KeyError(video_id)
        owner = (meta.get("user_id") or "").strip()
        if owner and user_id != owner:
            raise PermissionError("Cette vidéo appartient à un autre créateur : seule la suppression par son créateur est autorisée")
        if not owner:
            raise PermissionError("Créateur non identifiable sur cette publication : suppression par API impossible")
        client = _get_client()
        storage_path = meta.get("storage_path") or f"videos/{video_id}.mp4"
        try:
            self._storage().remove([storage_path])
        except Exception as e:
            logger.warning(f"[CommunityStore] Suppression objet storage {storage_path}: {e}")
        client.table("community_comments").delete().eq("video_id", video_id).execute()
        client.table("community_likes").delete().eq("video_id", video_id).execute()
        client.table("community_videos").delete().eq("id", video_id).execute()

    def backfill_thumbnails(self, limit: int = 60, delay: float = 1.5) -> dict:
        """Génère les vignettes manquantes des vidéos déjà publiées.

        Utilisé au démarrage du serveur (tâche de fond) : liste les vidéos
        récentes, extrait la 1ère frame depuis l'URL publique (ffmpeg seek
        rapide, pas de téléchargement complet) et l'upload dans le bucket.
        Non bloquant et borné — s'arrête dès que `limit` vignettes ont été
        créées ou que la liste est épuisée.
        """
        existing = self._list_thumbnail_ids()
        done = 0
        failed = 0
        skipped = 0
        try:
            page = 1
            client = _get_client()
            while done + failed < limit:
                res = (
                    client.table("community_videos")
                    .select("id", "storage_path")
                    .order("published_at", desc=True)
                    .limit(50)
                    .offset((page - 1) * 50)
                    .execute()
                )
                rows = res.data or []
                if not rows:
                    break
                if page > 10:  # garde : ne pas scanner plus de 500 vidéos à chaque boot
                    break
                for row in rows:
                    if done + failed >= limit:
                        break
                    vid = row.get("id") or ""
                    if not vid or vid in existing:
                        skipped += 1
                        continue
                    url = self._public_url(row.get("storage_path") or f"videos/{vid}.mp4")
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                        tmp_path = tmp.name
                    try:
                        if self._extract_frame(url, tmp_path) and self._upload_thumbnail(vid, tmp_path):
                            done += 1
                            logger.info(f"[CommunityStore] Backfill vignette {vid} ({done}/{limit})")
                        else:
                            failed += 1
                    except Exception as e:
                        failed += 1
                        logger.warning(f"[CommunityStore] Backfill {vid} échec: {e}")
                    finally:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    if done + failed < limit:
                        time.sleep(delay)
                page += 1
        except Exception as e:
            logger.warning(f"[CommunityStore] Backfill vignettes interrompu: {e}")
        return {"done": done, "failed": failed, "skipped": skipped}


class _CoalescingWriter:
    """Écrit les métadonnées de tâches en arrière-plan, une seule fois par
    tâche par cycle (les écritures successives sont coalescées), dans l'ordre.
    Les erreurs ne remontent jamais dans le pipeline de génération vidéo."""

    def __init__(self, client):
        self._client = client
        self._pending: dict = {}
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="task-meta-writer", daemon=True
        )
        self._thread.start()

    def submit(self, meta: dict):
        task_id = meta.get("task_id")
        if not task_id:
            return
        with self._lock:
            self._pending[task_id] = meta
        self._event.set()

    def _run(self):
        while True:
            self._event.wait(timeout=0.5)
            self._event.clear()
            with self._lock:
                batch = dict(self._pending)
                self._pending.clear()
            for meta in batch.values():
                try:
                    self._upsert(meta)
                except Exception as e:
                    logger.warning(
                        f"[TaskStore] Écriture métadonnées {meta.get('task_id')} impossible: {e}"
                    )

    def _upsert(self, meta: dict):
        params = meta.get("params") or {}
        self._client.table("tasks").upsert({
            "task_id": meta["task_id"],
            "dir_name": meta.get("dir_name", ""),
            "task_type": meta.get("task_type", ""),
            "creative_name": meta.get("creative_name", ""),
            "user_id": meta.get("user_id", ""),
            "status": meta.get("status", "pending"),
            "prompt": meta.get("prompt", ""),
            "current_message": meta.get("current_message", ""),
            "final_video_file": meta.get("final_video_file", ""),
            "video_backup_url": meta.get("video_backup_url", ""),
            "params": json.dumps(params, ensure_ascii=False),
            "resume_attempts": int(meta.get("resume_attempts", 0) or 0),
            "created_at": meta.get("created_at"),
            "updated_at": meta.get("updated_at", time.time()),
        }, on_conflict="task_id").execute()


class SupabaseTaskStore(TaskStore):
    """Métadonnées de tâches persistées dans Postgres (mode Render)."""

    def __init__(self):
        self._writer = _CoalescingWriter(_get_client())

    def upsert_meta(self, meta: dict) -> None:
        self._writer.submit(meta)

    def get_meta(self, task_id: str) -> Optional[dict]:
        res = (
            _get_client().table("tasks")
            .select("*").eq("task_id", task_id).limit(1).execute()
        )
        rows = res.data or []
        if not rows:
            return None
        return _norm_meta(dict(rows[0]))

    def list_meta(self) -> List[dict]:
        res = (
            _get_client().table("tasks")
            .select("*").order("updated_at", desc=True).execute()
        )
        return [_norm_meta(dict(r)) for r in (res.data or [])]

    def delete_meta(self, task_id: str) -> None:
        try:
            _get_client().table("tasks").delete().eq("task_id", task_id).execute()
        except Exception as e:
            logger.warning(f"[TaskStore] Suppression {task_id} impossible: {e}")

    def mark_interrupted(self, message: str) -> int:
        res = (
            _get_client().table("tasks")
            .update({"status": "failed", "current_message": message})
            .in_("status", ["running", "queued"])
            .execute()
        )
        return len(res.data or [])
