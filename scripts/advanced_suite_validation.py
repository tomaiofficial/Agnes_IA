# -*- coding: utf-8 -*-
"""Suite de validation incrémentale du pipeline avancé Agnes_IA (7 pré-tests).

Chaque pré-test est autonome, rejouable et cible UNE étape du pipeline avancé.
Les pré-tests 1, 2, 3 et 7 sont locaux (aucun crédit Agnes consommé) ; les
pré-tests 4, 5 et 6 génèrent une vraie vidéo sur Render (~1 à 1,8 crédit chacun).

Usage:
    python scripts/advanced_suite_validation.py --list
    python scripts/advanced_suite_validation.py --test 5          # pré-test isolé
    python scripts/advanced_suite_validation.py --all             # suite complète (bloquante)
    python scripts/advanced_suite_validation.py --test 5 --yes    # validation durée auto (CI)

Le critère de complétion « complété avec succès » des pré-tests 5 et 6 inclut
la validation par l'utilisateur de la durée réelle de la vidéo téléchargée :
en mode interactif, le script affiche la durée mesurée et demande confirmation.

Options:
    --base-url URL    API Render (défaut https://agnes-ia.onrender.com)
    --user-id ID      Header X-User-Id (défaut "")
    --duration N      Durée cible des E2E (défaut 15)
    --out-dir PATH    Dossier de travail local (défaut dossier temp du système)
    --yes             Validation durée automatique (ne demande jamais de confirmation)
    --report PATH     Rapport markdown (défaut ./advanced_suite_report.md)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

# Chemin racine du repo (parent de scripts/) : permet d'importer core.*
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PROMPT = "Un coucher de soleil sur la mer, vagues douces, ambiance paisible"
DEFAULT_BASE_URL = "https://agnes-ia.onrender.com"
POLL_INTERVAL_S = 20
MAX_WAIT_MIN = 16


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------


def find_ffmpeg() -> str:
    """Retourne un binaire ffmpeg utilisable (imageio-ffmpeg, puis PATH)."""
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            # Les modules core appellent "ffmpeg" via subprocess : on l'ajoute au PATH.
            bindir = os.path.dirname(exe)
            if bindir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
            return exe
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    raise RuntimeError("ffmpeg introuvable : installez imageio-ffmpeg ou ffmpeg sur le PATH")


def probe_video(path: str) -> dict:
    """Durée / résolution / fps / audio d'une vidéo via `ffmpeg -i` (stderr)."""
    ffmpeg = find_ffmpeg()
    r = subprocess.run([ffmpeg, "-i", path], capture_output=True, text=True)
    err = r.stderr or ""
    info = {"path": path, "duration_s": None, "width": None, "height": None,
            "fps": None, "audio": False, "video": False}
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err)
    if m:
        info["duration_s"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"(\d{2,5})x(\d{2,5})", err)
    if m:
        info["width"], info["height"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", err)
    if m:
        info["fps"] = float(m.group(1))
    info["video"] = bool(re.search(r"Stream.*Video", err))
    info["audio"] = bool(re.search(r"Stream.*Audio", err))
    return info


def http_get_json(url: str, user_id: str, timeout: int = 30) -> dict:
    r = requests.get(url, headers={"X-User-Id": user_id}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def create_advanced_task(ctx: dict, duration: int, width: int, height: int,
                         quality: str, extra: dict | None = None) -> str:
    """Crée une tâche avancée multipart ; retourne task_id."""
    data = {
        "prompt": DEFAULT_PROMPT,
        "duration": str(duration),
        "video_width": str(width),
        "video_height": str(height),
        "quality": quality,
        "style": "ultra_realistic",
        "compress": "true",
        "audio_enabled": "true",
        "audio_voice": "fr-FR-DeniseNeural",
        "optimize_prompt": "true",
        "priority": "free",
    }
    if extra:
        data.update({k: ("true" if v is True else "false" if v is False else str(v))
                     for k, v in extra.items()})
    r = requests.post(ctx["base_url"] + "/api/tasks/advanced",
                      headers={"X-User-Id": ctx["user_id"]},
                      data=data, timeout=60)
    r.raise_for_status()
    body = r.json()
    task_id = body.get("task_id")
    if not task_id:
        raise RuntimeError("Création tâche sans task_id: " + str(body))
    return task_id


def wait_task(ctx: dict, task_id: str) -> dict:
    """Poll /api/tasks/{id} jusqu'à completed/failed. Retourne la tâche."""
    deadline = time.time() + MAX_WAIT_MIN * 60
    last = {}
    while time.time() < deadline:
        try:
            last = http_get_json(ctx["base_url"] + f"/api/tasks/{task_id}", ctx["user_id"])
        except Exception as e:
            print(f"    [poll] erreur {e} - reprise dans {POLL_INTERVAL_S}s")
        status = last.get("status")
        print(f"    [{time.strftime('%H:%M:%S')}] status={status} "
              f"message={str(last.get('current_message', ''))[:60]}")
        if status in ("completed", "failed"):
            return last
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"Timeout ({MAX_WAIT_MIN} min) sur la tâche {task_id}")


def download_video(ctx: dict, task_id: str, out_path: str) -> str:
    r = requests.get(ctx["base_url"] + f"/api/video/{task_id}",
                     headers={"X-User-Id": ctx["user_id"]}, timeout=120)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


def ask_user(prompt: str, ctx: dict) -> bool:
    """Validation utilisateur interactive (ou auto si --yes)."""
    if ctx["yes"]:
        return True
    while True:
        ans = input(prompt + " [o/N] ").strip().lower()
        if ans in ("o", "oui", "y", "yes"):
            return True
        if ans in ("", "n", "non", "no"):
            return False


# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------


@dataclass
class TestResult:
    ok: bool
    title: str
    details: list = field(default_factory=list)
    credits: float = 0.0
    requires_user: bool = False

    def __str__(self) -> str:
        tag = "PASS" if self.ok else "FAIL"
        lines = [f"[{tag}] {self.title}", f"    Crédits: {self.credits:.1f}"]
        lines += [f"    - {d}" for d in self.details]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pré-test 1 — Watermark désactivé par défaut (local, 0 crédit)
# ---------------------------------------------------------------------------


def run_pt01(ctx: dict) -> TestResult:
    details = []
    ok = True
    try:
        from core.config import DEFAULT_WATERMARK_ENABLED
    except Exception as e:
        return TestResult(False, "PT1 - Watermark désactivé par défaut",
                          ["Import core.config impossible: " + repr(e)])
    if DEFAULT_WATERMARK_ENABLED is False:
        details.append(f"DEFAULT_WATERMARK_ENABLED=False (core/config.py: {DEFAULT_WATERMARK_ENABLED})")
    else:
        ok = False
        details.append(f"DEFAULT_WATERMARK_ENABLED={DEFAULT_WATERMARK_ENABLED} - attendu False")
    try:
        cfg = http_get_json(ctx["base_url"] + "/api/config", ctx["user_id"])
        wm = cfg.get("watermark_enabled")
        details.append(f"API /api/config watermark_enabled={wm}")
        if wm is not False and wm is not None:
            ok = False
            details.append("Watermark activé côté serveur - attendu désactivé")
    except Exception as e:
        details.append("API /api/config indisponible: " + repr(e) + " (test local uniquement)")
    return TestResult(ok, "PT1 - Watermark désactivé par défaut", details)


# ---------------------------------------------------------------------------
# Pré-test 2 — Postprocess étape 6 : durée exacte (local, 0 crédit)
# ---------------------------------------------------------------------------


def run_pt02(ctx: dict) -> TestResult:
    ffmpeg = find_ffmpeg()
    workdir = Path(ctx["out_dir"]) / "pt02"
    workdir.mkdir(parents=True, exist_ok=True)
    src = str(workdir / "src_2s.mp4")
    pad = str(workdir / "pad_5s.mp4")
    # Vidéo synthétique 2 s
    r = subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15",
                        "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", src],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(src):
        return TestResult(False, "PT2 - Postprocess : durée exacte (pad)",
                          ["Génération source échouée: " + (r.stderr or "")[-300:]])
    from core.video.postprocess import ensure_video_duration

    async def _run() -> str:
        return await ensure_video_duration(src, 5.0, pad)

    try:
        out = asyncio.run(_run())
    except Exception as e:
        return TestResult(False, "PT2 - Postprocess : durée exacte (pad)",
                          ["ensure_video_duration a levé: " + repr(e)])
    info = probe_video(out)
    details = [f"entrée 2,0 s -> sortie {info['duration_s']:.2f} s (cible 5,0 s)",
               "fichier: " + os.path.basename(out)]
    ok = info["duration_s"] is not None and abs(info["duration_s"] - 5.0) <= 0.2
    if not ok:
        details.append(f"Durée {info['duration_s']} != 5,0 s ± 0,2")
    return TestResult(ok, "PT2 - Postprocess : durée exacte (pad)", details)


