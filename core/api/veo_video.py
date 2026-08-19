"""core.api.veo_video — Google Veo 3.1 API client (Gemini API)

Utilise l'API Gemini de Google (predictLongRunning) pour générer des vidéos
avec Veo 3.1. Supporte text-to-video et image-to-video avec audio natif.

API Reference: https://ai.google.dev/gemini-api/docs/video
"""

import asyncio
import base64
import json
import logging
import mimetypes
import os
import time
from typing import Callable, List, Optional

import requests

from core.api.error_collector import collect_error, collect_error_from_exception
from core.api.rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════
# Veo 3.1 models
# ═══════════════════════════════════════════════════
VEO_MODELS = {
    "veo-3.1": "veo-3.1-generate-preview",
    "veo-3.1-fast": "veo-3.1-fast-generate-preview",
}

VEO_DURATIONS = [4, 6, 8]

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class VeoVideoOutput:
    """Sortie vidéo Veo 3.1."""
    def __init__(self, fmt: str, ext: str, data):
        self.fmt = fmt
        self.ext = ext
        self.data = data

    def save(self, path: str) -> None:
        if self.fmt == "url":
            # Télécharger via URL avec auth header
            headers = {"x-goog-api-key": self.data.get("api_key", "")}
            url = self.data["url"]
            logger.info(f"[VeoVideo] Downloading video from {url[:80]}...")
            resp = requests.get(url, headers=headers, timeout=120)
            resp.raise_for_status()
            with open(path, "wb") as f:
                f.write(resp.content)
            logger.info(f"[VeoVideo] Downloaded {len(resp.content)} bytes -> {path}")
        elif self.fmt == "bytes":
            raw = self.data
            if isinstance(raw, str):
                raw = base64.b64decode(raw)
            with open(path, "wb") as f:
                f.write(raw)


