"""
core/video/pipeline.py — Pipeline IA complet de génération vidéo (v8.0)

Orchestration complète du pipeline de génération :
  Prompt → Analyse IA → Optimisation → Génération → Upscaling →
  Amélioration visage → Amélioration mouvement → Audio → Compression → Livraison

Intègre :
  - PromptOptimizer (optimisation IA des prompts)
  - AgnesVideoAPI (génération vidéo)
  - VideoPostProcessor (upscaling, débruitage, HDR)
  - VideoQueue (file d'attente avec priorités)
  - VideoMonitor (monitoring et métriques)

Conçu pour être **rétro-compatible** : peut être utilisé comme wrapper autour
du pipeline existant (SimpleVideoPipeline) ou comme pipeline autonome.

Usage::

    from core.video.pipeline import AIVideoPipeline

    pipeline = AIVideoPipeline(api_key="...", quality="4k", style="cinema")
    result = await pipeline.generate(
        prompt="un enfant qui joue dans un jardin",
        duration=10,
        audio_enabled=True,
    )
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.api.agnes_video import AgnesVideoAPI
from core.cache.redis_cache import get_cache
from core.video.postprocess import (
    VideoPostProcessor,
    PostProcessConfig,
    VIDEO_STYLES,
    ensure_video_duration,
)
from core.video.prompt_optimizer import PromptOptimizer
from core.video.queue import VideoQueue, TaskPriority
from core.video.monitoring import VideoMonitor

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration du pipeline IA complet."""

    # Qualité vidéo
    quality: str = "full_hd"  # standard | hd | full_hd | 2k | 4k
    style: str = "ultra_realistic"  # ultra_realistic | cinema | anime | photorealistic | hyper_realistic

    # Post-traitement
    denoise: bool = True
    face_enhance: bool = True
    motion_enhance: bool = False
    hdr: bool = False
    color_correct: bool = True
    compress: bool = True
    # v8.4: plafond de largeur du postprocess (0 = illimité). Sur le plan Free
    # 512 Mo, on passe la largeur demandée pour ne JAMAIS upscaler au-delà de
    # la source (l'upscaling full_hd/2k/4k + preset medium faisait OOM).
    max_width: int = 0

    # Audio
    audio_enabled: bool = True
    audio_voice: str = "fr-FR-DeniseNeural"
    audio_rate: str = "+0%"

    # File d'attente
    priority: TaskPriority = TaskPriority.FREE
    max_concurrent: int = 2

    # Polling API Agnes : les bots ralentissent l'intervalle (15 s) pour ne pas
    # saturer le rate limiter global partagé avec les tâches utilisateur.
    poll_interval: float = 3.0

    # Optimisation prompt
    optimize_prompt: bool = True
    fix_spelling: bool = True
    add_cinematic: bool = True

    # Timeout
    generation_timeout: int = 1800  # 30 minutes
    postprocess_timeout: int = 600   # 10 minutes


@dataclass
class GenerationResult:
    """Résultat de la génération vidéo."""

    video_path: str
    video_url: str = ""
    duration: float = 0.0
    resolution: str = ""
    quality: str = ""
    style: str = ""
    metrics: dict = field(default_factory=dict)
    stages: dict = field(default_factory=dict)


