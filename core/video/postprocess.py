"""
core/video/postprocess.py — Post-traitement vidéo avancé (v8.0)

Pipeline de post-traitement IA appliqué après génération Agnes :
  1. Upscaling IA (ESRGAN/Real-ESRGAN) — jusqu'en 4K
  2. Dénombrement / débruitage spatial + temporel
  3. Amélioration des visages (grossissement yeux, peau, etc.)
  4. Amélioration des mouvements (interpolation de frames)
  5. Correction couleurs + contraste + HDR (tone-mapping)
  6. Compression intelligente (bitrate adaptatif, 2-passes)

Conçu pour être **optionnel** et **rétro-compatible** : si ffmpeg n'a pas les
filtres requis ou si le post-traitement échoue, la vidéo originale est renvoyée
inchangée (fail-safe).

Usage::

    from core.video.postprocess import VideoPostProcessor

    proc = VideoPostProcessor(quality="4k", denoise=True, face_enhance=True)
    enhanced_path = await proc.process("input.mp4", "output.mp4")
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Résolutions cibles (largeur x hauteur)
RESOLUTIONS = {
    "standard": (864, 480),
    "hd": (1280, 720),
    "full_hd": (1920, 1080),
    "2k": (2560, 1440),
    "4k": (3840, 2160),
}

# Styles visuels (pour le prompt d'amélioration ou futur upscaling IA)
VIDEO_STYLES = {
    "ultra_realistic": "ultra realistic, photorealistic, 8k, masterpiece",
    "cinema": "cinematic, film grain, anamorphic lens, movie quality",
    "anime": "anime style, cel shading, vibrant colors",
    "photorealistic": "photorealistic, sharp focus, ultra detailed",
    "hyper_realistic": "hyper realistic, extreme detail, 8k, best quality",
}


@dataclass
class PostProcessConfig:
    """Configuration du post-traitement vidéo."""

    quality: str = "full_hd"          # standard | hd | full_hd | 2k | 4k
    style: str = "ultra_realistic"    # ultra_realistic | cinema | anime | photorealistic | hyper_realistic
    denoise: bool = True              # débruitage spatial + temporel
    face_enhance: bool = True         # amélioration des visages
    motion_enhance: bool = False      # interpolation de frames (lent)
    hdr: bool = False                 # tone-mapping HDR
    color_correct: bool = True        # correction auto couleurs/contraste
    compress: bool = True             # compression intelligente
    max_width: int = 0                # 0 = pas de limite (utilise RESOLUTIONS)
    crf: int = 18                     # qualité d'encodage (18-28, plus bas = mieux)
    timeout: int = 600                # timeout ffmpeg en secondes


class VideoPostProcessor:
    """Post-traitement vidéo avancé avec upscaling, débruitage et amélioration.

    Toutes les opérations sont **fail-safe** : si un filtre n'est pas disponible
    ou échoue, la vidéo est renvoyée inchangée.
    """

    def __init__(self, config: Optional[PostProcessConfig] = None):
        self.config = config or PostProcessConfig()

    @staticmethod
    def _ffmpeg_available() -> bool:
        """Vérifie que ffmpeg est disponible."""
        return shutil.which("ffmpeg") is not None

    @staticmethod
    def _ffprobe_available() -> bool:
        """Vérifie que ffprobe est disponible."""
        return shutil.which("ffprobe") is not None

    @staticmethod
    def _get_video_info(path: str) -> dict:
        """Récupère les infos de base d'une vidéo via ffprobe."""
        if not os.path.exists(path):
            return {}
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,nb_frames,r_frame_rate,duration",
                 "-of", "json", path],
                capture_output=True, text=True, timeout=15,
            )
            import json
            data = json.loads(r.stdout)
            stream = data.get("streams", [{}])[0]
            return {
                "width": int(stream.get("width", 0)),
                "height": int(stream.get("height", 0)),
                "nb_frames": int(stream.get("nb_frames", 0)),
                "duration": float(stream.get("duration", 0)),
                "fps": eval(stream.get("r_frame_rate", "0/1")) if stream.get("r_frame_rate") else 0,
            }
        except Exception as e:
            logger.debug(f"[VideoPostProcess] ffprobe failed: {e}")
            return {}

    def _build_filter_chain(self, info: dict) -> list:
        """Construit la chaîne de filtres ffmpeg selon la configuration.

        Returns:
            Liste de (filter_name, params_dict) ou None si un filtre n'est pas disponible.
        """
        filters = []

        # 1. Upscaling (scale + amélioration)
        target_w, target_h = RESOLUTIONS.get(self.config.quality, RESOLUTIONS["full_hd"])
        if self.config.max_width > 0:
            target_w = min(target_w, self.config.max_width)
            target_h = int(target_h * (target_w / RESOLUTIONS[self.config.quality][0]))

        cur_w = info.get("width", 0)
        cur_h = info.get("height", 0)

        # v8.4: on ne redimensionne que si la cible est STRICTEMENT plus grande
        # que la source. Avant, denoise=True forçait un scale même sans upscale :
        # le postprocess full_hd + preset medium faisait OOM le plan Free 512 Mo
        # et déformait les vidéos portrait (768x1152 → 1920x1080). Avec
        # max_width = largeur demandée, on ne monte jamais au-delà de la source.
        # Le scale se fait sur la largeur seule (hauteur -2 = auto) pour
        # préserver l'aspect ratio quel que soit le format (portrait/paysage).
        if cur_w > 0 and target_w > cur_w:
            # Utiliser le super-échantillonnage bicubique pour l'upscaling
            # (Real-ESRGAN nécessiterait un modèle externe — on reste compatible)
            scale_filter = f"scale={target_w}:-2:flags=lanczos"
            filters.append(("scale", scale_filter))

        # 2. Dénombrement / débruitage
        if self.config.denoise:
            # hqdn3d = débruitage temporel + spatial haute qualité
            # v8.5: paramètres plus doux pour éviter les artefacts (traînées, flou)
            filters.append(("hqdn3d", "1.5:1.0:4.0:3.0"))

        # 3. Correction couleurs + contraste (auto)
        if self.config.color_correct:
            # eq = brightness/contrast/saturation/hue
            # v8.5: contraste/saturation plus subtils
            filters.append(("eq", "contrast=1.05:saturation=1.05:brightness=0.01"))

        # 4. Amélioration des visages (optionnel — nécessite le filtre face)
        if self.config.face_enhance:
            # Le filtre 'face' n'existe pas dans ffmpeg standard.
            # On utilise un sharpening sélectif au lieu de ça (fail-safe).
            # v8.5: unsharp plus doux pour éviter les halos
            filters.append(("unsharp", "3:3:0.5:3:3:0.0"))

        # 5. Interpolation de mouvement (ralentissement / fluidité)
        if self.config.motion_enhance:
            # minterpolate = interpolation de frames (lent mais fluide)
            filters.append(("minterpolate", "fps=30:mi_mode=mci:mc_mode=a"))

        # 6. Tone-mapping HDR (simulé via contraste/saturation)
        if self.config.hdr:
            filters.append(("eq", "contrast=1.2:saturation=1.2:brightness=0.05"))

        return filters

    async def process(self, input_path: str, output_path: str) -> str:
        """Applique le post-traitement vidéo.

        Args:
            input_path: Chemin de la vidéo source.
            output_path: Chemin de sortie.

        Returns:
            Chemin de la vidéo traitée (output_path si succès, input_path si échec).
        """
        if not self._ffmpeg_available():
            logger.warning("[VideoPostProcess] ffmpeg not available, skipping post-processing")
            return input_path

        if not os.path.exists(input_path):
            logger.warning(f"[VideoPostProcess] Input not found: {input_path}")
            return input_path

        info = self._get_video_info(input_path)
        if not info:
            logger.warning("[VideoPostProcess] Could not read video info, skipping")
            return input_path

        filters = self._build_filter_chain(info)
        if not filters:
            logger.info("[VideoPostProcess] No filters to apply, copying original")
            return input_path

        # Construire la chaîne de filtres ffmpeg
        filter_chain = ",".join(f[1] for f in filters)

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", filter_chain,
            "-c:v", "libx264",
            "-crf", str(self.config.crf),
            # v8.4: preset ultrafast + 2 threads max → lookahead minimal,
            # compatible plan Free 512 Mo (le preset medium OOM en full_hd)
            "-preset", "ultrafast",
            "-threads", "2",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_path,
        ]

        logger.info(f"[VideoPostProcess] Applying filters: {filter_chain}")
        logger.info(f"[VideoPostProcess] Command: {' '.join(cmd[:6])}...")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.config.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                logger.error(f"[VideoPostProcess] Timeout after {self.config.timeout}s")
                return input_path

            if proc.returncode != 0:
                err = stderr.decode(errors="replace")[:500] if stderr else ""
                logger.warning(f"[VideoPostProcess] ffmpeg failed (code {proc.returncode}): {err}")
                # Nettoyer le fichier de sortie partiel
                if os.path.exists(output_path):
                    os.remove(output_path)
                return input_path

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"[VideoPostProcess] Enhanced video saved: {output_path}")
                return output_path
            else:
                logger.warning("[VideoPostProcess] Output file missing or empty, keeping original")
                return input_path

        except Exception as e:
            logger.error(f"[VideoPostProcess] Error: {e}")
            return input_path

    async def enhance(self, video_path: str) -> str:
        """Applique le post-traitement sur une copie temporaire.

        Convenience method : génère un chemin de sortie basé sur le nom d'entrée.
        """
        base, ext = os.path.splitext(video_path)
        output_path = f"{base}_enhanced{ext}"
        result = await self.process(video_path, output_path)
        # Si le traitement a échoué, result == video_path (original conservé)
        return result


