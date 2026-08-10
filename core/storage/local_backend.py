"""
core/storage/local_backend.py — Backend de stockage local (système de fichiers)

Reprend exactement le comportement historique de server.py (dossier community/
avec index.json + fichiers .mp4). Utilisé uniquement en développement local,
quand les variables d'environnement Supabase ne sont pas configurées.

⚠️ Sur Render, ce backend est VOLATILE : le disque est éphémère et tout est
perdu à chaque redéploiement. C'est pourquoi le backend Supabase existe.
"""

import json
import logging
import os
import shutil
import time
from typing import List, Optional

from core.config import get_working_dir

from .base import CommunityStore, TaskStore

logger = logging.getLogger(__name__)


class LocalCommunityStore(CommunityStore):
    """Galerie communautaire sur système de fichiers (comportement historique)."""

    def _get_community_dir(self) -> str:
        d = os.path.join(get_working_dir(), "community")
        os.makedirs(d, exist_ok=True)
        return d

    def _load_index(self) -> dict:
        path = os.path.join(self._get_community_dir(), "index.json")
        if not os.path.exists(path):
            return {"videos": {}}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[CommunityStore] index.json illisible: {e}")
            return {"videos": {}}

    def _save_index(self, index: dict) -> None:
        path = os.path.join(self._get_community_dir(), "index.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def publish(self, task_id, author, prompt, duration, resolution, video_path,
                user_id: str = "", genre: str = "") -> dict:
        import uuid

        video_id = uuid.uuid4().hex[:12]
        dest = os.path.join(self._get_community_dir(), f"{video_id}.mp4")
        shutil.copy2(video_path, dest)
        index = self._load_index()
        index.setdefault("videos", {})[video_id] = {
            "task_id": task_id,
            "author": author or "Anonyme",
            "prompt": prompt,
            "duration": duration,
            "resolution": resolution,
            "published_at": time.time(),
            "user_id": user_id or "",
            "genre": genre or "",
            "likes": [],
            "comments": [],
        }
        self._save_index(index)
        logger.info(f"[CommunityStore] Published {video_id} (local fs)")
        return {"video_id": video_id, "video_url": f"/api/community/videos/{video_id}/video"}

    def list_videos(self, page=1, per_page=20) -> dict:
        index = self._load_index()
        profiles = self._load_profiles()
        verified = self._verified_by_user()
        videos = []
        for vid, meta in (index.get("videos") or {}).items():
            uid = meta.get("user_id", "")
            avatar_url = ""
            if uid and (profiles.get(uid) or {}).get("avatar_path"):
                avatar_url = f"/api/community/profiles/{uid}/avatar"
            videos.append({
                "id": vid,
                "title": meta["prompt"][:80] if meta.get("prompt") else "Untitled",
                "author": meta.get("author", "Anonyme"),
                "prompt": meta.get("prompt", ""),
                "duration": meta.get("duration", 0),
                "resolution": meta.get("resolution", ""),
                "published_at": meta.get("published_at", 0),
                "user_id": uid,
                "genre": meta.get("genre", ""),
                "avatar_url": avatar_url,
                "author_verified": bool(verified.get(uid, False)),
                "likes": len(meta.get("likes", [])),
                "comments_count": len(meta.get("comments", [])),
                "video_url": f"/api/community/videos/{vid}/video",
                "thumbnail": f"/api/community/videos/{vid}/video",
            })
        videos.sort(key=lambda v: v["published_at"], reverse=True)
        start = (page - 1) * per_page
        end = start + per_page
        return {"videos": videos[start:end], "total": len(videos)}

    def get_meta(self, video_id: str) -> Optional[dict]:
        index = self._load_index()
        return index.get("videos", {}).get(video_id)

    def toggle_like(self, video_id: str, visitor_hash: str) -> dict:
        index = self._load_index()
        videos = index.get("videos", {})
        if video_id not in videos:
            raise KeyError(video_id)
        likes = videos[video_id].setdefault("likes", [])
        already_liked = visitor_hash in likes
        if already_liked:
            likes.remove(visitor_hash)
        else:
            likes.append(visitor_hash)
        self._save_index(index)
        return {"ok": True, "likes": len(likes), "liked": not already_liked}

    def is_liked(self, video_id: str, visitor_hash: str) -> bool:
        """True si `visitor_hash` a déjà liké la vidéo (lecture seule)."""
        index = self._load_index()
        videos = index.get("videos", {})
        if video_id not in videos:
            raise KeyError(video_id)
        return visitor_hash in videos[video_id].get("likes", [])

    def get_comments(self, video_id: str) -> List[dict]:
        index = self._load_index()
        videos = index.get("videos", {})
        if video_id not in videos:
            raise KeyError(video_id)
        return list(videos[video_id].get("comments", []))

    def add_comment(self, video_id: str, author: str, text: str) -> dict:
        import uuid

        index = self._load_index()
        videos = index.get("videos", {})
        if video_id not in videos:
            raise KeyError(video_id)
        comment = {
            "id": uuid.uuid4().hex[:8],
            "author": author or "Anonyme",
            "text": text,
            "created_at": time.time(),
        }
        videos[video_id].setdefault("comments", []).append(comment)
        self._save_index(index)
        return {"ok": True, "comment": comment, "comments_count": len(videos[video_id]["comments"])}

    def get_video(self, video_id: str) -> Optional[str]:
        video_path = os.path.join(self._get_community_dir(), f"{video_id}.mp4")
        if not os.path.exists(video_path):
            return None
        return video_path

    def find_published(self, task_id: str) -> Optional[dict]:
        index = self._load_index()
        for vid, meta in (index.get("videos") or {}).items():
            if meta.get("task_id") != task_id:
                continue
            video_path = os.path.join(self._get_community_dir(), f"{vid}.mp4")
            if not os.path.exists(video_path):
                return None
            return {
                "video_id": vid,
                "video_url": f"/api/community/videos/{vid}/video",
                "video_target": video_path,
            }
        return None

    # ── Profils utilisateurs (façon TikTok/Instagram) ─────────────────────

    def _profiles_file(self) -> str:
        return os.path.join(self._get_community_dir(), "profiles.json")

    def _load_profiles(self) -> dict:
        path = self._profiles_file()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[CommunityStore] profiles.json illisible: {e}")
            return {}

    def _save_profiles(self, profiles: dict) -> None:
        path = self._profiles_file()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(profiles, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def get_profile(self, user_id: str) -> Optional[dict]:
        if not user_id:
            return None
        p = self._load_profiles().get(user_id)
        if not p:
            return None
        avatar_url = ""
        if p.get("avatar_path") and os.path.exists(p["avatar_path"]):
            avatar_url = f"/api/community/profiles/{user_id}/avatar"
        return {
            "user_id": user_id,
            "pseudo": p.get("pseudo", ""),
            "bio": p.get("bio", ""),
            "avatar_url": avatar_url,
            "created_at": p.get("created_at", 0),
            "updated_at": p.get("updated_at", 0),
        }

    def save_profile(
        self,
        user_id: str,
        pseudo: str = "",
        bio: str = "",
        avatar_bytes: Optional[bytes] = None,
        avatar_content_type: str = "",
    ) -> dict:
        profiles = self._load_profiles()
        existing = profiles.get(user_id) or {}
        now = time.time()
        avatar_path = ""
        if avatar_bytes:
            ext = {"image/jpeg": "jpg", "image/webp": "webp",
                   "image/gif": "gif"}.get(avatar_content_type or "", "png")
            avatar_path = os.path.join(self._get_community_dir(), f"avatar_{user_id}.{ext}")
            with open(avatar_path, "wb") as f:
                f.write(avatar_bytes)
            old = existing.get("avatar_path") or ""
            if old and os.path.abspath(old) != os.path.abspath(avatar_path) and os.path.exists(old):
                try:
                    os.remove(old)
                except OSError:
                    pass
        profiles[user_id] = {
            "pseudo": (pseudo or "").strip()[:30],
            "bio": (bio or "").strip()[:160],
            "avatar_path": avatar_path or existing.get("avatar_path", ""),
            "created_at": existing.get("created_at", now),
            "updated_at": now,
        }
        self._save_profiles(profiles)
        return self.get_profile(user_id)

    def get_user_videos(self, user_id: str, page: int = 1, per_page: int = 50) -> dict:
        index = self._load_index()
        profiles = self._load_profiles()
        verified = self._verified_by_user()
        videos = []
        for vid, meta in (index.get("videos") or {}).items():
            if (meta.get("user_id") or "") != user_id:
                continue
            avatar_url = ""
            if (profiles.get(user_id) or {}).get("avatar_path"):
                avatar_url = f"/api/community/profiles/{user_id}/avatar"
            videos.append({
                "id": vid,
                "title": meta["prompt"][:80] if meta.get("prompt") else "Untitled",
                "author": meta.get("author", "Anonyme"),
                "prompt": meta.get("prompt", ""),
                "duration": meta.get("duration", 0),
                "resolution": meta.get("resolution", ""),
                "published_at": meta.get("published_at", 0),
                "user_id": user_id,
                "avatar_url": avatar_url,
                "author_verified": bool(verified.get(user_id, False)),
                "likes": len(meta.get("likes", [])),
                "comments_count": len(meta.get("comments", [])),
                "video_url": f"/api/community/videos/{vid}/video",
                "thumbnail": f"/api/community/videos/{vid}/video",
            })
        videos.sort(key=lambda v: v["published_at"], reverse=True)
        start = (page - 1) * per_page
        end = start + per_page
        return {"videos": videos[start:end], "total": len(videos)}

    def get_avatar_path(self, user_id: str) -> Optional[str]:
        p = self._load_profiles().get(user_id)
        path = (p or {}).get("avatar_path") or ""
        if path and os.path.exists(path):
            return path
        return None

    # ── Abonnements (follow) ─────────────────────────────────────────────

    def _follows_file(self) -> str:
        return os.path.join(self._get_community_dir(), "follows.json")

    def _load_follows(self) -> dict:
        """{"follower_id|followed_id": created_at}"""
        path = self._follows_file()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[CommunityStore] follows.json illisible: {e}")
            return {}

    def _save_follows(self, data: dict) -> None:
        path = self._follows_file()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def follow_user(self, follower_id: str, followed_id: str) -> dict:
        if not follower_id or not followed_id or follower_id == followed_id:
            return {"following": False,
                    "follower_count": self.get_follower_count(followed_id)}
        data = self._load_follows()
        data[f"{follower_id}|{followed_id}"] = time.time()
        self._save_follows(data)
        return {"following": True,
                "follower_count": self.get_follower_count(followed_id)}

    def unfollow_user(self, follower_id: str, followed_id: str) -> dict:
        if not follower_id or not followed_id:
            return {"following": False,
                    "follower_count": self.get_follower_count(followed_id)}
        data = self._load_follows()
        data.pop(f"{follower_id}|{followed_id}", None)
        self._save_follows(data)
        return {"following": False,
                "follower_count": self.get_follower_count(followed_id)}

    def is_following(self, follower_id: str, followed_id: str) -> bool:
        if not follower_id or not followed_id:
            return False
        return f"{follower_id}|{followed_id}" in self._load_follows()

    def get_follower_count(self, user_id: str) -> int:
        if not user_id:
            return 0
        suffix = "|" + user_id
        return sum(1 for k in self._load_follows() if k.endswith(suffix))

    def get_following_count(self, user_id: str) -> int:
        if not user_id:
            return 0
        prefix = user_id + "|"
        return sum(1 for k in self._load_follows() if k.startswith(prefix))

    # ── Certification (badge bleu à partir de 5 vidéos publiées) ─────────

    def _verified_by_user(self) -> dict:
        """user_id → True si l'utilisateur a publié ≥ 5 vidéos."""
        counts: dict = {}
        for meta in (self._load_index().get("videos") or {}).values():
            uid = (meta.get("user_id") or "").strip()
            if uid:
                counts[uid] = counts.get(uid, 0) + 1
        return {uid: c >= 5 for uid, c in counts.items()}

    def delete(self, video_id: str, user_id: str = "") -> None:
        index = self._load_index()
        videos = index.get("videos", {})
        if video_id not in videos:
            raise KeyError(video_id)
        owner = (videos[video_id].get("user_id") or "").strip()
        if owner and user_id != owner:
            raise PermissionError("Cette vidéo appartient à un autre créateur : seule la suppression par son créateur est autorisée")
        if not owner:
            raise PermissionError("Créateur non identifiable sur cette publication : suppression par API impossible")
        video_path = os.path.join(self._get_community_dir(), f"{video_id}.mp4")
        if os.path.exists(video_path):
            os.remove(video_path)
        del videos[video_id]
        self._save_index(index)


class LocalTaskStore(TaskStore):
    """Les métadonnées de tâches sont déjà sur le disque local : backend no-op."""

    def upsert_meta(self, meta: dict) -> None:
        pass

    def get_meta(self, task_id: str) -> Optional[dict]:
        return None

    def list_meta(self) -> List[dict]:
        return []

    def delete_meta(self, task_id: str) -> None:
        pass

    def mark_interrupted(self, message: str) -> int:
        return 0
