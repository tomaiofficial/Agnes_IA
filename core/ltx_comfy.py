"""
core/ltx_comfy.py — Moteur LTX-2.3 via un pod ComfyUI distant (v9.0)

Principe : Agnes_IA ne peut pas exécuter LTX-2.3 (12–24 Go VRAM requis) sur
Render. Le module envoie un workflow API ComfyUI à un pod GPU loué à l'heure
(RunPod / Vast.ai, URL configurée via la variable d'environnement
`LTX_COMFY_URL`, ex. `https://xxxx-8188.proxy.runpod.net`), poll le history
toutes les 5 s, télécharge le MP4 généré et le dépose dans le working_dir
de la tâche (réutilisé ensuite par GET /api/video/{id}).

Le workflow embarqué est l'aplatissement fidèle du workflow officiel
"LTX-2.3 Text to Video" de ComfyUI (Template Library → Video → LTX-2.3 T2V) :
double sampling (basse résolution 640×360 → upscale latent ×2 → haute
résolution 1280×720) + audio généré par le modèle (VAE audio) → MP4 avec son.

Surcharge : si un fichier `ltx_workflow_api.json` existe à la racine du repo,
il remplace le workflow embarqué (utile si les noms de fichiers de modèles
diffèrent ou si l'utilisateur veut un workflow personnalisé). Les placeholders
`__PROMPT__` et `__SEED__` y sont remplacés si présents.
"""

import json
import logging
import os
import re
import time
from typing import Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════
# Constantes du workflow officiel LTX-2.3 T2V
# ═══════════════════════════════════════════════════

LTX_CKPT = "ltx-2.3-22b-dev-fp8.safetensors"
LTX_LORA_DISTILLED = "ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors"
LTX_TEXT_ENCODER = "gemma_3_12B_it_fp4_mixed.safetensors"
LTX_UPSCALER = "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"
LTX_DEFAULT_NEGATIVE = "pc game, console game, video game, cartoon, childish, ugly"
LTX_FPS = 25
LTX_MAX_VIDEO_BYTES = 200 * 1024 * 1024  # 200 Mo (pod → Agnes, pas via Render)

