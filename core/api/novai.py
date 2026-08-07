"""
core/api/novai.py — Moteur vidéo NovAI (cogvideox-flash, $0/génération) (v9.1)

Principe : Agnes_IA ne consomme AUCUN crédit Agnes quand le moteur NovAI est
utilisé. NovAI est une passerelle OpenAI-compatible (https://aiapi-pro.com/v1)
qui route les modèles « flash » gratuits de Zhipu : `cogvideox-flash` est
facturé $0 par génération (inscription email, sans carte bancaire).

Le client soumet un job (POST /v1/video/generations), poll le statut
(GET /v1/video/generations/{id}?model=...), puis télécharge le MP4 dans le
working_dir de la tâche (exposé ensuite par GET /api/video/{id}).

Contreparties assumées du modèle gratuit :
- qualité « flash tier » (au-dessous de Seedance/Kling/Sora) ;
- watermark chinois « AI生成 » obligatoire (exigence légale côté upstream) ;
- jobs de la file gratuite traités à priorité basse (plus lents en pointe).
"""

import logging
import os
import time
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

# Modèle vidéo gratuit ($0/génération)
NOVAI_VIDEO_MODEL = "cogvideox-flash"
# Durées supportées par cogvideox-flash (clips courts)
NOVAI_DURATIONS = (5, 10)
NOVAI_POLL_INTERVAL = 5.0
NOVAI_DEFAULT_TIMEOUT = 30.0


class NovAIError(Exception):
    """Erreur utilisateur lisible (affichée telle quelle dans l'UI)."""


class NovAIVideoClient:
    """Client minimal de l'API vidéo NovAI (submit → poll → download).

    L'appel réseau est synchrone (requests) ; les endpoints FastAPI le
    lancent dans un thread via `asyncio.to_thread` (même pattern que
    l'ancien client LTX).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://aiapi-pro.com/v1",
        timeout: float = NOVAI_DEFAULT_TIMEOUT,
    ):
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").strip().rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise NovAIError("Clé API NovAI manquante (NOVAI_API_KEY)")
        if not self.base_url:
            raise NovAIError("Base URL NovAI manquante")

    # ── helpers ─────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _handle_http_error(resp: requests.Response, context: str) -> None:
        if resp.status_code == 401:
            raise NovAIError(
                "Clé API NovAI invalide (401) — vérifie NOVAI_API_KEY "
                "(clé gratuite sur https://aiapi-pro.com)."
            )
        if resp.status_code == 403:
            raise NovAIError(
                "Accès NovAI refusé (403) — vérifie le statut de la clé "
                "(check-in quotidien / rôle Discord ?)."
            )
        if resp.status_code == 429:
            raise NovAIError(
                "Limite NovAI atteinte (429) — réessaie dans quelques minutes."
            )
        raise NovAIError(
            f"Erreur NovAI {context} (HTTP {resp.status_code}): {resp.text[:300]}"
        )

    # ── API vidéo ───────────────────────────────────────────

    def submit(self, prompt: str, duration: int = 5) -> str:
        """Soumet un job de génération T2V. Retourne l'id du job."""
        try:
            resp = requests.post(
                f"{self.base_url}/video/generations",
                headers=self._headers(),
                json={
                    "model": NOVAI_VIDEO_MODEL,
                    "prompt": prompt,
                    "duration": duration,
                },
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout:
            raise NovAIError("NovAI ne répond pas (timeout) — réessaie.")
        except requests.exceptions.ConnectionError:
            raise NovAIError("NovAI injoignable — vérifie ta connexion réseau.")
        if resp.status_code >= 400:
            self._handle_http_error(resp, "à la soumission")
        data = resp.json()
        job_id = data.get("id")
        if not job_id:
            raise NovAIError(f"Réponse NovAI sans id de job: {data}")
        return job_id

    def poll(self, job_id: str) -> tuple:
        """Poll le statut du job.

        Returns:
            (status, video_url) — status ∈ {"processing", "succeeded", "failed", ...}
        """
        try:
            resp = requests.get(
                f"{self.base_url}/video/generations/{job_id}",
                headers=self._headers(),
                params={"model": NOVAI_VIDEO_MODEL},
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout:
            raise NovAIError("NovAI ne répond pas (timeout) pendant le polling.")
        except requests.exceptions.ConnectionError:
            raise NovAIError("NovAI injoignable pendant le polling.")
        if resp.status_code == 404:
            raise NovAIError("Job NovAI introuvable (404) — l'API a peut-être purgé le job.")
        if resp.status_code >= 400:
            self._handle_http_error(resp, "au polling")
        data = resp.json()
        status = data.get("status", "processing")
        content = data.get("content") or {}
        video_url = content.get("video_url") or ""
        return status, video_url

    def download(self, url: str, dest_path: str, timeout: float = 300.0) -> str:
        """Télécharge la vidéo générée vers dest_path. Retourne dest_path."""
        try:
            resp = requests.get(url, timeout=timeout, stream=True)
        except requests.exceptions.Timeout:
            raise NovAIError("Téléchargement de la vidéo NovAI: timeout.")
        except requests.exceptions.ConnectionError:
            raise NovAIError("Téléchargement de la vidéo NovAI: réseau injoignable.")
        if resp.status_code >= 400:
            self._handle_http_error(resp, "au téléchargement")
        dest_path = os.path.abspath(dest_path)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                if chunk:
                    f.write(chunk)
        if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
            raise NovAIError("Fichier vidéo NovAI vide après téléchargement.")
        return dest_path

    def generate(
        self,
        prompt: str,
        duration: int = 5,
        dest_path: str = "",
        timeout_s: float = 1800.0,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> str:
        """Soumission → polling → téléchargement. Retourne le chemin local.

        Args:
            prompt: description de la vidéo
            duration: 5 ou 10 secondes (NOVAI_DURATIONS)
            dest_path: chemin de destination du MP4
            timeout_s: délai max global (soumission + polling)
            on_progress: callback (progress 0..1, message) pour l'UI
        """
        if on_progress:
            on_progress(0.05, "Soumission du job NovAI (cogvideox-flash, $0)…")
        job_id = self.submit(prompt=prompt, duration=duration)

        deadline = time.time() + timeout_s
        progress = 0.05
        while True:
            if time.time() > deadline:
                raise NovAIError("Délai d'attente dépassé pour la génération NovAI.")
            status, video_url = self.poll(job_id)
            if status == "succeeded":
                break
            if status == "failed":
                raise NovAIError("La génération NovAI a échoué (job status=failed).")
            # Progression simulée (l'API NovAI n'expose pas de % fin) : on monte
            # lentement vers 90% tant que le job tourne.
            if on_progress:
                progress = min(0.90, progress + 0.02)
                on_progress(progress, "Génération vidéo en cours (NovAI, gratuit)…")
            time.sleep(NOVAI_POLL_INTERVAL)

        if not video_url:
            raise NovAIError("Job NovAI réussi mais sans URL vidéo.")
        if on_progress:
            on_progress(0.92, "Téléchargement de la vidéo…")
        self.download(video_url, dest_path)
        return dest_path
