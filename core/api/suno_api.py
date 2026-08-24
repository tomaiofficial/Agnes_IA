"""core.api.suno_api — Suno AI music generation client (via Apiframe)

Génère de la musique (vocals + instruments) à partir d'un prompt texte.
Supporte : description mode, custom lyrics mode, instrumental.

API Reference: https://apiframe.ai/docs/music/suno
"""

import asyncio
import logging
import time
from typing import Callable, Optional

import requests

from core.api.error_collector import collect_error, collect_error_from_exception
from core.api.rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════
# Suno models
# ═══════════════════════════════════════════════════
SUNO_MODELS = {
    "suno-v5": "V5",
    "suno-v5.5": "V5_5",
    "suno-v4.5": "V4_5PLUS",
}

_BASE_URL = "https://api.apiframe.ai/v2"


class SunoTrack:
    """Un track musical généré par Suno."""
    def __init__(self, data: dict):
        self.id = data.get("id", "")
        self.audio_url = data.get("audio_url", "") or data.get("source_audio_url", "")
        self.image_url = data.get("image_url", "") or data.get("source_image_url", "")
        self.title = data.get("title", "")
        self.tags = data.get("tags", "")
        self.prompt = data.get("prompt", "")
        self.model_name = data.get("model_name", "")
        self.duration = data.get("duration", 0)

    def save(self, path: str) -> None:
        """Télécharge le audio dans un fichier."""
        if not self.audio_url:
            raise ValueError("Pas d'URL audio disponible")
        logger.info(f"[SunoTrack] Downloading {self.title or self.id} from {self.audio_url[:80]}...")
        resp = requests.get(self.audio_url, timeout=120)
        resp.raise_for_status()
        with open(path, "wb") as f:
            f.write(resp.content)
        logger.info(f"[SunoTrack] Downloaded {len(resp.content)} bytes -> {path}")

    def save_image(self, path: str) -> None:
        """Télécharge la cover art."""
        if not self.image_url:
            raise ValueError("Pas d'URL image disponible")
        resp = requests.get(self.image_url, timeout=60)
        resp.raise_for_status()
        with open(path, "wb") as f:
            f.write(resp.content)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "audio_url": self.audio_url,
            "image_url": self.image_url,
            "title": self.title,
            "tags": self.tags,
            "prompt": self.prompt,
            "model_name": self.model_name,
            "duration": self.duration,
        }


class SunoOutput:
    """Sortie de génération musicale Suno (2 tracks)."""
    def __init__(self, tracks: list):
        self.tracks = tracks  # List[SunoTrack]

    @property
    def first(self) -> Optional[SunoTrack]:
        return self.tracks[0] if self.tracks else None

    def to_dict(self) -> dict:
        return {
            "tracks": [t.to_dict() for t in self.tracks],
            "count": len(self.tracks),
        }