class AIVideoPipeline:
    """Pipeline IA complet de génération vidéo.

    Orchestre l'ensemble des étapes : optimisation du prompt, génération,
    post-traitement, amélioration audio, compression et livraison.
    """

    def __init__(
        self,
        api_key: str,
        config: Optional[PipelineConfig] = None,
        queue: Optional[VideoQueue] = None,
        monitor: Optional[VideoMonitor] = None,
        on_progress: Optional[Callable[[str, str, float], None]] = None,
    ):
        self.api_key = api_key
        self.config = config or PipelineConfig()
        self.queue = queue or VideoQueue(max_concurrent=self.config.max_concurrent)
        self.monitor = monitor or VideoMonitor()
        self.cache = get_cache()
        # Callback de progression (step_key, message, progress 0..1) :
        # utilisé par le endpoint /api/tasks/advanced pour publier l'avancement
        # dans le task_state (sinon l'UI reste bloquée sur « Initialisation... »).
        self.on_progress = on_progress

        # Initialiser les composants
        self.video_api = AgnesVideoAPI(
            api_key=api_key,
            on_retry=self._on_retry,
            poll_interval=self.config.poll_interval,
        )
        self.postprocessor = VideoPostProcessor(
            config=PostProcessConfig(
                quality=self.config.quality,
                style=self.config.style,
                denoise=self.config.denoise,
                face_enhance=self.config.face_enhance,
                motion_enhance=self.config.motion_enhance,
                hdr=self.config.hdr,
                color_correct=self.config.color_correct,
                compress=self.config.compress,
                max_width=self.config.max_width,
            )
        )
        self.prompt_optimizer = PromptOptimizer(
            style=self.config.style,
            enhance=self.config.optimize_prompt,
            fix_spelling=self.config.fix_spelling,
            add_cinematic=self.config.add_cinematic,
        )

    async def _on_retry(self, attempt: int, delay: float, reason: str) -> None:
        """Callback de retry pour l'API Agnes."""
        logger.warning(
            f"[AIVideoPipeline] Retry {attempt} in {delay:.0f}s: {reason}"
        )

    async def _emit_progress(self, step: str, message: str, progress: float) -> None:
        """Publie la progression via le callback on_progress (si fourni)."""
        if not self.on_progress:
            return
        try:
            result = self.on_progress(step, message, progress)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.warning(f"[AIVideoPipeline] Progress callback error: {e}")

    async def generate(
        self,
        prompt: str,
        duration: int = 5,
        width: int = 1152,
        height: int = 768,
        reference_image_paths: Optional[list] = None,
        seed: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        working_dir: str = "",
    ) -> GenerationResult:
        """Génère une vidéo complète avec le pipeline IA.

        Args:
            prompt: Prompt utilisateur.
            duration: Durée souhaitée (5, 7, 10, 12, 15 secondes).
            width: Largeur cible.
            height: Hauteur cible.
            reference_image_paths: Images de référence (i2v/keyframes).
            seed: Graine aléatoire.
            negative_prompt: Prompt négatif.
            working_dir: Répertoire de travail.

        Returns:
            GenerationResult avec le chemin de la vidéo finale.
        """
        task_id = f"ai_{int(time.time())}_{hash(prompt) % 10000}"
        self.monitor.create_task(task_id)

        stages = {}
        start_time = time.time()

        # ── Étape 1 : Analyse IA du prompt ──
        self.monitor.start_stage(task_id, "prompt_analysis")
        await self._emit_progress("prompt_analysis", "Analyse du prompt...", 0.05)
        optimized_prompt = prompt
        if self.config.optimize_prompt:
            # Cache Redis : éviter de re-optimiser des prompts identiques
            cache_key = f"prompt_opt:{hash(prompt) & 0xFFFFFFFF}"
            cached_opt = self.cache.get(cache_key)
            if cached_opt and isinstance(cached_opt, dict) and cached_opt.get("optimized"):
                optimized_prompt = cached_opt["optimized"]
                stages["prompt_optimization"] = {
                    "original": prompt,
                    "optimized": optimized_prompt,
                    "corrections": cached_opt.get("corrections", []),
                    "added_keywords": cached_opt.get("added_keywords", []),
                    "from_cache": True,
                }
            else:
                opt_result = await self.prompt_optimizer.optimize(prompt)
                optimized_prompt = opt_result.optimized
                stages["prompt_optimization"] = {
                    "original": opt_result.original,
                    "optimized": opt_result.optimized,
                    "corrections": opt_result.corrections,
                    "added_keywords": opt_result.added_keywords,
                }
                self.cache.set(
                    cache_key,
                    {
                        "optimized": optimized_prompt,
                        "corrections": opt_result.corrections,
                        "added_keywords": opt_result.added_keywords,
                    },
                    ttl=86400,  # 24h
                )
        self.monitor.end_stage(task_id, "prompt_analysis", extra=stages.get("prompt_optimization"))
        await self._emit_progress("prompt_optimization", "Optimisation du prompt terminée", 0.08)

        # ── Étape 2 : Génération vidéo (via queue) ──
        self.monitor.start_stage(task_id, "video_generation")
        # La tâche peut attendre un slot (file partagée bots/utilisateurs) :
        # message honnête plutôt qu'un « Génération... » figé pendant l'attente.
        await self._emit_progress(
            "video_gen",
            "En attente d'un slot de génération...",
            0.10,
        )
        video_path = await self._generate_video(
            prompt=optimized_prompt,
            duration=duration,
            width=width,
            height=height,
            reference_image_paths=reference_image_paths,
            seed=seed,
            negative_prompt=negative_prompt,
            working_dir=working_dir,
        )
        await self._emit_progress("video_gen", "Vidéo générée", 0.70)
        self.monitor.end_stage(task_id, "video_generation", extra={"video_path": video_path})

        # ── Étape 3 : Upscaling + amélioration visuelle ──
        self.monitor.start_stage(task_id, "upscaling")
        await self._emit_progress("upscaling", "Upscaling et amélioration visuelle...", 0.85)
        enhanced_path = await self.postprocessor.enhance(video_path)
        if enhanced_path != video_path:
            video_path = enhanced_path
        self.monitor.end_stage(task_id, "upscaling")

        # ── Étape 4 : Amélioration audio ──
        if self.config.audio_enabled:
            self.monitor.start_stage(task_id, "audio_enhancement")
            await self._emit_progress("audio", "Ajout de l'audio...", 0.92)
            video_path = await self._enhance_audio(video_path, prompt)
            self.monitor.end_stage(task_id, "audio_enhancement")

        # ── Étape 5 : Compression intelligente ──
        self.monitor.start_stage(task_id, "compression")
        await self._emit_progress("compression", "Compression de la vidéo...", 0.98)
        final_path = await self._compress(video_path)
        self.monitor.end_stage(task_id, "compression")

        # ── Étape 6 : Garantie de durée exacte (v8.6) ──
        # L'API Agnes plafonne les frames en Full HD (≈11 s) : on complète
        # (dernière image figée) ou on tronque pour livrer EXACTEMENT la
        # durée demandée par l'utilisateur.
        # v8.9: ensure_video_duration est async — `await` direct, jamais via
        # asyncio.to_thread (retournerait la coroutine non exécutée).
        try:
            final_path = await ensure_video_duration(final_path, float(duration))
        except Exception as e:
            logger.warning(f"[AIVideoPipeline] ensure_video_duration failed: {e}")

        # ── Finalisation ──
        total_duration = time.time() - start_time
        self.monitor.finalize_task(task_id, status="completed")
        await self._emit_progress("done", "Terminé", 1.0)

        # Récupérer les métriques
        metrics = self.monitor.get_metrics(task_id) or {}

        return GenerationResult(
            video_path=final_path,
            duration=duration,
            resolution=f"{width}x{height}",
            quality=self.config.quality,
            style=self.config.style,
            metrics=metrics,
            stages=stages,
        )

    async def _generate_video(
        self,
        prompt: str,
        duration: int,
        width: int,
        height: int,
        reference_image_paths: Optional[list],
        seed: Optional[int],
        negative_prompt: Optional[str],
        working_dir: str,
    ) -> str:
        """Génère la vidéo via l'API Agnes."""
        os.makedirs(working_dir, exist_ok=True)
        video_path = os.path.join(working_dir, "final_video.mp4")

        # Soumettre via la queue
        _gen_started = time.time()

        async def _agv_progress(status: str, progress, curl_cmd: str) -> None:
            # Mappe la progression Agnes (0-100%) sur la tranche 10-70%
            # de l'échelle globale du pipeline. Même à 0%, on publie un
            # message : dès que la tâche sort de la file et est soumise,
            # l'utilisateur voit la transition « attente → génération ».
            try:
                pct = float(progress)
            except (TypeError, ValueError):
                return
            if pct <= 0:
                # v8.1: Agnes remonte souvent 0% pendant de longues minutes
                # puis saute directement à 100% : on fait avancer la barre
                # selon le temps écoulé (+10%/min, plafond +30%) pour que
                # l'UI ne semble pas figée sur 10%.
                elapsed_min = (time.time() - _gen_started) / 60.0
                creep = min(0.30, elapsed_min * 0.10)
                mapped = 0.10 + creep
                msg = "Génération de la vidéo en cours..."
            else:
                mapped = 0.10 + min(100.0, pct) * 0.60 / 100.0
                msg = f"Génération de la vidéo... {int(pct)}%"
            await self._emit_progress("video_gen", msg, round(min(0.68, mapped), 4))

        async def _do_generate():
            video_output = await self.video_api.generate_single_video(
                prompt=prompt,
                reference_image_paths=reference_image_paths or [],
                duration=duration,
                width=width,
                height=height,
                seed=seed,
                negative_prompt=negative_prompt,
                progress_callback=_agv_progress,
            )
            video_output.save(video_path)
            return video_path

        task = await self.queue.enqueue(
            task_id=f"gen_{int(time.time())}",
            priority=self.config.priority,
            fn=_do_generate,
        )

        result = await self.queue.wait(task.task_id, timeout=self.config.generation_timeout)
        return result

    async def _enhance_audio(self, video_path: str, prompt: str) -> str:
        """Améliore l'audio de la vidéo (TTS + normalisation douce).

        v8.6 — fail-safe : toute erreur (TTS, ffmpeg, enhancer) renvoie la
        vidéo inchangée au lieu de faire échouer la tâche (le mode simple
        faisait déjà ce compromis ; l'ancien code levait l'exception et le
        mode avancé « échouait » alors que la vidéo était générée).

        v8.6 — plus de troncature : l'ancien `-shortest` coupait la vidéo à la
        durée de la narration (un prompt court = 3-4 s au lieu des 15 s
        demandées). On muxe maintenant sans `-shortest` (la vidéo garde toute
        sa longueur ; la durée EXACTE est garantie par ensure_video_duration).
        """
        from core.audio.tts import EdgeTTSEngine
        from core.audio.enhancer import AudioEnhancer, AudioEnhanceConfig

        audio_path = video_path + ".narration.wav"
        try:
            tts = EdgeTTSEngine()
            await tts.generate(
                text=prompt.strip(),
                output_path=audio_path,
                voice=self.config.audio_voice,
                rate=self.config.audio_rate,
            )

            # v8.5: config audio adaptée au TTS synthétique (pas de débruitage agressif
            # qui dégrade la voix artificielle). On garde normalisation douce + EQ vocal.
            enhancer = AudioEnhancer(
                config=AudioEnhanceConfig(
                    denoise=False,           # TTS = pas de bruit à enlever (afftdn crée des artefacts)
                    normalize=True,          # loudnorm doux pour niveau constant
                    reduce_breath=False,     # pas de souffle sur TTS
                    spatialize=False,
                    eq_preset="vocal",       # EQ vocal léger
                    remove_clicks=False,     # pas de clics sur TTS
                    target_lufs=-18.0,       # niveau plus naturel pour narration
                )
            )
            enhanced_audio = await enhancer.enhance(audio_path, audio_path + ".enhanced.wav")

            # Overlay audio : mux SIMPLE (sans `-shortest`). Avec `-shortest`,
            # la vidéo était tronquée à la durée de la narration (prompt court
            # = 3-4 s au lieu des 15 s demandées). Sans `-shortest`, la sortie
            # dure max(vidéo, audio) : la vidéo garde toute sa longueur, la
            # narration reste au début (silence ensuite). L'étape finale
            # ensure_video_duration garantit ensuite la durée EXACTE demandée.
            output_path = video_path + ".audio.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", enhanced_audio,
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                output_path,
            ]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
                except asyncio.TimeoutError:
                    # v8.10: tuer le process au timeout (évite un ffmpeg zombie
                    # qui tourne en parallèle du prochain encode → OOM 512 Mo).
                    proc.kill()
                    await proc.wait()
                    logger.warning(f"[AIVideoPipeline] Audio overlay timeout (120s), killed")
                    if os.path.exists(output_path):
                        try:
                            os.remove(output_path)
                        except OSError:
                            pass
                    return video_path
                if proc.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    # Nettoyer les fichiers audio temporaires
                    for p in (audio_path, enhanced_audio):
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except OSError:
                                pass
                    return output_path
                # v9.4: loguer le stderr ffmpeg (avant, on voyait juste un code 69
                # sans la cause) + supprimer la sortie partielle.
                err_txt = ""
                if stderr:
                    err_txt = stderr.decode(errors="replace")[-600:]
                logger.warning(
                    f"[AIVideoPipeline] Audio overlay failed (code {proc.returncode}): {err_txt}"
                )
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass
            except Exception as e:
                logger.warning(f"[AIVideoPipeline] Audio overlay failed: {e}")
        except Exception as e:
            logger.warning(f"[AIVideoPipeline] Audio enhancement failed (non-fatal): {e}")

        # v9.4: log clair si la vidéo part SANS piste audio (le fail-safe
        # silencieux masquait les vidéos muettes publiées par les bots).
        try:
            probe = await asyncio.create_subprocess_exec(
                "ffmpeg", "-i", video_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, probe_err = await asyncio.wait_for(probe.communicate(), timeout=30)
            if b"Audio:" in (probe_err or b""):
                logger.info(f"[AIVideoPipeline] Piste audio confirmée: {video_path}")
            else:
                logger.error(f"[AIVideoPipeline] Vidéo livrée SANS piste audio: {video_path}")
        except Exception as e:
            logger.warning(f"[AIVideoPipeline] Probe audio impossible: {e}")

        return video_path

    async def _compress(self, video_path: str) -> str:
        """Compression intelligente (qualité préservée, preset ultrafast).

        v8.10 — deux corrections RAM (plan Free 512 Mo) :
        1. Le timeout doit TUER le process ffmpeg : avant, wait_for(300) expirait
           mais le process continuait de tourner en arrière-plan pendant que
           l'étape 6 (ensure_video_duration) lançait SON propre ffmpeg →
           2 encodages 1080p simultanés → « Ran out of memory » (tâche avancée
           f8b15659c077, 2026-08-04 11:40).
        2. preset ultrafast + threads 2 (comme le reste du pipeline) : le preset
           fast est ~4-5x plus lent sur le CPU partagé de Render et timeout
           systématiquement sur Full HD. ultrafast termine en ~1-2 min.
        """
        output_path = video_path + ".final.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-c:v", "libx264",
            "-crf", "21",
            "-preset", "ultrafast",
            "-threads", "2",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=240)
            except asyncio.TimeoutError:
                # CRITIQUE : tuer le process — sinon il continue d'encoder
                # 1080p en arrière-plan et fait OOM avec le prochain ffmpeg.
                proc.kill()
                await proc.wait()
                logger.warning(f"[AIVideoPipeline] Compression timeout (240s), killed: {video_path}")
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass
                return video_path
            if proc.returncode == 0 and os.path.exists(output_path):
                return output_path
            logger.warning(f"[AIVideoPipeline] Compression failed (code {proc.returncode})")
        except Exception as e:
            logger.warning(f"[AIVideoPipeline] Compression failed: {e}")

        return video_path