class VeoVideoAPI:
    """Client API Google Veo 3.1 pour la génération vidéo.

    Utilise l'endpoint Gemini API (predictLongRunning) :
      POST /v1beta/models/{model}:predictLongRunning
      GET  /v1beta/{operationName}

    Auth: header x-goog-api-key.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "veo-3.1",
        default_duration: int = 6,
        max_retries: int = 6,
        retry_base_delay: float = 10.0,
        on_retry: Optional[Callable] = None,
        poll_interval: float = 10.0,
    ):
        self.api_key = api_key
        self.model_id = VEO_MODELS.get(model, model)
        self.model_name = model
        self.default_duration = default_duration
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.on_retry = on_retry
        self.poll_interval = poll_interval
        self.shutdown_event = None

    def _auth_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

    async def _resolve_image_ref(self, ref: str) -> Optional[dict]:
        """Convertit une référence image en format inlineData pour l'API."""
        if ref.startswith(("http://", "https://")):
            return {"url": ref}
        if os.path.exists(ref):
            with open(ref, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            mime = mimetypes.guess_type(ref)[0] or "image/png"
            return {"inlineData": {"mimeType": mime, "data": b64}}
        if ref.startswith("data:"):
            # data:mime;base64,XXX
            parts = ref.split(",", 1)
            header = parts[0]  # data:image/png;base64
            b64 = parts[1] if len(parts) > 1 else ""
            mime = header.split(":")[1].split(";")[0] if ":" in header else "image/png"
            return {"inlineData": {"mimeType": mime, "data": b64}}
        return None

    def _normalize_duration(self, seconds: int) -> str:
        """Veo 3.1 supporte uniquement 4, 6 ou 8 secondes (string)."""
        if seconds <= 4:
            return "4"
        elif seconds <= 6:
            return "6"
        else:
            return "8"

    def _normalize_aspect_ratio(self, width: int, height: int) -> str:
        if height > width:
            return "9:16"
        elif width > height:
            return "16:9"
        else:
            return "1:1"

    async def generate_video(
        self,
        prompt: str,
        reference_image_paths: List[str] = [],
        duration: Optional[int] = None,
        width: int = 1280,
        height: int = 720,
        resolution: str = "1080p",
        generate_audio: bool = True,
        progress_callback=None,
        **kwargs,
    ) -> VeoVideoOutput:
        dur = self._normalize_duration(duration or self.default_duration)
        aspect = self._normalize_aspect_ratio(width, height)
        veo_res = "720p" if "720" in str(resolution) else "1080p"

        # Construire le payload (format predictLongRunning)
        instance = {"prompt": prompt}

        # Image de référence pour i2v
        if reference_image_paths:
            img_data = await self._resolve_image_ref(reference_image_paths[0])
            if img_data:
                instance["image"] = img_data

        payload = {
            "instances": [instance],
            "parameters": {
                "aspectRatio": aspect,
                "sampleCount": 1,
                "durationSeconds": dur,
                "resolution": veo_res,
            },
        }

        mode_desc = "text-to-video" if not reference_image_paths else "image-to-video"
        logger.info(f"[VeoVideo] {mode_desc}: {prompt[:80]}... (model={self.model_name}, {dur}s, {veo_res}, {aspect})")

        # Soumettre la tâche
        operation_name = await self._submit(payload, mode_desc)

        # Poller jusqu'à completion
        result = await self._poll(operation_name, progress_callback)

        # Extraire l'URL de la vidéo
        video_url = self._extract_video_url(result)
        if not video_url:
            raise RuntimeError(f"[VeoVideo] Pas d'URL de vidéo dans la réponse: {json.dumps(result)[:500]}")

        logger.info(f"[VeoVideo] Done: {video_url[:80]}...")
        return VeoVideoOutput(fmt="url", ext="mp4", data={"url": video_url, "api_key": self.api_key})

    async def _submit(self, payload: dict, mode_desc: str) -> str:
        """Soumet une tâche de génération vidéo à l'API Veo 3.1."""
        last_exc = None
        for attempt in range(self.max_retries):
            if self.shutdown_event and self.shutdown_event.is_set():
                raise RuntimeError("Video generation cancelled by user")

            try:
                logger.info(f"[VeoVideo] Submitting {mode_desc} (attempt {attempt + 1}/{self.max_retries})...")
                await asyncio.to_thread(get_rate_limiter().acquire)

                url = f"{_BASE_URL}/models/{self.model_id}:predictLongRunning"
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        requests.post,
                        url,
                        headers=self._auth_headers(),
                        json=payload,
                        timeout=(15, 60),
                    ),
                    timeout=90,
                )

                if resp.status_code == 200:
                    result = resp.json()
                    op_name = result.get("name", "")
                    if op_name:
                        logger.info(f"[VeoVideo] Operation started: {op_name[:60]}...")
                        return op_name
                    raise RuntimeError(f"[VeoVideo] No operation name in response: {resp.text[:500]}")

                if resp.status_code == 429:
                    retry_after = 0
                    try:
                        ra = resp.headers.get("Retry-After")
                        if ra and str(ra).isdigit():
                            retry_after = float(ra)
                    except Exception:
                        pass
                    delay = max(retry_after, self.retry_base_delay * (attempt + 1))
                    logger.warning(f"[VeoVideo] 429 rate limit, retry {attempt + 1}/{self.max_retries} in {delay:.0f}s...")
                    collect_error(
                        "veo", "submit_video",
                        prompt=payload.get("instances", [{}])[0].get("prompt", ""),
                        error_type="RateLimit429",
                        error_message="HTTP 429: rate limited",
                        status_code=429,
                        response_body=resp.text,
                        retry_count=attempt + 1,
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code >= 500:
                    delay = self.retry_base_delay * (attempt + 1)
                    logger.warning(f"[VeoVideo] {resp.status_code} server error, retry {attempt + 1}/{self.max_retries} in {delay:.0f}s...")
                    collect_error(
                        "veo", "submit_video",
                        prompt=payload.get("instances", [{}])[0].get("prompt", ""),
                        error_type=f"HTTP{resp.status_code}",
                        error_message=f"HTTP {resp.status_code}: server error",
                        status_code=resp.status_code,
                        response_body=resp.text,
                        retry_count=attempt + 1,
                    )
                    await asyncio.sleep(delay)
                    continue

                # Erreur non-réessayable
                error_text = resp.text[:500]
                logger.error(f"[VeoVideo] HTTP {resp.status_code}: {error_text}")
                collect_error(
                    "veo", "submit_video",
                    prompt=payload.get("instances", [{}])[0].get("prompt", ""),
                    error_type="HTTPError",
                    error_message=f"HTTP {resp.status_code}: {error_text}",
                    status_code=resp.status_code,
                    response_body=resp.text,
                    retry_count=attempt + 1,
                )
                raise RuntimeError(
                    f"L'API Veo a refusé la demande (HTTP {resp.status_code}). "
                    f"Détail: {error_text[:300]}"
                )

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, asyncio.TimeoutError) as e:
                last_exc = e
                collect_error_from_exception(
                    "veo", "submit_video",
                    exc=e, prompt=payload.get("instances", [{}])[0].get("prompt", ""),
                    retry_count=attempt + 1,
                )
                if attempt < self.max_retries - 1:
                    delay = self.retry_base_delay * (attempt + 1)
                    logger.warning(f"[VeoVideo] {type(e).__name__}, retry {attempt + 1}/{self.max_retries} in {delay:.0f}s...")
                    await asyncio.sleep(delay)
                    continue
                raise

        if last_exc:
            raise last_exc
        raise RuntimeError(f"[VeoVideo] Submit: max retries ({self.max_retries}) exceeded")

    async def _poll(self, operation_name: str, progress_callback=None) -> dict:
        """Poll une opération Veo jusqu'à completion."""
        poll_count = 0
        max_poll_duration = 600  # 10 minutes max
        start_time = asyncio.get_event_loop().time()
        consecutive_failures = 0

        while True:
            if self.shutdown_event and self.shutdown_event.is_set():
                raise RuntimeError("Video generation cancelled by user")

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > max_poll_duration:
                raise RuntimeError(f"[VeoVideo] Polling timed out after {max_poll_duration}s")

            try:
                if poll_count % 5 == 0:
                    logger.info(f"[VeoVideo] Polling {operation_name[:60]}... (poll #{poll_count + 1}, elapsed {elapsed:.0f}s)")

                await asyncio.to_thread(get_rate_limiter().acquire)
                poll_url = f"{_BASE_URL}/{operation_name}"
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        requests.get,
                        poll_url,
                        headers=self._auth_headers(),
                        timeout=15,
                    ),
                    timeout=30,
                )
                resp.raise_for_status()
                result = resp.json()
                poll_count += 1
                consecutive_failures = 0

                if progress_callback:
                    done = result.get("done", False)
                    progress = 100 if done else min(90, int(elapsed / max_poll_duration * 100))
                    cb = progress_callback("completed" if done else "running", progress, "")
                    if asyncio.iscoroutine(cb):
                        await cb

                if result.get("done"):
                    error = result.get("error")
                    if error:
                        error_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                        raise RuntimeError(f"[VeoVideo] Generation failed: {error_msg}")
                    return result

            except requests.exceptions.HTTPError as e:
                status_code = getattr(e.response, 'status_code', 0) if hasattr(e, 'response') else 0
                if status_code == 429:
                    retry_after = 0
                    try:
                        ra = e.response.headers.get("Retry-After") if e.response else ""
                        retry_after = int(ra) if ra and str(ra).isdigit() else 0
                    except Exception:
                        retry_after = 0
                    pause = retry_after if retry_after > 0 else min(15 * (poll_count + 1), 120)
                    logger.warning(f"[VeoVideo] 429 au polling, pause {pause}s...")
                    await asyncio.sleep(pause)
                    continue
                consecutive_failures += 1
                logger.warning(f"[VeoVideo] Poll HTTP error ({consecutive_failures}): {e}")
                if consecutive_failures >= 10:
                    raise RuntimeError(f"[VeoVideo] Échec du polling après {consecutive_failures} erreurs")

            except (requests.exceptions.RequestException, asyncio.TimeoutError) as e:
                consecutive_failures += 1
                logger.warning(f"[VeoVideo] Poll error ({consecutive_failures}): {e}")
                if consecutive_failures >= 10:
                    raise RuntimeError(f"[VeoVideo] Échec du polling après {consecutive_failures} erreurs")

            await asyncio.sleep(self.poll_interval)

    def _extract_video_url(self, result: dict) -> Optional[str]:
        """Extrait l'URL de la vidéo depuis la réponse de l'opération."""
        response = result.get("response", {})

        # Format predictLongRunning (Gemini API) :
        # response.generateVideoResponse.generatedSamples[0].video.uri
        gen_resp = response.get("generateVideoResponse", {})
        samples = gen_resp.get("generatedSamples", [])
        if samples:
            video = samples[0].get("video", {})
            url = video.get("uri")
            if url:
                return url

        # Fallback : format direct generatedVideos (Vertex AI)
        generated = response.get("generatedVideos", [])
        if generated:
            video = generated[0].get("video", {})
            url = video.get("uri") or video.get("url")
            if url:
                return url

        logger.warning(f"[VeoVideo] Unexpected response structure: {json.dumps(result)[:800]}")
        return None
