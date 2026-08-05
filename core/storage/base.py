"""
core/storage/base.py — Interfaces de stockage persistant (galerie communautaire + métadonnées de tâches)

Deux backends implémentent ces interfaces :
- LocalCommunityStore / LocalTaskStore   → système de fichiers (mode développement, comportement historique)
- SupabaseCommunityStore / SupabaseTaskStore → Supabase (Stockage + Postgres, mode production Render)

Le contrat des réponses est volontairement identique à l'ancien code, afin que le
frontend (static/index.html / docs/index.html) continue de fonctionner sans changement
de format (seule la valeur de `video_url` peut devenir une URL publique directe).
"""

from abc import ABC, abstractmethod
from typing import List, Optional


class CommunityStore(ABC):
    """Stockage des vidéos publiées dans la galerie communautaire."""

    @abstractmethod
    def publish(
        self,
        task_id: str,
        author: str,
        prompt: str,
        duration: float,
        resolution: str,
        video_path: str,
        user_id: str = "",
    ) -> dict:
        """Publie une vidéo (upload du fichier + enregistrement des métadonnées).

        user_id : identifiant opaque du créateur ('' pour les publications
        héritées). Sert à réserver la suppression au créateur.

        Returns:
            {"video_id": str, "video_url": str}
        """

    @abstractmethod
    def list_videos(self, page: int = 1, per_page: int = 20) -> dict:
        """Liste les vidéos publiées (les plus récentes d'abord).

        Returns:
            {"videos": [dict], "total": int} — chaque dict contient
            id/title/author/prompt/duration/resolution/published_at/likes/comments_count/video_url/thumbnail
        """

    @abstractmethod
    def get_meta(self, video_id: str) -> Optional[dict]:
        """Retourne les métadonnées d'une vidéo, ou None si inconnue."""

    @abstractmethod
    def toggle_like(self, video_id: str, visitor_hash: str) -> dict:
        """Bascule le like d'un visiteur (identifié par hash).

        Returns:
            {"ok": True, "likes": int, "liked": bool}
        """

    @abstractmethod
    def get_comments(self, video_id: str) -> List[dict]:
        """Retourne les commentaires d'une vidéo (ordre chronologique)."""

    @abstractmethod
    def add_comment(self, video_id: str, author: str, text: str) -> dict:
        """Ajoute un commentaire.

        Returns:
            {"ok": True, "comment": dict, "comments_count": int}
        """

    @abstractmethod
    def get_video(self, video_id: str) -> Optional[str]:
        """Retourne l'URL publique (mode distant) ou le chemin local (mode local)
        du fichier vidéo, ou None si introuvable."""

    @abstractmethod
    def find_published(self, task_id: str) -> Optional[dict]:
        """Retourne la publication la plus récente d'une tâche, ou None.

        Permet de récupérer la vidéo publiée en galerie quand le fichier local
        de la tâche a disparu (système de fichiers éphémère après redéploiement).

        Returns:
            {"video_id": str, "video_url": str, "video_target": str} —
            video_target est l'URL publique (mode distant) ou le chemin local (mode local).
        """

    @abstractmethod
    def delete(self, video_id: str, user_id: str = "") -> None:
        """Supprime la vidéo (fichier + métadonnées + likes + commentaires).

        Seul le créateur de la publication (user_id) peut la supprimer :
        lève PermissionError si l'appelant n'est pas le propriétaire, ou si
        la publication n'a pas de user_id enregistré (créateur non vérifiable).
        """

    def save_task_video_backup(self, task_id: str, video_path: str) -> Optional[str]:
        """Sauvegarde la vidéo finale d'une tâche (copie privée de secours).

        Capacité optionnelle (le backend local est un no-op : le fichier est
        déjà sur le disque persistant). Retourne l'URL publique de la
        sauvegarde, ou None si non disponible / en échec.
        """
        return None

    # ── Profils utilisateurs (façon TikTok/Instagram) ────────────────────
    # Méthodes concrètes (non abstraites) pour préserver la rétrocompatibilité :
    # un backend qui ne les implémente pas retombe sur le comportement "sans
    # profil" (pseudo dérivé des publications, aucun avatar, aucune persistance).

    def get_profile(self, user_id: str) -> Optional[dict]:
        """Retourne le profil enregistré d'un utilisateur, ou None.

        Returns:
            {"user_id", "pseudo", "bio", "avatar_url", "created_at", "updated_at"}
        """
        return None

    def save_profile(
        self,
        user_id: str,
        pseudo: str = "",
        bio: str = "",
        avatar_bytes: Optional[bytes] = None,
        avatar_content_type: str = "",
    ) -> dict:
        """Crée ou met à jour le profil d'un utilisateur (upsert).

        avatar_bytes : si fourni, uploadé comme photo de profil (le chemin
        stocké devient `avatars/{user_id}.{ext}`). Returns : profil à jour
        (même format que get_profile).
        """
        return {
            "user_id": user_id,
            "pseudo": pseudo,
            "bio": bio,
            "avatar_url": "",
            "created_at": 0,
            "updated_at": 0,
        }

    def get_user_videos(self, user_id: str, page: int = 1, per_page: int = 50) -> dict:
        """Liste les vidéos publiées par un utilisateur (les plus récentes d'abord).

        Returns:
            {"videos": [dict], "total": int} — mêmes champs que list_videos.
        """
        return {"videos": [], "total": 0}

    def get_avatar_path(self, user_id: str) -> Optional[str]:
        """Chemin/URL de l'avatar d'un utilisateur (pour l'endpoint de service).

        Retourne une URL publique (mode distant) ou un chemin local (mode
        local), ou None si l'utilisateur n'a pas d'avatar.
        """
        return None

    # ── Abonnements (follow) ─────────────────────────────────────────────
    # Méthodes concrètes (non abstraites) pour préserver la rétrocompatibilité :
    # un backend qui ne les implémente pas retombe sur un comportement neutre
    # (jamais abonné, compteurs à zéro, abonnement non persisté).

    def follow_user(self, follower_id: str, followed_id: str) -> dict:
        """Abonne `follower_id` à `followed_id` (idempotent).

        Returns:
            {"following": bool, "follower_count": int}
        """
        return {"following": True, "follower_count": 0}

    def unfollow_user(self, follower_id: str, followed_id: str) -> dict:
        """Désabonne `follower_id` de `followed_id` (idempotent).

        Returns:
            {"following": bool, "follower_count": int}
        """
        return {"following": False, "follower_count": 0}

    def is_following(self, follower_id: str, followed_id: str) -> bool:
        """True si `follower_id` est abonné à `followed_id`."""
        return False

    def get_follower_count(self, user_id: str) -> int:
        """Nombre d'abonnés de `user_id`."""
        return 0

    def get_following_count(self, user_id: str) -> int:
        """Nombre de profils suivis par `user_id`."""
        return 0


class TaskStore(ABC):
    """Persistance des métadonnées de tâches (survit aux redéploiements)."""

    @abstractmethod
    def upsert_meta(self, meta: dict) -> None:
        """Écrit (ou met à jour) les métadonnées d'une tâche de façon asynchrone."""

    @abstractmethod
    def get_meta(self, task_id: str) -> Optional[dict]:
        """Retourne les métadonnées persistées d'une tâche, ou None."""

    @abstractmethod
    def list_meta(self) -> List[dict]:
        """Retourne toutes les métadonnées de tâches persistées."""

    @abstractmethod
    def delete_meta(self, task_id: str) -> None:
        """Supprime les métadonnées persistées d'une tâche."""

    @abstractmethod
    def mark_interrupted(self, message: str) -> int:
        """Marque les tâches running/queued comme interrompues après un redémarrage.

        Returns:
            Nombre de tâches mises à jour.
        """
