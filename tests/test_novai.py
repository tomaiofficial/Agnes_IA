"""tests/test_novai.py — Tests mockés du moteur NovAI (v9.1).

Le client NovAI (core/api/novai.py) appelle l'API publique de la passerelle
https://aiapi-pro.com/v1. Aucun réseau dans ces tests : les appels requests
sont remplacés par des faux objets Response via monkeypatch, donc la suite
tourne hors-ligne et sans consommer le crédit gratuit du compte de test.

Couverture : submit, poll, download, generate (flux complet avec progression),
et messages d'erreur typés (401/403/429/404).
"""

import io
import os

import pytest

from core.api.novai import NOVAI_VIDEO_MODEL, NovAIError, NovAIVideoClient


class FakeResponse:
    """Mini-doublure de requests.Response (status_code, json, text, iter_content)."""

    def __init__(self, status_code=200, payload=None, text="", chunks=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or str(self._payload)
        self._chunks = chunks if chunks is not None else [b"fake-mp4-bytes"]

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=1):
        for c in self._chunks:
            yield c


@pytest.fixture
def client():
    return NovAIVideoClient(api_key="test-key", base_url="https://aiapi-pro.com/v1")


def _patch_post(monkeypatch, response):
    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == "https://aiapi-pro.com/v1/video/generations", url
        assert headers["Authorization"] == "Bearer test-key", headers
        assert json["model"] == NOVAI_VIDEO_MODEL
        return response

    monkeypatch.setattr("core.api.novai.requests.post", fake_post)


def _patch_get(monkeypatch, responses):
    """responses: dict {url_suffix: FakeResponse} — retourne dans l'ordre du poll."""
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        if url.endswith("/video/generations/job_1"):
            resp = responses["job_1"][min(calls["n"], len(responses["job_1"]) - 1)]
            calls["n"] += 1
            return resp
        if url == "https://cdn.novai.test/video.mp4":
            return responses["download"]
        raise AssertionError(f"URL inattendue: {url}")

    monkeypatch.setattr("core.api.novai.requests.get", fake_get)


# ══════════════════════════════════════════════════════════════════
# submit
# ══════════════════════════════════════════════════════════════════

def test_submit_ok(monkeypatch, client):
    _patch_post(monkeypatch, FakeResponse(200, {"id": "job_1", "model": NOVAI_VIDEO_MODEL}))
    assert client.submit("un chat dans un jardin", duration=5) == "job_1"


def test_submit_missing_id(monkeypatch, client):
    _patch_post(monkeypatch, FakeResponse(200, {"status": "queued"}))
    with pytest.raises(NovAIError, match="sans id de job"):
        client.submit("test")


@pytest.mark.parametrize("status,msg", [
    (401, "Clé API NovAI invalide"),
    (403, "Accès NovAI refusé"),
    (429, "Limite NovAI atteinte"),
    (500, "Erreur NovAI"),
])
def test_submit_http_errors(monkeypatch, client, status, msg):
    _patch_post(monkeypatch, FakeResponse(status, {"error": "boom"}, text="boom"))
    with pytest.raises(NovAIError, match=msg):
        client.submit("test")


def test_init_requires_api_key():
    # La clé manquante est détectée dès la construction du client.
    with pytest.raises(NovAIError, match="Clé API NovAI manquante"):
        NovAIVideoClient(api_key="", base_url="https://aiapi-pro.com/v1")


# ══════════════════════════════════════════════════════════════════
# poll
# ══════════════════════════════════════════════════════════════════

def test_poll_processing_then_succeeded(monkeypatch, client):
    _patch_get(monkeypatch, {
        "job_1": [
            FakeResponse(200, {"status": "processing", "content": {}}),
            FakeResponse(200, {"status": "succeeded", "content": {"video_url": "https://cdn.novai.test/video.mp4"}}),
        ],
        "download": FakeResponse(200),
    })
    status, url = client.poll("job_1")
    assert status == "processing"
    status, url = client.poll("job_1")
    assert status == "succeeded"
    assert url == "https://cdn.novai.test/video.mp4"


def test_poll_404(monkeypatch, client):
    _patch_get(monkeypatch, {"job_1": [FakeResponse(404, {"detail": "nope"})], "download": FakeResponse(200)})
    with pytest.raises(NovAIError, match="introuvable"):
        client.poll("job_1")


# ══════════════════════════════════════════════════════════════════
# generate (flux complet : submit → poll × N → download)
# ══════════════════════════════════════════════════════════════════

def test_generate_full_flow(monkeypatch, client, tmp_path):
    _patch_post(monkeypatch, FakeResponse(200, {"id": "job_1"}))
    _patch_get(monkeypatch, {
        "job_1": [FakeResponse(200, {"status": "processing"})] * 3
               + [FakeResponse(200, {"status": "succeeded", "content": {"video_url": "https://cdn.novai.test/video.mp4"}})],
        "download": FakeResponse(200, chunks=[b"MP4" * 100]),
    })

    dest = os.path.join(str(tmp_path), "out", "novai_final.mp4")
    progress = []

    result = client.generate("chat qui joue", duration=5, dest_path=dest,
                             timeout_s=300, on_progress=lambda p, m: progress.append(p))

    assert result == os.path.abspath(dest)
    assert os.path.exists(result)
    assert os.path.getsize(result) > 0
    with open(result, "rb") as f:
        assert f.read().startswith(b"MP4")
    # La progression couvre la soumission → le poll → le téléchargement
    assert 0 < min(progress) <= max(progress) <= 1.0


def test_generate_failed_status(monkeypatch, client, tmp_path):
    _patch_post(monkeypatch, FakeResponse(200, {"id": "job_1"}))
    _patch_get(monkeypatch, {
        "job_1": [FakeResponse(200, {"status": "failed", "content": {"error": "prompt rejeté"}})],
        "download": FakeResponse(200),
    })
    with pytest.raises(NovAIError, match="a échoué"):
        client.generate("test", dest_path=str(tmp_path / "x.mp4"), timeout_s=60)


def test_generate_timeout(monkeypatch, client, tmp_path):
    _patch_post(monkeypatch, FakeResponse(200, {"id": "job_1"}))
    _patch_get(monkeypatch, {
        "job_1": [FakeResponse(200, {"status": "processing"})],
        "download": FakeResponse(200),
    })
    # timeout_s très court → poll unique puis dépassement
    with pytest.raises(NovAIError, match="Délai d'attente dépassé"):
        client.generate("test", dest_path=str(tmp_path / "x.mp4"), timeout_s=0.01)


def test_generate_empty_download(monkeypatch, client, tmp_path):
    _patch_post(monkeypatch, FakeResponse(200, {"id": "job_1"}))
    _patch_get(monkeypatch, {
        "job_1": [FakeResponse(200, {"status": "succeeded", "content": {"video_url": "https://cdn.novai.test/video.mp4"}})],
        "download": FakeResponse(200, chunks=[]),  # fichier vide
    })
    with pytest.raises(NovAIError, match="vide après téléchargement"):
        client.generate("test", dest_path=str(tmp_path / "x.mp4"), timeout_s=60)
