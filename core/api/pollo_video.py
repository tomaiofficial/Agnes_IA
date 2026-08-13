"""Client officiel Pollo AI Platform.

La clé API reste côté serveur. Les notifications sont vérifiées par HMAC-SHA256
selon la documentation officielle Pollo avant toute mise à jour de tâche.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://pollo.ai/api/platform"


class PolloAPIError(RuntimeError):
    """Erreur normalisée renvoyée par Pollo."""


class PolloVideoAPI:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = (api_key or os.environ.get("POLLO_API_KEY", "")).strip()
        self.base_url = (base_url or os.environ.get("POLLO_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        if not self.api_key:
            raise PolloAPIError("POLLO_API_KEY n'est pas configurée sur le serveur")

    @property
    def headers(self) -> Dict[str, str]:
        return {"X-API-KEY": self.api_key, "Content-Type": "application/json"}

    def create_video_task(self, model: str, input_payload: Dict[str, Any], webhook_url: str = "") -> Dict[str, Any]:
        """Créer une tâche vidéo Pollo avec le schéma officiel /generation/{provider}/{model}."""
        if model == "veo3-1":
            path = "/generation/google/veo3-1"
        elif model == "veo3-1-fast":
            path = "/generation/google/veo3-1-fast"
        else:
            raise PolloAPIError(f"Modèle Pollo non autorisé: {model}")
        payload: Dict[str, Any] = {"input": input_payload, "clientSource": "agnes"}
        if webhook_url:
            payload["webhookUrl"] = webhook_url
        try:
            response = requests.post(
                f"{self.base_url}{path}",
                headers=self.headers,
                json=payload,
                timeout=(20, 90),
            )
        except requests.RequestException as exc:
            raise PolloAPIError(f"Connexion Pollo impossible: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:500]
            raise PolloAPIError(f"Pollo HTTP {response.status_code}: {detail}")
        try:
            data = response.json()
        except ValueError as exc:
            raise PolloAPIError("Réponse Pollo invalide") from exc
        task_id = data.get("taskId") or data.get("task_id")
        if not task_id:
            raise PolloAPIError(f"Pollo n'a pas renvoyé de taskId: {data}")
        return data

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, webhook_id: str, timestamp: str, signature: str, secret: Optional[str] = None) -> bool:
        """Vérifie X-Webhook-Signature avec le secret Base64 de Pollo."""
        secret = (secret or os.environ.get("POLLO_WEBHOOK_SECRET", "")).strip()
        if not secret or not webhook_id or not timestamp or not signature:
            return False
        signed_content = f"{webhook_id}.{timestamp}.".encode("utf-8") + raw_body
        try:
            secret_bytes = base64.b64decode(secret)
        except (ValueError, base64.binascii.Error):
            return False
        expected = base64.b64encode(hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()).decode("ascii")
        return hmac.compare_digest(signature, expected)

    @staticmethod
    def extract_video_url(payload: Dict[str, Any]) -> str:
        """Extraire de façon tolérante l'URL présente dans les callbacks Pollo."""
        candidates = [payload.get("videoUrl"), payload.get("video_url"), payload.get("url")]
        result = payload.get("result")
        if isinstance(result, dict):
            candidates.extend([result.get("videoUrl"), result.get("video_url"), result.get("url")])
            urls = result.get("urls")
            if isinstance(urls, list):
                candidates.extend(urls)
        urls = payload.get("urls")
        if isinstance(urls, list):
            candidates.extend(urls)
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                return candidate
        return ""
