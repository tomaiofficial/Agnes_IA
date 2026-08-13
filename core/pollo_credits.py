"""Portefeuille de crédits Agnes pour les générations Pollo.

Le stockage est atomique et local par défaut, compatible avec le fallback déjà
utilisé par Agnes quand Supabase est indisponible. Les coûts sont des estimations
configurables Agnes, séparées de la facturation réelle du compte Pollo.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict

LOCK = threading.RLock()
LEDGER_PATH = Path(os.environ.get("AGNES_POLLO_CREDITS_FILE", "data/pollo_credits.json"))
INITIAL_CREDITS = int(os.environ.get("AGNES_INITIAL_CREDITS", "120"))

COSTS = {
    "veo3-1": {"720p": 12, "1080p": 18, "4k": 30},
    "veo3-1-fast": {"720p": 8, "1080p": 12, "4k": 20},
}


def _load() -> Dict[str, Any]:
    try:
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"users": {}}


def _save(data: Dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="pollo-credits-", suffix=".json", dir=str(LEDGER_PATH.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, LEDGER_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _user(data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    users = data.setdefault("users", {})
    return users.setdefault(user_id or "anonymous", {"balance": INITIAL_CREDITS, "reservations": {}})


def estimate(model: str, resolution: str, duration: int = 8, audio: bool = True) -> Dict[str, Any]:
    table = COSTS.get(model, COSTS["veo3-1"])
    base = int(table.get(resolution, table.get("720p", 12)))
    duration_factor = max(1.0, float(duration or 8) / 8.0)
    audio_factor = 1.1 if audio else 1.0
    credits = max(1, int(round(base * duration_factor * audio_factor)))
    return {"credits": credits, "model": model, "resolution": resolution, "duration": duration, "audio": bool(audio), "estimated": True}


def snapshot(user_id: str) -> Dict[str, Any]:
    with LOCK:
        return {"balance": int(_user(_load(), user_id).get("balance", INITIAL_CREDITS)), "currency": "credits"}


def reserve(user_id: str, reservation_id: str, credits: int) -> Dict[str, Any]:
    with LOCK:
        data = _load()
        user = _user(data, user_id)
        if reservation_id in user.setdefault("reservations", {}):
            return {"ok": True, "reservation_id": reservation_id, "credits": credits, "balance": user["balance"]}
        if int(user.get("balance", 0)) < credits:
            return {"ok": False, "balance": int(user.get("balance", 0)), "required": credits}
        user["balance"] -= credits
        user["reservations"][reservation_id] = {"credits": credits, "status": "reserved"}
        _save(data)
        return {"ok": True, "reservation_id": reservation_id, "credits": credits, "balance": user["balance"]}


def link_task(user_id: str, reservation_id: str, task_id: str) -> None:
    with LOCK:
        data = _load()
        user = _user(data, user_id)
        reservation = user.setdefault("reservations", {}).get(reservation_id)
        if reservation:
            reservation["task_id"] = task_id
            _save(data)


def find_by_task(task_id: str) -> Dict[str, str]:
    with LOCK:
        data = _load()
        for user_id, user in data.get("users", {}).items():
            for reservation_id, reservation in user.get("reservations", {}).items():
                if reservation.get("task_id") == task_id:
                    return {"user_id": user_id, "reservation_id": reservation_id}
        return {}


def settle(user_id: str, reservation_id: str, success: bool) -> Dict[str, Any]:
    with LOCK:
        data = _load()
        user = _user(data, user_id)
        reservation = user.setdefault("reservations", {}).get(reservation_id)
        if reservation and reservation.get("status") == "reserved":
            reservation["status"] = "settled" if success else "refunded"
            if not success:
                user["balance"] += int(reservation.get("credits", 0))
            _save(data)
        return {"balance": int(user.get("balance", 0)), "reservation": reservation or {}}
