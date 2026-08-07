"""
core/agents/avatars.py — Photos de profil IA pour les créateurs bots

À l'arrivée sur le flux Vibes, chaque persona doit ressembler à un vrai
utilisateur de réseau social : un nom, une bio… et une photo de profil.

Ce module génère le portrait de chaque persona (Agnes Image t2i, gratuite,
limitée par le rate limiter global partagé) puis l'enregistre via
`CommunityStore.save_profile` — exactement le même chemin que les avatars
uploadés par les utilisateurs :
  - backend local : `avatar_{user_id}.{ext}` dans le répertoire communauté
  - backend Supabase : upload dans le bucket + colonne `avatar_path`

Idempotent : un persona qui a déjà un avatar est ignoré. Ne lève jamais
(log uniquement) pour ne pas perturber le démarrage du serveur.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Optional, Tuple

from core.agents.personas import AGENT_PERSONAS
from core.api.agnes_image import AgnesImageAPI, ImageOutput
from core.storage import get_community_store

logger = logging.getLogger(__name__)

_AVATAR_SIZE = "512x512"  # petit portrait : léger en RAM, upload rapide


def _avatar_bytes_and_type(img: ImageOutput) -> Tuple[bytes, str]:
    """Extrait les bytes + content-type d'une ImageOutput (url ou base64)."""
    ext = (img.ext or "png").lstrip(".").lower()
    if ext in ("jpg", "jpeg"):
        ext = "jpg"
        content_type = "image/jpeg"
    else:
        ext = "png"
        content_type = "image/png"
    fd, path = tempfile.mkstemp(suffix=f".{ext}")
    try:
        img.save(path)  # gère les deux formats (download si url)
        with open(path, "rb") as f:
            return f.read(), content_type
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.remove(path)
        except OSError:
            pass


async def ensure_agent_avatars(api_key: str, delay: float = 8.0) -> None:
    """Génère les photos de profil manquantes des 8 personas.

    Séquentiel (le rate limiter global est partagé avec les tâches des
    utilisateurs) ; idempotent ; ne lève jamais.

    Args:
        api_key: clé Agnes pour l'API image.
        delay: secondes d'attente avant de commencer (laisse le boot respirer).
    """
    if not api_key:
        return
    image_api = AgnesImageAPI(api_key=api_key)
    store = get_community_store()
    if delay:
        await asyncio.sleep(delay)
    for persona in AGENT_PERSONAS:
        try:
            profile = await asyncio.to_thread(store.get_profile, persona.user_id)
            if profile and profile.get("avatar_url"):
                logger.info(
                    f"[Agents.Avatars] {persona.author}: avatar déjà présent, ignoré"
                )
                continue
            prompt = persona.avatar_prompt or (
                f"Photo de profil TikTok ultra réaliste d'un créateur français "
                f"de contenus sur {persona.theme}, sourire naturel, selfie vlog, "
                f"lumière douce et flatteuse, photoréaliste, haute qualité"
            )
            logger.info(f"[Agents.Avatars] Génération de l'avatar de {persona.author}…")
            img = await image_api.generate_single_image(prompt, size=_AVATAR_SIZE)
            data, content_type = _avatar_bytes_and_type(img)
            await asyncio.to_thread(
                store.save_profile,
                persona.user_id,
                persona.author,
                persona.bio,
                data,
                content_type,
            )
            logger.info(
                f"[Agents.Avatars] {persona.author}: avatar enregistré "
                f"({len(data)} octets, {content_type})"
            )
        except Exception as e:
            logger.warning(f"[Agents.Avatars] {persona.author}: échec avatar ({e})")
