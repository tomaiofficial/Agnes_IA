"""tests.test_user_profiles — profils utilisateurs façon TikTok/Instagram.

Couvre : save_profile/get_profile (pseudo/bio/avatar), avatar écrit sur
disque (local) ou dans le bucket (supabase), get_avatar_path, filtrage de
get_user_videos par user_id, et injection de avatar_url dans list_videos.
"""

import os
import tempfile
from types import SimpleNamespace

import pytest

from core.storage.local_backend import LocalCommunityStore
from core.storage.supabase_backend import SupabaseCommunityStore

AVATAR_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-avatar-bytes"  # header PNG + contenu bidon


@pytest.fixture
def tmp_workdir(monkeypatch, tmp_path):
    from core.storage import local_backend as lb
    monkeypatch.setattr(lb, "get_working_dir", lambda: str(tmp_path))
    return str(tmp_path)


def _publish_local(store, user_id="owner-1", author="Alice"):
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"fake-mp4-bytes")
        path = f.name
    try:
        return store.publish(
            task_id="task-x", author=author, prompt="Une jolie vidéo",
            duration=15.0, resolution="768x1152", video_path=path,
            user_id=user_id,
        )
    finally:
        os.remove(path)


# ── Backend local ────────────────────────────────────────────────────────

def test_local_profile_save_get_roundtrip(tmp_workdir):
    store = LocalCommunityStore()
    assert store.get_profile("u1") is None
    store.save_profile("u1", pseudo="Alice", bio="Créatrice de vidéos IA")
    p = store.get_profile("u1")
    assert p["user_id"] == "u1"
    assert p["pseudo"] == "Alice"
    assert p["bio"] == "Créatrice de vidéos IA"
    assert p["avatar_url"] == ""


def test_local_profile_update_keeps_created_at(tmp_workdir):
    store = LocalCommunityStore()
    store.save_profile("u1", pseudo="Alice", bio="Bio 1")
    created = store.get_profile("u1")["created_at"]
    store.save_profile("u1", pseudo="AliceBis", bio="Bio 2")
    p = store.get_profile("u1")
    assert p["pseudo"] == "AliceBis"
    assert p["bio"] == "Bio 2"
    assert p["created_at"] == created
    assert p["updated_at"] >= created


def test_local_avatar_written_to_disk(tmp_workdir):
    store = LocalCommunityStore()
    store.save_profile("u1", pseudo="Alice", avatar_bytes=AVATAR_PNG,
                       avatar_content_type="image/png")
    p = store.get_profile("u1")
    assert p["avatar_url"].endswith(f"/api/community/profiles/u1/avatar")
    path = store.get_avatar_path("u1")
    assert path and os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == AVATAR_PNG


def test_local_avatar_replaced_when_reuploaded(tmp_workdir):
    store = LocalCommunityStore()
    store.save_profile("u1", pseudo="Alice", avatar_bytes=AVATAR_PNG,
                       avatar_content_type="image/png")
    path = store.get_avatar_path("u1")
    assert path and os.path.exists(path)
    store.save_profile("u1", pseudo="Alice", avatar_bytes=b"new-avatar",
                       avatar_content_type="image/png")
    # Même extension → le fichier est réécrit avec le nouveau contenu
    new_path = store.get_avatar_path("u1")
    assert new_path == path
    assert os.path.exists(new_path)
    with open(new_path, "rb") as f:
        assert f.read() == b"new-avatar"


def test_local_get_avatar_path_none_without_profile(tmp_workdir):
    store = LocalCommunityStore()
    assert store.get_avatar_path("ghost") is None


def test_local_get_user_videos_filters_by_user(tmp_workdir):
    store = LocalCommunityStore()
    vid_owner = _publish_local(store, user_id="u1", author="Alice")["video_id"]
    _publish_local(store, user_id="u2", author="Bob")
    res = store.get_user_videos("u1")
    assert res["total"] == 1
    assert res["videos"][0]["id"] == vid_owner
    assert res["videos"][0]["author"] == "Alice"
    assert store.get_user_videos("unknown")["total"] == 0
    assert store.get_user_videos("") == {"videos": [], "total": 0}


def test_local_list_videos_injects_avatar_url(tmp_workdir):
    store = LocalCommunityStore()
    _publish_local(store, user_id="u1", author="Alice")
    store.save_profile("u1", pseudo="Alice", avatar_bytes=AVATAR_PNG,
                       avatar_content_type="image/png")
    listed = store.list_videos(per_page=50)["videos"]
    assert any(v["avatar_url"] == "/api/community/profiles/u1/avatar" for v in listed)


# ── Backend Supabase ─────────────────────────────────────────────────────

def _make_supabase_store(monkeypatch, client):
    import core.storage.supabase_backend as sb
    monkeypatch.setattr(sb, "_get_client", lambda: client)
    store = SupabaseCommunityStore()
    monkeypatch.setattr(store, "_public_url",
                        lambda path: f"https://supabase.example/{path}")
    return store


class _FakeQuery:
    def __init__(self, client, table, result_rows=None):
        self._client = client
        self._table = table
        self._result_rows = result_rows or []
        self._count = None

    def select(self, *cols, **kwargs):
        return self

    def eq(self, key, value):
        self._client.calls.append(("eq", self._table, key, value))
        return self

    def in_(self, key, values):
        self._client.calls.append(("in", self._table, key, values))
        return self

    def order(self, col, desc=False):
        return self

    def limit(self, n):
        return self

    def offset(self, n):
        return self

    def execute(self):
        self._client.calls.append(("execute", self._table))
        return SimpleNamespace(data=self._result_rows,
                               count=getattr(self._client, "_count", None))