# ---------------------------------------------------------------------------
# Pré-test 3 — Compression sans casse de durée (local, 0 crédit)
# ---------------------------------------------------------------------------


def run_pt03(ctx: dict) -> TestResult:
    ffmpeg = find_ffmpeg()
    workdir = Path(ctx["out_dir"]) / "pt03"
    workdir.mkdir(parents=True, exist_ok=True)
    src = str(workdir / "src_5s.mp4")
    r = subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15",
                        "-t", "5", "-c:v", "libx264", "-preset", "ultrafast", src],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(src):
        return TestResult(False, "PT3 - Compression sans casse de durée",
                          ["Source échouée: " + (r.stderr or "")[-300:]])
    from core.video.pipeline import AIVideoPipeline

    # pas d'init : _compress n'utilise que le logger
    pipeline = AIVideoPipeline.__new__(AIVideoPipeline)

    async def _run() -> str:
        return await pipeline._compress(src)

    try:
        out = asyncio.run(_run())
    except Exception as e:
        return TestResult(False, "PT3 - Compression sans casse de durée",
                          ["_compress a levé: " + repr(e)])
    before = probe_video(src)
    after = probe_video(out)
    details = [f"durée avant={before['duration_s']:.2f}s après={after['duration_s']:.2f}s",
               f"audio avant={before['audio']} après={after['audio']}",
               "sortie: " + os.path.basename(out)]
    ok = (after["duration_s"] is not None and before["duration_s"] is not None
          and abs(after["duration_s"] - before["duration_s"]) <= 0.2)
    if not ok:
        details.append("Durée altérée par la compression")
    return TestResult(ok, "PT3 - Compression sans casse de durée", details)