# Noms d'inputs API exacts vérifiés dans le code ComfyUI
# (comfy_extras/nodes_lt_audio.py + schémas du workflow officiel).
_DEFAULT_WORKFLOW: Dict = {
    # ── Chargement des modèles ─────────────────────────────
    "1": {"class_type": "CheckpointLoaderSimple",
          "inputs": {"ckpt_name": LTX_CKPT}},
    "2": {"class_type": "LoraLoaderModelOnly",
          "inputs": {"model": ["1", 0], "lora_name": LTX_LORA_DISTILLED,
                     "strength_model": 0.5}},
    "3": {"class_type": "LTXAVTextEncoderLoader",
          "inputs": {"text_encoder": LTX_TEXT_ENCODER, "ckpt_name": LTX_CKPT,
                     "device": "default"}},
    # ── Prompt (positif / négatif, sans "prompt enhance") ───
    "4": {"class_type": "CLIPTextEncode",
          "inputs": {"clip": ["3", 0], "text": "__PROMPT__"}},
    "5": {"class_type": "CLIPTextEncode",
          "inputs": {"clip": ["3", 0], "text": "__NEGATIVE__"}},
    "6": {"class_type": "LTXVConditioning",
          "inputs": {"positive": ["4", 0], "negative": ["5", 0],
                     "frame_rate": LTX_FPS}},
    "7": {"class_type": "LTXVCropGuides",
          "inputs": {"positive": ["6", 0], "negative": ["6", 1],
                     "latent": ["8", 0]}},
    # ── Latents basse résolution (w/2 × h/2, length = durée×fps+1) ──
    "8": {"class_type": "EmptyLTXVLatentVideo",
          "inputs": {"width": "__LATENT_W__", "height": "__LATENT_H__",
                     "length": "__LENGTH__", "batch_size": 1}},
    "13": {"class_type": "LTXVAudioVAELoader",
           "inputs": {"ckpt_name": LTX_CKPT}},
    "9": {"class_type": "LTXVEmptyLatentAudio",
          "inputs": {"audio_vae": ["13", 0], "frames_number": "__LENGTH__",
                     "frame_rate": LTX_FPS, "batch_size": 1}},
    "10": {"class_type": "LTXVConcatAVLatent",
           "inputs": {"video_latent": ["8", 0], "audio_latent": ["9", 0]}},
    # ── Sampler basse résolution ────────────────────────────
    "11": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
    "12": {"class_type": "ManualSigmas",
           "inputs": {"sigmas": "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"}},
    "14": {"class_type": "RandomNoise",
           "inputs": {"noise_seed": "__SEED__", "noise_mode": "randomize"}},
    "15": {"class_type": "CFGGuider",
           "inputs": {"model": ["2", 0], "positive": ["7", 0],
                      "negative": ["7", 1], "cfg": 1.0}},
    "16": {"class_type": "SamplerCustomAdvanced",
           "inputs": {"noise": ["14", 0], "guider": ["15", 0],
                      "sampler": ["11", 0], "sigmas": ["12", 0],
                      "latent_image": ["10", 0]}},
    "17": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["16", 0]}},
    # ── Upscale latent ×2 ───────────────────────────────────
    "18": {"class_type": "LatentUpscaleModelLoader",
           "inputs": {"model_name": LTX_UPSCALER}},
    "19": {"class_type": "LTXVLatentUpsampler",
           "inputs": {"samples": ["17", 0], "upscale_model": ["18", 0],
                      "vae": ["1", 2]}},
    "20": {"class_type": "LTXVConcatAVLatent",
           "inputs": {"video_latent": ["19", 0], "audio_latent": ["17", 1]}},
    # ── Sampler haute résolution ────────────────────────────
    "21": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
    "22": {"class_type": "ManualSigmas",
           "inputs": {"sigmas": "0.85, 0.7250, 0.4219, 0.0"}},
    "23": {"class_type": "RandomNoise",
           "inputs": {"noise_seed": 42, "noise_mode": "fixed"}},
    "24": {"class_type": "CFGGuider",
           "inputs": {"model": ["2", 0], "positive": ["7", 0],
                      "negative": ["7", 1], "cfg": 1.0}},
    "25": {"class_type": "SamplerCustomAdvanced",
           "inputs": {"noise": ["23", 0], "guider": ["24", 0],
                      "sampler": ["21", 0], "sigmas": ["22", 0],
                      "latent_image": ["20", 0]}},
    "26": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["25", 0]}},
    # ── Décodage (image + audio) ────────────────────────────
    "27": {"class_type": "VAEDecodeTiled",
           "inputs": {"samples": ["26", 0], "vae": ["1", 2],
                      "tile_size": 768, "overlap": 64,
                      "tile_size_short": 4096, "max_tiles": 4}},
    "28": {"class_type": "LTXVAudioVAEDecode",
           "inputs": {"samples": ["26", 1], "audio_vae": ["13", 0]}},
    "29": {"class_type": "CreateVideo",
           "inputs": {"images": ["27", 0], "audio": ["28", 0],
                      "fps": float(LTX_FPS), "bit_depth": 8}},
    # ── Sortie MP4 ──────────────────────────────────────────
    "30": {"class_type": "SaveVideo",
           "inputs": {"video": ["29", 0], "filename_prefix": "video/agnes_ltx",
                      "format": "auto", "codec": {"codec": "auto", "encoding": {}}}},
}

_LT_WORKFLOW_FILE = "ltx_workflow_api.json"


def _repo_root() -> str:
    """Racine du dépôt (là où vit server.py)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_override_workflow() -> Optional[Dict]:
    """Charge `ltx_workflow_api.json` (racine du repo) s'il existe."""
    for path in (
        os.path.join(_repo_root(), _LT_WORKFLOW_FILE),
        os.path.join(os.getcwd(), _LT_WORKFLOW_FILE),
    ):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[LTX] Fichier {path} illisible, workflow embarqué utilisé: {e}")
    return None