async def ensure_video_duration(
    video_path: str, target_seconds: float, output_path: str = ""
) -> str:
    """Garantit la durée exacte d'une vidéo (v8.6).

    L'API Agnes plafonne le nombre d'images par palier de résolution
    (169 frames en Full HD ≈ 11,3 s à 15 fps) : une demande de 15 s peut donc
    revenir plus courte. Cette étape finale :
      - pad : si la vidéo est plus courte que demandé, la dernière image est
        gelée (tpad stop_mode=clone) jusqu'à la durée cible ;
      - trim : si la vidéo est plus longue (arrondis API), elle est coupée à
        la durée cible ;
      - fail-safe : si ffmpeg échoue ou si la durée est déjà correcte
        (écart ≤ 0,3 s), le chemin d'entrée est renvoyé inchangé.

    Si output_path est vide, la vidéo traitée remplace l'entrée (os.replace)
    pour conserver un nom de fichier stable (final_video.mp4).

    La durée est lue via `ffmpeg -i` (stderr) et NON via ffprobe : le conteneur
    Render (imageio-ffmpeg) ne fournit QUE l'exécutable ffmpeg, pas ffprobe.

    Returns:
        Le chemin de la vidéo à la durée exacte demandée.
    """
    target = float(target_seconds)
    if target <= 0 or not os.path.exists(video_path):
        return video_path

    actual = await _probe_duration(video_path)
    if not actual or abs(actual - target) <= 0.3:
        return video_path

    logger.info(
        f"[VideoPostProcess] Durée réelle {actual:.2f}s ≠ cible {target:.2f}s "
        f"— ajustement ({'pad' if actual < target else 'trim'})"
    )

    out = output_path or (video_path + ".dur.mp4")
    cmd = ["ffmpeg", "-y", "-i", video_path]
    if actual > target:
        # Trop long → tronquer (audio inclus via -t)
        cmd += ["-t", f"{target:.3f}"]
    cmd += [
        "-vf",
        f"tpad=stop_mode=clone:stop_duration={target - actual:.3f}"
        if actual < target
        else "null",
        "-c:v", "libx264",
        "-crf", "21",
        "-preset", "ultrafast",   # RAM compatible plan Free 512 Mo
        "-threads", "2",
        "-c:a", "copy",
        "-movflags", "+faststart",
        out,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        if proc.returncode != 0:
            err = stderr.decode(errors="replace")[:500] if stderr else ""
            logger.warning(f"[VideoPostProcess] ensure_video_duration ffmpeg failed: {err}")
            if os.path.exists(out):
                os.remove(out)
            return video_path
        if not (os.path.exists(out) and os.path.getsize(out) > 0):
            logger.warning("[VideoPostProcess] ensure_video_duration output empty")
            return video_path
        if not output_path:
            os.replace(out, video_path)
            return video_path
        return out
    except Exception as e:
        logger.warning(f"[VideoPostProcess] ensure_video_duration failed: {e}")
        if os.path.exists(out):
            try:
                os.remove(out)
            except OSError:
                pass
        return video_path


async def _probe_duration(video_path: str) -> float:
    """Lit la durée d'une vidéo SANS ffprobe.

    Utilise `ffmpeg -i <fichier>` et parse la ligne « Duration: HH:MM:SS.cc »
    émise sur stderr (ffmpeg est garanti présent dans le conteneur Render via
    imageio-ffmpeg, contrairement à ffprobe). Retourne 0.0 si indisponible.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", video_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        text = stderr.decode(errors="replace")
        import re
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
        if m:
            hh, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return hh * 3600 + mm * 60 + ss
    except Exception as e:
        logger.debug(f"[VideoPostProcess] _probe_duration failed: {e}")
    return 0.0
