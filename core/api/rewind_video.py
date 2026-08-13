"""Client Rewind AI pour la génération vidéo Veo 3.1.

Le jeton n'est jamais exposé au navigateur : il est lu uniquement depuis
REWIND_API_KEY côté serveur. L'API Rewind est asynchrone et renvoie un job,
qui est ensuite interrogé jusqu'à obtention de l'URL vidéo.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, List, Optional

import requests

from core.api.error_collector import collect_error, collect_error_from_exception
from utils.video import download_video

logger = logging.getLogger(__name__)

REWIND_BASE_URL = os.environ.get("REWIND_API_BASE_URL", "https://api.rewind.ai").rstrip("/")
REWIND_MODEL = os.environ.get("REWIND_VIDEO_MODEL", "google/veo-3.1")


class RewindVideoOutput:
    """Sortie vidéo compatible avec le contrat VideoOutput d'Agnes."""

    def __init__(self, url: str):
        self.fmt = "url"
        self.ext = "mp4"
        self.data = url

    def save(self, path: str) -> None:
        download_video(self.data, path)


class RewindVideoAPI:
    """Client minimal et tolérant pour l'API vidéo Rewind AI."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = REWIND_MODEL,
        poll_interval: float = 5.0,
        max_poll_duration: int = 1800,
    ):
        self.api_key = api_key or os.environ.get("REWIND_API_KEY", "").strip()
        self.model = model.split(":", 1)[1] if model.startswith("rewind:") else model
        self.poll_interval = poll_interval
        self.max_poll_duration = max_poll_duration
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Agnes-IA/rewind-video",
        }

    def _ensure_key(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "REWIND_API_KEY n'est pas configurée. Ajoutez votre clé Rewind "
                "dans les variables d'environnement du serveur."
            )

    @staticmethod
    def _aspect_ratio(width: int, height: int) -> str:
        if width <= 0 or height <= 0:
            return "16:9"
        ratio = width / height
        if ratio > 1.55:
            return "16:9"
        if ratio < 0.72:
            return "9:16"
        if 0.92 <= ratio <= 1.08:
            return "1:1"
        return "4:3" if ratio < 1.25 else "3:2"

    @staticmethod
    def _duration(value: Optional[int]) -> str:
        seconds = int(value or 5)
        return f"{max(4, min(seconds, 10))}s"

    @staticmethod
    def _extract_job_id(payload: dict) -> Optional[str]:
        for key in ("job_id", "jobId", "prediction_id", "predictionId", "task_id", "id"):
            value = payload.get(key)
            if value:
                return str(value)
        data = payload.get("data")
        if isinstance(data, dict):
            return RewindVideoAPI._extract_job_id(data)
        return None

    @staticmethod
    def _extract_url(payload: dict) -> Optional[str]:
        candidates = (
            payload.get("video_url"),
            payload.get("videoUrl"),
            payload.get("output"),
            payload.get("url"),
            payload.get("result"),
        )
        for value in candidates:
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.startswith(("http://", "https://")):
                        return item
            if isinstance(value, dict):
                found = RewindVideoAPI._extract_url(value)
                if found:
                    return found
        data = payload.get("data")
        if isinstance(data, dict):
            return RewindVideoAPI._extract_url(data)
        return None

    async def submit_video(
        self,
        prompt: str,
        reference_image_paths: Optional[List[str]] = None,
        duration: Optional[int] = None,
        width: int = 1152,
        height: int = 768,
        negative_prompt: Optional[str] = None,
        **kwargs,
    ) -> str:
        self._ensure_key()
        payload = {
            "model": self.model,
            "prompt": prompt,
            "duration": self._duration(duration),
            "aspectRatio": self._aspect_ratio(width, height),
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if kwargs.get("generate_audio") is not False:
            payload["generate_audio"] = True
        refs = reference_image_paths or []
        if refs:
            # Rewind accepte une image de référence. Agnes résout déjà les
            # fichiers locaux en URL/base64 avant l'appel de l'adaptateur.
            payload["image"] = refs[0]

        try:
            response = await asyncio.to_thread(
                requests.post,
                f"{REWIND_BASE_URL}/v1/videos/generate-async",
                headers=self.headers,
                json=payload,
                timeout=(20, 90),
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Rewind HTTP {response.status_code}: {response.text[:500]}"
                )
            result = response.json()
            job_id = self._extract_job_id(result)
            if not job_id:
                # Certains déploiements Rewind peuvent renvoyer directement
                # une URL dans la réponse.
                direct_url = self._extract_url(result)
                if direct_url:
                    return f"direct:{direct_url}"
                raise RuntimeError(f"Réponse Rewind sans identifiant de job: {result}")
            logger.info("[RewindVideo] Job soumis: %s", job_id[:32])
            return job_id
        except Exception as exc:
            collect_error_from_exception("video", "rewind_submit", exc=exc, prompt=prompt)
            raise

    async def wait_for_video(self, job_id: str, progress_callback: Optional[Callable] = None) -> RewindVideoOutput:
        if job_id.startswith("direct:"):
            return RewindVideoOutput(job_id[len("direct:"):])
        self._ensure_key()
        start = asyncio.get_event_loop().time()
        last_status = ""
        while True:
            if asyncio.get_event_loop().time() - start > self.max_poll_duration:
                raise RuntimeError("Rewind: délai d'attente dépassé pendant la génération vidéo")
            try:
                response = await asyncio.to_thread(
                    requests.get,
                    f"{REWIND_BASE_URL}/v1/jobs/{job_id}",
                    headers=self.headers,
                    timeout=(15, 45),
                )
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"Rewind polling HTTP {response.status_code}: {response.text[:400]}"
                    )
                result = response.json()
                status = str(result.get("status") or result.get("state") or "").lower()
                progress = result.get("progress", 0)
                if status != last_status:
                    logger.info("[RewindVideo] %s status=%s progress=%s", job_id[:24], status, progress)
                    last_status = status
                if progress_callback:
                    callback_result = progress_callback(status or "running", progress, "rewind")
                    if asyncio.iscoroutine(callback_result):
                        await callback_result
                url = self._extract_url(result)
                if url and status not in {"failed", "error", "cancelled", "canceled"}:
                    return RewindVideoOutput(url)
                if status in {"failed", "error", "cancelled", "canceled"}:
                    raise RuntimeError(f"Rewind génération échouée: {result}")
            except Exception as exc:
                collect_error_from_exception("video", "rewind_poll", exc=exc, extra={"job_id": job_id[:32]})
                raise
            await asyncio.sleep(self.poll_interval)
