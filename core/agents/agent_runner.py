"""
core/agents/agent_runner.py — Génération et publication d'une vidéo par un persona

Flux :
  1. Prompt ultra réaliste (généré par AgnesChatAPI ou prompt de secours)
  2. AIVideoPipeline (full_hd, ultra_realistic, audio français)
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

from core.agents.personas import AgentPersona, fallback_prompts
from core.api.agnes_chat import AgnesChatAPI
from core.config import get_working_dir
from core.storage import get_community_store
from core.video import AIVideoPipeline, PipelineConfig, TaskPriority, VideoMonitor, VideoQueue

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """Tu es {author}, un créateur de vidéos français spécialisé dans {theme}.
{bio}
{nsfw}
Rédige UN prompt de génération vidéo en FRANÇAIS, détaillé et cinématographique,
décrivant une scène ultra réaliste sur le thème « {theme} ».
Exigences :
- 1 à 3 phrases, riche en détails visuels (lumière, mouvement de caméra, textures, ambiance)
- photoréaliste, digne d'une caméra professionnelle (slow motion, travelling, éclairage cinéma)
- scène nouvelle et originale à chaque fois, jamais la même
- réponds UNIQUEMENT avec le prompt, sans introduction ni guillemets"""


def _generate_prompt(persona: AgentPersona, chat: Optional[AgnesChatAPI]) -> str:
    """Génère un prompt ultra réaliste pour le persona (chat IA + fallback)."""
    if chat is not None:
        try:
            system = SYSTEM_PROMPT_TEMPLATE.format(
                author=persona.author,
                theme=persona.theme,
                bio=persona.bio,
                nsfw=persona.nsfw_policy,
            )
            prompt = chat.chat(system_prompt=system, user_prompt=persona.theme, max_tokens=300)
            prompt = prompt.strip().strip('"').strip("«").strip("»").strip()
            if len(prompt) >= 40 and " " in prompt:
                logger.info(f"[Agents] {persona.id}: prompt IA généré ({len(prompt)} chars)")
                return prompt
            logger.warning(f"[Agents] {persona.id}: prompt IA trop court, fallback")
        except Exception as e:
            logger.warning(f"[Agents] {persona.id}: chat échoué ({e}), fallback templates")
    # Fallback : rotation aléatoire dans les templates du thème
    templates = fallback_prompts(persona)
    return random.choice(templates)


async def generate_and_publish(
    persona: AgentPersona,
    api_key: str,
    queue: Optional[VideoQueue] = None,
    monitor: Optional[VideoMonitor] = None,
    chat: Optional[AgnesChatAPI] = None,
) -> dict:
    """Génère une vidéo pour le persona et la publie en galerie.

    Returns:
        dict avec video_id, video_url, prompt, ou lève une exception en cas d'échec.
    """
    prompt = await asyncio.to_thread(_generate_prompt, persona, chat)

    working_dir = os.path.join(get_working_dir(), f"agent_{persona.id}")
    os.makedirs(working_dir, exist_ok=True)

    config = PipelineConfig(
        quality="full_hd",
        style="ultra_realistic",
        audio_enabled=True,
        audio_voice=persona.voice,
        priority=TaskPriority.FREE,
        max_concurrent=1,
    )

    pipeline = AIVideoPipeline(
        api_key=api_key,
        config=config,
        queue=queue,
        monitor=monitor,
    )

    logger.info(f"[Agents] {persona.author} génère: {prompt[:100]}…")
    result = await pipeline.generate(
        prompt=prompt,
        duration=persona.duration,
        width=persona.width,
        height=persona.height,
        working_dir=working_dir,
    )
    if not result.video_path or not os.path.exists(result.video_path):
        raise RuntimeError(f"[Agents] {persona.id}: fichier vidéo absent ({result.video_path})")

    # Publication dans la galerie avec le vrai nom du persona
    task_id = f"agent_{persona.id}_{uuid.uuid4().hex[:8]}"
    resolution = f"{persona.width}x{persona.height}"
    published = get_community_store().publish(
        task_id=task_id,
        author=persona.author,
        prompt=prompt,
        duration=float(result.duration or persona.duration),
        resolution=resolution,
        video_path=result.video_path,
        user_id=persona.user_id,
    )
    logger.info(
        f"[Agents] {persona.author} publié: {published.get('video_id')} "
        f"(storage=communauté, duration={result.duration or persona.duration}s)"
    )
    return {
        "video_id": published.get("video_id"),
        "video_url": published.get("video_url"),
        "prompt": prompt,
        "published_at": time.time(),
    }
