"""tests.test_community_puter — endpoints de publication de vidéos générées côté client.

v8.19 : le front génère la vidéo avec le SDK Puter (Kling/Sora/Veo) puis upload
le fichier sur POST /api/community/videos/publish-external, qui réutilise le
même store communautaire que les tâches Agnes (Vibes).

v8.19.6 : Wan 2.1 via Hugging Face (publish-external-wan) — retiré en v8.20.
v8.20 : PixVerse V6 (publish-external-pixverse) — ajouté puis retiré le même
jour à la demande : plus aucun moteur externe, formulaire simple = Agnes seul.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

import server
from core.storage.local_backend import LocalCommunityStore

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"fake-video-bytes"


@pytest.fixture
def community_client(tmp_path, monkeypatch):
    from core.storage import local_backend as lb

    monkeypatch.setattr(lb, "get_working_dir", lambda: str(tmp_path))
    store = LocalCommunityStore()
    monkeypatch.setattr(server, "get_community_store", lambda: store)
    return TestClient(server.app), store


# ── publish-external (Puter) ──────────────────────────────────────────────

def test_publish_external_requires_prompt_and_video(community_client):
    client, _ = community_client
    # Fichier présent mais prompt manquant → 422
    r = client.post(
        "/api/community/videos/publish-external",
        files={"video": ("a.mp4", FAKE_MP4, "video/mp4")},
    )
    assert r.status_code == 422
    # Prompt présent mais fichier manquant → 400
    r = client.post(
        "/api/community/videos/publish-external",
        data={"prompt": "Un chat qui court"},
    )
    assert r.status_code == 400


def test_publish_external_rejects_non_video(community_client):
    client, _ = community_client
    r = client.post(
        "/api/community/videos/publish-external",
        data={"prompt": "Un chat"},
        files={"video": ("a.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 415


def test_publish_external_roundtrip(community_client):
    client, store = community_client
    r = client.post(
        "/api/community/videos/publish-external",
        data={
            "prompt": "Un chat qui court dans un champ",
            "duration": "5",
            "resolution": "1024x576",
            "engine": "kwaivgi/kling-2.1-master",
        },
        files={"video": ("puter_x.mp4", FAKE_MP4, "video/mp4")},
        headers={"X-User-Id": "u-puter"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["video_id"]
    assert d["video_url"]

    listed = store.list_videos()
    assert listed["total"] == 1
    v = listed["videos"][0]
    assert v["user_id"] == "u-puter"
    assert v["author"] == "Anonyme"
    assert v["duration"] == 5.0
    assert v["resolution"] == "1024x576"
    assert v["prompt"] == "Un chat qui court dans un champ"


def test_publish_external_author_and_delete(community_client):
    client, store = community_client
    r = client.post(
        "/api/community/videos/publish-external",
        data={"prompt": "Océan au coucher du soleil", "author": "Agnes"},
        files={"video": ("puter_y.mp4", FAKE_MP4, "video/mp4")},
        headers={"X-User-Id": "owner-puter"},
    )
    assert r.status_code == 200, r.text
    vid = r.json()["video_id"]
    # Suppression réservée au créateur (403 pour un autre user)
    r = client.delete(f"/api/community/videos/{vid}", headers={"X-User-Id": "someone-else"})
    assert r.status_code == 403
    r = client.delete(f"/api/community/videos/{vid}", headers={"X-User-Id": "owner-puter"})
    assert r.status_code == 200
    assert store.list_videos()["total"] == 0