# ---------------------------------------------------------------------------
# Pré-test 4 — Audio présent dans la vidéo finale (E2E, ~1 crédit)
# ---------------------------------------------------------------------------


def run_pt04(ctx: dict) -> TestResult:
    try:
        task_id = create_advanced_task(ctx, duration=5, width=768, height=1152,
                                       quality="standard", extra={"audio_enabled": True})
    except Exception as e:
        return TestResult(False, "PT4 - Audio présent dans la vidéo finale",
                          ["Création: " + repr(e)])
    details = ["tâche: " + task_id]
    try:
        task = wait_task(ctx, task_id)
    except Exception as e:
        return TestResult(False, "PT4 - Audio présent dans la vidéo finale",
                          details + ["Attente: " + repr(e)])
    details.append("status: " + str(task.get("status")) + " message: " + str(task.get("current_message", ""))[:60])
    if task.get("status") != "completed":
        return TestResult(False, "PT4 - Audio présent dans la vidéo finale", details)
    out = os.path.join(ctx["out_dir"], f"pt04_{task_id}.mp4")
    try:
        download_video(ctx, task_id, out)
    except Exception as e:
        return TestResult(False, "PT4 - Audio présent dans la vidéo finale",
                          details + ["Download: " + repr(e)])
    info = probe_video(out)
    details.append(f"vidéo {info['width']}x{info['height']} {info['duration_s']:.2f}s audio={info['audio']}")
    ok = info["audio"] is True
    if not ok:
        details.append("Aucune piste audio détectée dans la vidéo servie")
    return TestResult(ok, "PT4 - Audio présent dans la vidéo finale", details, credits=1.0)