class _FakeTable:
    def __init__(self, client, name, rows=None):
        self._client = client
        self._name = name
        self._rows = rows or []

    def select(self, *cols, **kwargs):
        return _FakeQuery(self._client, self._name, self._rows)

    def insert(self, row):
        self._client.calls.append(("insert", self._name, row))
        return _FakeQuery(self._client, self._name)

    def update(self, row):
        self._client.calls.append(("update", self._name, row))
        return _FakeQuery(self._client, self._name)

    def delete(self):
        return _FakeQuery(self._client, self._name)


class _FakeStorage:
    def __init__(self, client):
        self._client = client

    def from_(self, bucket):
        self._client.calls.append(("storage-from", bucket))
        return self

    def upload(self, path, data, opts):
        self._client.calls.append(("storage-upload", path, data, opts))

    def remove(self, paths):
        self._client.calls.append(("storage-remove", paths))


class _FakeClient:
    def __init__(self, tables=None):
        self.tables = tables or {}
        self.calls = []
        self.storage = _FakeStorage(self)

    def table(self, name):
        return _FakeTable(self, name, self.tables.get(name) or [])


def test_supabase_get_profile_none(monkeypatch):
    client = _FakeClient()
    store = _make_supabase_store(monkeypatch, client)
    assert store.get_profile("u1") is None
    assert store.get_profile("") is None


def test_supabase_get_profile_maps_avatar_url(monkeypatch):
    client = _FakeClient({"user_profiles": [{
        "user_id": "u1", "pseudo": "Alice", "bio": "Bio",
        "avatar_path": "avatars/u1.png",
        "created_at": 111.0, "updated_at": 222.0,
    }]})
    store = _make_supabase_store(monkeypatch, client)
    p = store.get_profile("u1")
    assert p["pseudo"] == "Alice"
    assert p["bio"] == "Bio"
    assert p["avatar_url"] == "https://supabase.example/avatars/u1.png"
    assert p["created_at"] == 111.0


def test_supabase_save_profile_inserts_then_updates(monkeypatch):
    client = _FakeClient()  # pas de profil existant
    store = _make_supabase_store(monkeypatch, client)

    # Monkey-patch get_profile pour renvoyer le profil "à jour" (comme le vrai)
    monkeypatch.setattr(store, "get_profile",
                        lambda uid: {"user_id": uid, "pseudo": "Alice",
                                     "bio": "Bio", "avatar_url": "",
                                     "created_at": 1.0, "updated_at": 2.0})
    store.save_profile("u1", pseudo="Alice", bio="Bio")
    assert ("insert", "user_profiles", "u1") in [(c[0], c[1], (c[2] or {}).get("user_id")) for c in client.calls if c[0] in ("insert",)]
    # Les colonnes pseudo/bio passent à l'insert
    inserts = [c for c in client.calls if c[0] == "insert"]
    assert inserts and inserts[0][2]["pseudo"] == "Alice"
    assert inserts[0][2]["bio"] == "Bio"


def test_supabase_save_profile_with_avatar_uploads(monkeypatch):
    client = _FakeClient({"user_profiles": [{
        "user_id": "u1", "pseudo": "Alice", "bio": "", "avatar_path": "",
        "created_at": 1.0, "updated_at": 1.0,
    }]})
    store = _make_supabase_store(monkeypatch, client)
    monkeypatch.setattr(store, "get_profile",
                        lambda uid: {"user_id": uid, "pseudo": "Alice",
                                     "bio": "", "avatar_url": "https://x/avatars/u1.png",
                                     "created_at": 1.0, "updated_at": 2.0})
    store.save_profile("u1", pseudo="Alice", avatar_bytes=AVATAR_PNG,
                       avatar_content_type="image/png")
    uploads = [c for c in client.calls if c[0] == "storage-upload"]
    assert len(uploads) == 1
    assert uploads[0][1] == "avatars/u1.png"
    assert uploads[0][2] == AVATAR_PNG
    updates = [c for c in client.calls if c[0] == "update"]
    assert updates and updates[0][2]["avatar_path"] == "avatars/u1.png"


def test_supabase_get_user_videos_filters(monkeypatch):
    client = _FakeClient({"community_videos": [
        {"id": "v1", "user_id": "u1", "author": "Alice", "prompt": "P",
         "duration": 15.0, "resolution": "768x1152", "published_at": 2.0,
         "storage_path": "videos/v1.mp4"},
        {"id": "v2", "user_id": "u2", "author": "Bob", "prompt": "Q",
         "duration": 15.0, "resolution": "768x1152", "published_at": 1.0,
         "storage_path": "videos/v2.mp4"},
    ]})
    client._count = 1
    store = _make_supabase_store(monkeypatch, client)
    res = store.get_user_videos("u1")
    assert res["total"] == 1
    assert res["videos"][0]["id"] == "v1"
    assert res["videos"][0]["avatar_url"] == ""
    eqs = [c for c in client.calls if c[0] == "eq"]
    assert ("eq", "community_videos", "user_id", "u1") in eqs


def test_supabase_get_avatar_path(monkeypatch):
    client = _FakeClient({"user_profiles": [{
        "user_id": "u1", "avatar_path": "avatars/u1.png",
    }]})
    store = _make_supabase_store(monkeypatch, client)
    assert store.get_avatar_path("u1") == "https://supabase.example/avatars/u1.png"
    client2 = _FakeClient()
    store2 = _make_supabase_store(monkeypatch, client2)
    assert store2.get_avatar_path("ghost") is None