def build_ltx_workflow(
    prompt: str,
    duration: int = 5,
    video_width: int = 1280,
    video_height: int = 720,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Dict:
    """Construit le workflow API ComfyUI pour une génération T2V LTX-2.3.

    - `length` = durée × 25 fps + 1 (formule du workflow officiel)
    - Latent = (largeur/2, hauteur/2) arrondi à un multiple de 32 ;
      la sortie finale est ~2× (ex. 1280×720 pour une demande 1280×720).
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Prompt vide")
    seed = int(seed) if seed is not None else int(time.time()) % (2 ** 31)
    negative = (negative_prompt or "").strip() or LTX_DEFAULT_NEGATIVE

    latent_w = max(32, (max(int(video_width), 64) // 2) // 32 * 32)
    latent_h = max(32, (max(int(video_height), 64) // 2) // 32 * 32)
    length = int(duration) * LTX_FPS + 1

    override = _load_override_workflow()
    base = override if override is not None else _DEFAULT_WORKFLOW

    if override is not None:
        # Workflow personnalisé : remplacement des placeholders si présents.
        raw = json.dumps(base, ensure_ascii=False)
        raw = raw.replace("__PROMPT__", json.dumps(prompt, ensure_ascii=False)[1:-1])
        raw = raw.replace("__NEGATIVE__", json.dumps(negative, ensure_ascii=False)[1:-1])
        raw = raw.replace("__SEED__", str(seed))
        raw = raw.replace("__LENGTH__", str(length))
        raw = raw.replace("__LATENT_W__", str(latent_w))
        raw = raw.replace("__LATENT_H__", str(latent_h))
        try:
            return json.loads(raw)
        except Exception as e:
            raise ValueError(f"ltx_workflow_api.json invalide après substitution: {e}")

    workflow = json.loads(json.dumps(base))
    workflow["4"]["inputs"]["text"] = prompt
    workflow["5"]["inputs"]["text"] = negative
    workflow["8"]["inputs"]["width"] = latent_w
    workflow["8"]["inputs"]["height"] = latent_h
    workflow["8"]["inputs"]["length"] = length
    workflow["9"]["inputs"]["frames_number"] = length
    workflow["14"]["inputs"]["noise_seed"] = seed
    return workflow


# ═══════════════════════════════════════════════════
# Client HTTP vers le pod ComfyUI
# ═══════════════════════════════════════════════════


class LtxComfyError(Exception):
    """Erreur utilisateur lisible (affichée telle quelle dans l'UI)."""


class LtxComfyClient:
    """Client minimal de l'API HTTP de ComfyUI (endpoints /prompt, /history, /view)."""

    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.timeout = timeout
        if not self.base_url:
            raise LtxComfyError("URL du pod LTX manquante (LTX_COMFY_URL)")

    # ── helpers ─────────────────────────────────────────────

    def _get(self, path: str, params: Optional[Dict] = None, timeout: Optional[float] = None):
        try:
            resp = requests.get(
                f"{self.base_url}{path}", params=params,
                timeout=timeout or self.timeout,
            )
        except requests.exceptions.Timeout:
            raise LtxComfyError("Le pod LTX ne répond pas (timeout) — pod en cours de démarrage ?")
        except requests.exceptions.ConnectionError:
            raise LtxComfyError(
                "Pod LTX injoignable — vérifie qu'il est DÉMARRÉ sur RunPod/Vast.ai "
                "et que l'URL LTX_COMFY_URL (proxy 8188) est correcte."
            )
        return resp

    def _post_json(self, path: str, payload: Dict, timeout: Optional[float] = None):
        try:
            resp = requests.post(
                f"{self.base_url}{path}", json=payload,
                timeout=timeout or self.timeout,
            )
        except requests.exceptions.Timeout:
            raise LtxComfyError("Le pod LTX ne répond pas (timeout) — pod en cours de démarrage ?")
        except requests.exceptions.ConnectionError:
            raise LtxComfyError(
                "Pod LTX injoignable — vérifie qu'il est DÉMARRÉ sur RunPod/Vast.ai "
                "et que l'URL LTX_COMFY_URL (proxy 8188) est correcte."
            )
        if resp.status_code == 400:
            detail = ""
            try:
                detail = resp.json().get("detail") or resp.json().get("error") or resp.text
            except Exception:
                detail = resp.text[:400]
            raise LtxComfyError(
                "ComfyUI a rejeté le workflow. Détail : "
                f"{detail[:600]}\nAstuce : colle le JSON de ton workflow "
                f"(Menu → Export (API)) dans ltx_workflow_api.json à la racine du repo."
            )
        if resp.status_code == 503:
            raise LtxComfyError("Le pod LTX est en cours de démarrage (503) — réessaie dans ~1 min.")
        if resp.status_code >= 500:
            raise LtxComfyError(f"Erreur pod LTX (HTTP {resp.status_code}).")
        return resp

    # ── endpoints ───────────────────────────────────────────

    def ping(self) -> Optional[Dict]:
        """Vérifie que le pod répond. Retourne /system_stats ou None."""
        try:
            resp = self._get("/system_stats", timeout=10)
            if resp.status_code != 200:
                return None
            return resp.json()
        except LtxComfyError:
            return None

    def submit(self, workflow: Dict) -> str:
        """POST /prompt → prompt_id."""
        resp = self._post_json("/prompt", {"prompt": workflow}, timeout=60)
        try:
            data = resp.json()
        except Exception:
            raise LtxComfyError("Réponse du pod LTX illisible après soumission.")
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise LtxComfyError(
                f"Soumission refusée par ComfyUI : {str(data)[:300]}"
            )
        logger.info(f"[LTX] Prompt soumis: {prompt_id}")
        return prompt_id

    def poll_history(
        self,
        prompt_id: str,
        timeout_s: float = 1800.0,
        interval_s: float = 5.0,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> Dict:
        """Poll GET /history/{prompt_id} jusqu'à completion ou erreur."""
        start = time.time()
        while time.time() - start < timeout_s:
            resp = self._get(f"/history/{prompt_id}", timeout=15)
            if resp.status_code != 200:
                raise LtxComfyError(f"Erreur de polling (HTTP {resp.status_code}).")
            try:
                hist = resp.json()
            except Exception:
                hist = {}
            entry = hist.get(prompt_id)
            if entry is None:
                # Pas encore visible : le pod peut être occupé à charger les modèles.
                elapsed = int(time.time() - start)
                if on_progress:
                    on_progress(0.1, f"Chargement des modèles sur le pod… ({elapsed}s)")
                time.sleep(interval_s)
                continue
            status = entry.get("status", "running")
            if status == "success":
                return entry
            if status == "error":
                messages = entry.get("messages") or []
                detail = ""
                for msg in messages:
                    if isinstance(msg, (list, tuple)) and len(msg) >= 2:
                        detail += f"{msg[0]}: {msg[1]}"
                    else:
                        detail += str(msg)
                raise LtxComfyError(f"Échec de la génération sur le pod : {detail[:500]}")
            # running
            elapsed = int(time.time() - start)
            if on_progress:
                on_progress(0.2, f"Génération vidéo sur le pod… ({elapsed}s écoulées)")
            time.sleep(interval_s)
        raise LtxComfyError(
            f"Timeout après {int(timeout_s)}s — génération toujours en cours. "
            "Le pod est peut-être trop lent (GPU faible) ; vérifie le ComfyUI du pod."
        )

    def _extract_video_file(self, history: Dict) -> Optional[Dict]:
        """Trouve l'output vidéo (SaveVideo → clé 'videos')."""
        outputs = history.get("outputs") or {}
        for node_id, out in outputs.items():
            videos = out.get("videos") or []
            if videos:
                v = videos[0]
                if v.get("filename"):
                    return {
                        "filename": v["filename"],
                        "subfolder": v.get("subfolder", ""),
                        "type": v.get("type", "output"),
                    }
        return None

    def download_video(self, prompt_id: str, dest_path: str, history: Optional[Dict] = None) -> str:
        """Télécharge le MP4 généré vers dest_path. Retourne dest_path."""
        hist = history or self.poll_history(prompt_id)
        video = self._extract_video_file(hist)
        if video is None:
            raise LtxComfyError(
                "Génération réussie mais aucun fichier vidéo trouvé dans les outputs."
            )
        params = {
            "filename": video["filename"],
            "subfolder": video["subfolder"],
            "type": video["type"],
        }
        resp = self._get("/view", params=params, timeout=60)
        if resp.status_code != 200:
            raise LtxComfyError(f"Téléchargement de la vidéo refusé (HTTP {resp.status_code}).")
        if len(resp.content) > LTX_MAX_VIDEO_BYTES:
            raise LtxComfyError("Vidéo générée > 200 Mo (trop volumineuse).")
        if not resp.content:
            raise LtxComfyError("Vidéo téléchargée vide.")
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        logger.info(f"[LTX] Vidéo téléchargée ({len(resp.content)} o) → {dest_path}")
        return dest_path

    def generate(
        self,
        workflow: Dict,
        dest_path: str,
        timeout_s: float = 1800.0,
        interval_s: float = 5.0,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> str:
        """Soumission + polling + téléchargement, de bout en bout."""
        prompt_id = self.submit(workflow)
        history = self.poll_history(
            prompt_id, timeout_s=timeout_s, interval_s=interval_s,
            on_progress=on_progress,
        )
        if on_progress:
            on_progress(0.95, "Vidéo générée — téléchargement…")
        return self.download_video(prompt_id, dest_path, history=history)