# ---------------------------------------------------------------------------
# Pré-test 5 — Durée exacte 15 s (E2E, ~1,8 crédit) + validation utilisateur
# ---------------------------------------------------------------------------


def run_pt05(ctx: dict) -> TestResult:
    target = ctx["duration"]
    try:
        task_id = create_advanced_task(ctx, duration=target, width=1920, height=1080,
                                       quality="full_hd", extra={"compress": True, "audio_enabled": True})
    except Exception as e:
        return TestResult(False, f"PT5 - Durée exacte {target} s (Full HD)",
                          ["Création: " + repr(e)])
    details = ["tâche: " + task_id]
    try:
        task = wait_task(ctx, task_id)
    except Exception as e:
        return TestResult(False, f"PT5 - Durée exacte {target} s (Full HD)",
                          details + ["Attente: " + repr(e)])
    details.append("status: " + str(task.get("status")) + " message: " + str(task.get("current_message", ""))[:60])
    if task.get("status") != "completed":
        return TestResult(False, f"PT5 - Durée exacte {target} s (Full HD)", details)
    out = os.path.join(ctx["out_dir"], f"pt05_{task_id}.mp4")
    try:
        download_video(ctx, task_id, out)
    except Exception as e:
        return TestResult(False, f"PT5 - Durée exacte {target} s (Full HD)",
                          details + ["Download: " + repr(e)])
    info = probe_video(out)
    details.append(f"vidéo {info['width']}x{info['height']} durée={info['duration_s']:.2f}s "
                   f"audio={info['audio']} (cible {target} s)")
    ok = info["duration_s"] is not None and abs(info["duration_s"] - float(target)) <= 0.2
    if not ok:
        details.append(f"Durée {info['duration_s']} != {target} s ± 0,2")
        return TestResult(False, f"PT5 - Durée exacte {target} s (Full HD)", details, credits=1.8)
    # Critère de complétion : validation de la durée réelle par l'utilisateur.
    if not ask_user(f"La durée mesurée est {info['duration_s']:.2f} s sur {target} s. "
                    f"Confirmez-vous la durée réelle de la vidéo téléchargée ({out}) ?", ctx):
        details.append("Validation utilisateur refusée - critère de complétion non rempli")
        return TestResult(False, f"PT5 - Durée exacte {target} s (Full HD)", details, credits=1.8)
    details.append("Validation utilisateur : durée réelle confirmée")
    return TestResult(True, f"PT5 - Durée exacte {target} s (Full HD)", details,
                      credits=1.8, requires_user=True)


# ---------------------------------------------------------------------------
# Pré-test 6 — Mode avancé complet (E2E, ~1,8 crédit) + validation utilisateur
# ---------------------------------------------------------------------------