class SunoAPI:
    """Client API Suno AI pour la génération musicale.

    Utilise l'endpoint Apiframe (wrapper Suno) :
      POST /v2/music/generate   → soumet un job
      GET  /v2/jobs/{id}        → poll le statut

    Auth: header X-API-Key.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "suno-v5.5",
        max_retries: int = 3,
        retry_base_delay: float = 5.0,
        progress_callback: Optional[Callable] = None,
        shutdown_event: Optional[asyncio.Event] = None,
    ):
        self.api_key = api_key
        self.model_version = SUNO_MODELS.get(model, "V5_5")
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.progress_callback = progress_callback
        self.shutdown_event = shutdown_event
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }

    def _report(self, msg: str, pct: float = 0):
        logger.info(f"[SunoAPI] {msg}")
        if self.progress_callback:
            try:
                self.progress_callback(msg, pct)
            except Exception:
                pass

    async def generate(
        self,
        prompt: str,
        style: str = "",
        title: str = "",
        instrumental: bool = False,
        custom_mode: bool = False,
        vocal_gender: str = "",
        negative_tags: str = "",
        callback_url: str = "",
    ) -> SunoOutput:
        """Génère de la musique à partir d'un prompt.

        Args:
            prompt: Description du morceau (mode normal) ou lyrics (custom_mode=True)
            style: Style/genre (ex: "lofi, jazz, chill")
            title: Titre du morceau
            instrumental: True = pas de vocals
            custom_mode: True = prompt = lyrics
            vocal_gender: "m" ou "f"
            negative_tags: Styles à éviter
            callback_url: URL de callback webhook (optionnel)

        Returns:
            SunoOutput avec les 2 tracks générées
        """
        await asyncio.to_thread(get_rate_limiter().acquire)

        body = {
            "prompt": prompt,
            "model": "suno",
            "sunoParams": {
                "model_version": self.model_version,
            },
        }

        if custom_mode:
            body["sunoParams"]["custom_mode"] = True
        if instrumental:
            body["sunoParams"]["instrumental"] = True
        if style:
            body["sunoParams"]["style"] = style
        if title:
            body["sunoParams"]["title"] = title
        if vocal_gender:
            body["sunoParams"]["vocal_gender"] = vocal_gender
        if negative_tags:
            body["sunoParams"]["negative_tags"] = negative_tags
        if callback_url:
            body["callbackUrl"] = callback_url

        self._report("🎵 Envoi de la demande musicale...", 10)

        # ── Submit job ──
        job_id = await self._submit(body)
        self._report(f"🎵 Job soumis : {job_id[:16]}...", 20)

        # ── Poll until done ──
        tracks = await self._poll(job_id)
        self._report("🎵 Musique générée !", 100)

        return SunoOutput(tracks=tracks)

    async def _submit(self, body: dict) -> str:
        """Soumet un job de génération musicale."""
        for attempt in range(self.max_retries + 1):
            if self.shutdown_event and self.shutdown_event.is_set():
                raise RuntimeError("Arrêt demandé par l'utilisateur")
            try:
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        requests.post,
                        f"{_BASE_URL}/music/generate",
                        headers=self.headers,
                        json=body,
                        timeout=60,
                    ),
                    timeout=70,
                )
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", self.retry_base_delay * (2 ** attempt)))
                    self._report(f"⏳ Rate limit, attente {retry_after}s...", 15)
                    await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                data = resp.json()
                job_id = data.get("id", "")
                if not job_id:
                    raise ValueError(f"Pas de job_id dans la réponse: {data}")
                return job_id
            except requests.exceptions.HTTPError as e:
                collect_error("suno_api", "submit", str(e), body)
                if attempt < self.max_retries:
                    delay = self.retry_base_delay * (2 ** attempt)
                    self._report(f"⚠️ Erreur {e.response.status_code}, retry dans {delay}s...", 15)
                    await asyncio.sleep(delay)
                else:
                    raise
            except Exception as e:
                collect_error_from_exception("suno_api", "submit", e)
                raise

    async def _poll(self, job_id: str, max_wait: float = 600) -> list:
        """Poll le statut du job jusqu'à complétion."""
        start = time.time()
        poll_interval = 5

        while True:
            if self.shutdown_event and self.shutdown_event.is_set():
                raise RuntimeError("Arrêt demandé par l'utilisateur")
            if time.time() - start > max_wait:
                raise TimeoutError(f"Timeout après {max_wait}s en attente du job {job_id}")

            try:
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        requests.get,
                        f"{_BASE_URL}/jobs/{job_id}",
                        headers={"X-API-Key": self.api_key},
                        timeout=30,
                    ),
                    timeout=35,
                )
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "").upper()

                elapsed = int(time.time() - start)
                if status == "COMPLETED":
                    self._report(f"✅ Terminé en {elapsed}s", 95)
                    return self._parse_tracks(data)
                elif status == "FAILED":
                    error = data.get("error", "Erreur inconnue")
                    collect_error("suno_api", "poll", error, {"job_id": job_id})
                    raise RuntimeError(f"Échec génération musicale: {error}")
                else:
                    pct = min(90, 20 + (elapsed / max_wait) * 70)
                    self._report(f"⏳ Génération en cours... ({elapsed}s)", pct)

            except requests.exceptions.HTTPError as e:
                collect_error("suno_api", "poll", str(e), {"job_id": job_id})
                if e.response and e.response.status_code == 404:
                    raise ValueError(f"Job {job_id} introuvable")

            # Backoff progressif
            await asyncio.sleep(poll_interval)
            poll_interval = min(30, poll_interval + 2)

    def _parse_tracks(self, data: dict) -> list:
        """Parse les tracks depuis la réponse API."""
        tracks = []
        # Apiframe: data["result"]["tracks"] ou data["data"]["tracks"]
        result = data.get("result") or data.get("data") or {}
        raw_tracks = result.get("tracks") if isinstance(result, dict) else None
        if not raw_tracks and isinstance(result, list):
            raw_tracks = result
        if not raw_tracks:
            # Fallback: chercher dans data directement
            raw_tracks = data.get("tracks", [])
        for t in (raw_tracks or []):
            tracks.append(SunoTrack(t))
        return tracks
