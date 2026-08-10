"""
core/agents/agent_runner.py — Génération et publication d'une vidéo par un persona

Flux :
  1. Prompt ultra réaliste (généré par AgnesChatAPI ou prompt de secours)
  2. AIVideoPipeline (hd, ultra_realistic) — audio original de la vidéo conservé
  3. Publication dans la galerie communautaire avec le nom du persona
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
import uuid
from typing import Optional

from core.agents.personas import AgentPersona, EditorialChoice, pick_editorial
from core.api.agnes_chat import AgnesChatAPI
from core.config import get_working_dir
from core.storage import get_community_store
from core.video import AIVideoPipeline, PipelineConfig, TaskPriority, VideoMonitor, VideoQueue

logger = logging.getLogger(__name__)

# v10.0: le system prompt demande un MINI-FILM dans le genre choisi
# (comédie, horreur, action, SF…) : chaque publication est différente.
SYSTEM_PROMPT_TEMPLATE = """Tu es {author}, un créateur de vidéos français qui publie des mini-films originaux sur les réseaux.
{instruction}
{bio}
{nsfw}
Rédige UN prompt de génération vidéo en FRANÇAIS, détaillé et cinématographique, décrivant une scène de {label} : personnages, situation, action, décor, lumière et mouvement de caméra.
Exigences :
- 1 à 3 phrases, riche en détails visuels (lumière, mouvement de caméra, textures, ambiance)
- photoréaliste, digne d'une caméra professionnelle (slow motion, travelling, éclairage cinéma)
- scène nouvelle et originale à chaque fois, jamais la même, surprenante et spectaculaire
- réponds UNIQUEMENT avec le prompt, sans introduction ni guillemets"""


def _generate_prompt(
    persona: AgentPersona,
    chat: Optional[AgnesChatAPI],
    editorial: EditorialChoice,
) -> str:
    """Génère un prompt « mini-film » pour le persona dans le genre choisi (chat IA + fallback)."""
    if chat is not None:
        try:
            system = SYSTEM_PROMPT_TEMPLATE.format(
                author=persona.author,
                instruction=editorial.instruction,
                label=editorial.label,
                bio=persona.bio,
                nsfw=persona.nsfw_policy,
            )
            prompt = chat.chat(system_prompt=system, user_prompt=editorial.label, max_tokens=300)
            prompt = prompt.strip().strip('"').strip("«").strip("»").strip()
            if len(prompt) >= 40 and " " in prompt:
                logger.info(f"[Agents] {persona.id}: prompt IA généré ({len(prompt)} chars, genre={editorial.label})")
                return prompt
            logger.warning(f"[Agents] {persona.id}: prompt IA trop court, fallback")
        except Exception as e:
            logger.warning(f"[Agents] {persona.id}: chat échoué ({e}), fallback templates")
    # Fallback : rotation aléatoire dans les prompts du genre (ou du thème)
    return random.choice(editorial.prompts)


async def generate_and_publish(
    persona: AgentPersona,
    api_key: str,
    queue: Optional[VideoQueue] = None,
    monitor: Optional[VideoMonitor] = None,
    chat: Optional[AgnesChatAPI] = None,
    task_id: Optional[str] = None,
) -> dict:
    """Génère une vidéo pour le persona et la publie en galerie.

    Args:
        task_id: identifiant de publication. Le scheduler passe le task_id
            DÉTERMINISTE du créneau (`agent_{persona}_{YYYY-MM-DD}_{HH}`) pour
            que l'anti-doublon `find_published` fonctionne : sinon chaque bot
            re-publie en boucle pendant son heure et le feed est rempli d'un
            seul auteur. S'il est None, un identifiant aléatoire est utilisé.

    Returns:
        dict avec video_id, video_url, prompt, ou lève une exception en cas d'échec.
    """
    # v10.0: chaque publication tire un genre différent (comédie, horreur,
    # action…) — les bots ne refont plus jamais « le même type » de vidéo.
    editorial = pick_editorial(persona)
    prompt = await asyncio.to_thread(_generate_prompt, persona, chat, editorial)

    working_dir = os.path.join(get_working_dir(), f"agent_{persona.id}")
    os.makedirs(working_dir, exist_ok=True)

    config = PipelineConfig(
        quality="hd",            # HD (pas Full HD) : les bots restent légers en RAM,
                                 # sinon le postprocess fait OOM le plan Free 512 MB
                                 # et tue les tâches des utilisateurs en file.
        style="ultra_realistic",
        # audio_enabled=True est REQUIS pour que _enhance_audio() tourne.
        # v9.8: native_audio=True → l'audio NATIF d'Agnes Video V2.0 est
        # demandé (paramètre `audio` au submit) et CONSERVÉ s'il est présent :
        # c'est le « son réel » de la scène (comme Sora 2). Si le modèle
        # renvoie une vidéo muette, ambiance_sound=True (fallback) synthétise
        # le paysage sonore du prompt (vagues, pluie, forêt, ville…).
        # Plus de musique : l'utilisateur veut le son de l'environnement filmé.
        audio_enabled=True,
        native_audio=True,
        ambiance_sound=True,
        background_music=False,
        audio_voice=persona.voice,
        # v9.8: les bots publient avec le SON NATIF du modèle Agnes (audio
        # synchronisé de la vidéo) ou, à défaut, le paysage sonore procédural
        # du prompt — jamais de musique ni de voix de robot.
        # (commentaire v9.8 conservé)
        # Postprocess allégé : sans filtre, enhance() copie la vidéo sans ffmpeg
        # → beaucoup moins de mémoire, zéro OOM, génération plus rapide.
        denoise=False,
        face_enhance=False,
        motion_enhance=False,
        hdr=False,
        color_correct=False,
        compress=False,
        # Priorité BOT (la plus basse) : les utilisateurs passent toujours avant.
        priority=TaskPriority.BOT,
        max_concurrent=1,
        generation_timeout=900,   # 15 min max : ne pas bloquer la file des vrais utilisateurs
        postprocess_timeout=300,  # 5 min max de post-traitement
        poll_interval=15,         # polling lent : préserve le rate limiter global partagé
                                  # avec les tâches des utilisateurs (429 observés à 3 s)
    )

    pipeline = AIVideoPipeline(
        api_key=api_key,
        config=config,
        queue=queue,
        monitor=monitor,
    )

    # v9.3: qualité réduite imposée aux bots (1280x720, 10 s max) : les
    # générations 1080p/15 s font OOM le plan Free 512 Mo (cascade de
    # "Ran out of memory" qui tue aussi les tâches des utilisateurs en file).
    bot_width, bot_height, bot_duration = 1280, 720, min(persona.duration, 10)
    logger.info(f"[Agents] {persona.author} génère ({editorial.label}, {bot_width}x{bot_height}/{bot_duration}s): {prompt[:100]}…")
    result = await pipeline.generate(
        prompt=prompt,
        duration=bot_duration,
        width=bot_width,
        height=bot_height,
        working_dir=working_dir,
    )
    if not result.video_path or not os.path.exists(result.video_path):
        raise RuntimeError(f"[Agents] {persona.id}: fichier vidéo absent ({result.video_path})")

    # Publication dans la galerie avec le vrai nom du persona.
    # v9.5: le task_id est fourni par le scheduler (déterministe par créneau)
    # pour que l'anti-doublon fonctionne; sinon uuid aléatoire (appels manuels).
    task_id = task_id or f"agent_{persona.id}_{uuid.uuid4().hex[:8]}"
    resolution = f"{bot_width}x{bot_height}"
    published = get_community_store().publish(
        task_id=task_id,
        author=persona.author,
        prompt=prompt,
        duration=float(result.duration or bot_duration),
        resolution=resolution,
        video_path=result.video_path,
        user_id=persona.user_id,
        genre=editorial.label,
    )
    logger.info(
        f"[Agents] {persona.author} publié: {published.get('video_id')} "
        f"(storage=communauté, duration={result.duration or bot_duration}s)"
    )
    return {
        "video_id": published.get("video_id"),
        "video_url": published.get("video_url"),
        "prompt": prompt,
        "published_at": time.time(),
    }