def run_pt06(ctx: dict) -> TestResult:
    target = ctx["duration"]
    extra = {
        "quality": "full_hd", "compress": True, "audio_enabled": True,
        "optimize_prompt": True, "face_enhance": True, "denoise": True,
        "motion_enhance": False, "hdr": False, "color_correct": True,
        "style": "ultra_realistic", "priority": "free",
    }
    try:
        task_id = create_advanced_task(ctx, duration=target, width=1920, height=1080,
                                       quality="full_hd", extra=extra)
    except Exception as e:
        return TestResult(False, f"PT6 - Mode avancé complet ({target} s Full HD)",
                          ["Création: " + repr(e)])
    details = ["tâche: " + task_id]
    try:
        task = wait_task(ctx, task_id)
    except Exception as e:
        return TestResult(False, f"PT6 - Mode avancé complet ({target} s Full HD)",
                          details + ["Attente: " + repr(e)])
    details.append("status: " + str(task.get("status")) + " message: " + str(task.get("current_message", ""))[:60])
    if task.get("status") != "completed":
        return TestResult(False, f"PT6 - Mode avancé complet ({target} s Full HD)",
                          details, credits=1.8)
    # Pas d'OOM : le serveur doit répondre après la génération.
    try:
        http_get_json(ctx["base_url"] + "/api/health", ctx["user_id"])
        details.append("Serveur toujours vivant après génération (pas d'OOM)")
    except Exception as e:
        details.append("ÉCHEC santé serveur après génération: " + repr(e) + " - possible OOM")
        return TestResult(False, f"PT6 - Mode avancé complet ({target} s Full HD)",
                          details, credits=1.8)
    out = os.path.join(ctx["out_dir"], f"pt06_{task_id}.mp4")
    try:
        download_video(ctx, task_id, out)
    except Exception as e:
        return TestResult(False, f"PT6 - Mode avancé complet ({target} s Full HD)",
                          details + ["Download: " + repr(e)], credits=1.8)
    info = probe_video(out)
    details.append(f"vidéo {info['width']}x{info['height']} durée={info['duration_s']:.2f}s "
                   f"fps={info['fps']} audio={info['audio']} (cible {target} s)")
    ok = (info["duration_s"] is not None and abs(info["duration_s"] - float(target)) <= 0.2
          and (info["width"] or 0) >= 1920 and info["audio"] is True)
    if not ok:
        details.append("Critères vidéo non remplis (durée/résolution/audio)")
        return TestResult(False, f"PT6 - Mode avancé complet ({target} s Full HD)",
                          details, credits=1.8)
    if not ask_user(f"Durée mesurée {info['duration_s']:.2f} s, résolution {info['width']}x{info['height']}, "
                    f"audio présent. Confirmez-vous la qualité réelle de la vidéo ({out}) ?", ctx):
        details.append("Validation utilisateur refusée")
        return TestResult(False, f"PT6 - Mode avancé complet ({target} s Full HD)",
                          details, credits=1.8)
    details.append("Validation utilisateur : vidéo réelle confirmée")
    return TestResult(True, f"PT6 - Mode avancé complet ({target} s Full HD)", details,
                      credits=1.8, requires_user=True)


# ---------------------------------------------------------------------------
# Pré-test 7 — Bandeau « app en cours de finition » limité à 2 affichages (local)
# ---------------------------------------------------------------------------


def run_pt07(ctx: dict) -> TestResult:
    html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    details = []
    ok = True
    has_banner = 'id="wip-banner"' in html
    details.append(f"#wip-banner présent dans static/index.html: {has_banner}")
    if not has_banner:
        ok = False
    # Affichage #2 : carte « bientôt disponible » de l'onglet Image.
    has_image_card = 'id="form-image"' in html and "bient" in html.lower()
    details.append(f"Carte Image « bientôt disponible » (affichage #2): {has_image_card}")
    if not has_image_card:
        ok = False
    # Note de durée (Full HD 12/15 s) : le texte « durée » + gestion s_duration_note.
    has_note = "s_duration_note" in html and ("dur" in html.lower() or "Dur" in html)
    details.append(f"Note durée (s_duration_note): {has_note}")
    if not has_note:
        ok = False
    # Max 2 affichages : vérifie qu'il n'existe pas d'autre occurrence du bandeau.
    occurrences = len(re.findall(r"wip-banner", html))
    details.append(f"Occurrences de wip-banner dans le HTML: {occurrences} (max 2 attendu)")
    if occurrences > 2:
        ok = False
    if not ok:
        details.append("Un ou plusieurs critères du bandeau non satisfaits")
    return TestResult(ok, "PT7 - Bandeau WIP limité à 2 affichages", details)


# ---------------------------------------------------------------------------
# Registre des pré-tests
# ---------------------------------------------------------------------------

TESTS = [
    (1, "Watermark désactivé par défaut (local)", run_pt01),
    (2, "Postprocess étape 6 : durée exacte pad (local)", run_pt02),
    (3, "Compression sans casse de durée (local)", run_pt03),
    (4, "Audio présent dans la vidéo finale (E2E ~1 crédit)", run_pt04),
    (5, "Durée exacte 15 s Full HD (E2E ~1,8 crédit) + validation utilisateur", run_pt05),
    (6, "Mode avancé complet 15 s Full HD (E2E ~1,8 crédit) + validation utilisateur", run_pt06),
    (7, "Bandeau WIP limité à 2 affichages (local)", run_pt07),
]


def run_one(ctx: dict, num: int) -> TestResult:
    entry = next((t for t in TESTS if t[0] == num), None)
    if entry is None:
        raise SystemExit(f"Pré-test {num} inconnu. Choisir parmi: {[t[0] for t in TESTS]}")
    print(f"\n=== Pré-test {num} — {entry[1]} ===")
    result = entry[2](ctx)
    print(str(result))
    return result


def write_report(ctx: dict, results: list) -> str:
    path = Path(ctx["report"])
    lines = [
        "# Rapport de validation — pipeline avancé Agnes_IA",
        "",
        f"- Date : {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Base : {ctx['base_url']}",
        f"- Durée cible : {ctx['duration']} s",
        f"- Mode : {'auto (--yes)' if ctx['yes'] else 'interactif (validation utilisateur)'}",
        "",
        "## Résultats",
        "",
        "| # | Pré-test | Statut | Détails | Crédits |",
        "|---|----------|--------|---------|---------|",
    ]
    total_credits = 0.0
    all_ok = True
    for num, title, res in results:
        total_credits += res.credits
        all_ok = all_ok and res.ok
        lines.append(f"| {num} | {title} | {'OK PASS' if res.ok else 'KO FAIL'} | "
                     f"{'; '.join(res.details)} | {res.credits:.1f} |")
    lines.append("")
    lines.append(f"**Bilan : {'SUCCÈS' if all_ok else 'ÉCHEC'} — "
                 f"{sum(1 for _, _, r in results if r.ok)}/{len(results)} pré-tests, "
                 f"{total_credits:.1f} crédits Agnes consommés.**")
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def main() -> None:
    # Console Windows : forcer l'UTF-8 (évite UnicodeEncodeError cp1252).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Suite de validation incrémentale du pipeline avancé Agnes_IA")
    ap.add_argument("--test", type=int, default=None, help="Numéro de pré-test isolé")
    ap.add_argument("--all", action="store_true", help="Exécuter les 7 pré-tests dans l'ordre")
    ap.add_argument("--list", action="store_true", help="Lister les pré-tests")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--user-id", default="")
    ap.add_argument("--duration", type=int, default=15)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--yes", action="store_true", help="Validation durée automatique (CI)")
    ap.add_argument("--report", default="advanced_suite_report.md")
    args = ap.parse_args()

    if args.list or not (args.test or args.all):
        print("Pré-tests disponibles :")
        for num, title, _ in TESTS:
            print(f"  {num}. {title}")
        if args.list:
            return
        print("\nUsage : --test N (isolé) ou --all (suite bloquante), --list pour lister.")
        return

    find_ffmpeg()  # échoue tôt si ffmpeg manquant
    out_dir = args.out_dir or tempfile.mkdtemp(prefix="agnes_suite_")
    os.makedirs(out_dir, exist_ok=True)
    ctx = {
        "base_url": args.base_url.rstrip("/"),
        "user_id": args.user_id,
        "duration": args.duration,
        "out_dir": out_dir,
        "yes": args.yes,
        "report": args.report,
    }

    results: list = []
    if args.test:
        res = run_one(ctx, args.test)
        results.append((args.test, next(t[1] for t in TESTS if t[0] == args.test), res))
    else:
        for num, title, fn in TESTS:
            print(f"\n=== Pré-test {num} — {title} ===")
            res = fn(ctx)
            print(str(res))
            results.append((num, title, res))
            if not res.ok:
                print(f"\nSUITE INTERROMPUE : le pré-test {num} a échoué. "
                      f"Corrigez puis relancez --test {num} (ou --all).")
                break

    report = write_report(ctx, results)
    print(f"\nRapport écrit : {report}")
    ok_count = sum(1 for _, _, r in results if r.ok)
    print(f"Bilan : {ok_count}/{len(results)} pré-tests PASS.")
    if ok_count != len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
