# Guide — LTX-2.3 (Lightricks) sur GPU loué à l'heure

> Génération vidéo IA **ultra-réaliste avec audio + synchronisation labiale en une seule passe**, gratuite et illimitée (licence communautaire LTX-2, < 10 M$ de revenus annuels).
> Cible : **pod GPU à l'heure** (RunPod / Vast.ai) — ta machine (GTX 750 Ti 2 Go) et Render (CPU) ne peuvent pas le faire tourner.
> Statut : 2026-08 · Modèle : `Lightricks/LTX-2.3` (22B DiT, open-source, licence LTX-2 Community).

---

## 1. Pourquoi LTX-2.3

| Point | Détail |
|---|---|
| **Ultra-réaliste** | 22B paramètres, quality photo-réaliste proche de Kling 3.0 |
| **Audio + lip-sync natifs** | Le SEUL modèle open-source qui génère vidéo + audio synchronisés (bouche, ambiance) en une passe — pas de post-synchronisation |
| **Illimité** | Aucun quota : le coût = celui du GPU loué, pas celui de la vidéo |
| **Licence** | LTX-2 Community : libre (y compris commercial) si revenus < 10 M$/an ; restrictions : pas de fine-tune d'autres modèles, pas de produit en concurrence directe avec Lightricks |
| **Portrait 9:16 natif** | Parfait pour TikTok / Reels / YouTube Shorts |

---

## 2. Le principe : pod GPU à l'heure

- Tu loues une machine cloud avec une **RTX 3090 ou 4090 (24 Go)**.
- Tu paies **à l'heure** (≈ 0,30–0,90 $/h), uniquement quand le pod est **allumé**.
- Tu peux éteindre le pod entre deux utilisations → coût réel quasi nul.
- Les modèles (~40–50 Go) sont stockés sur un **volume réseau** qui survit à l'arrêt du pod.

| Fournisseur | Prix indicatif (RTX 3090 / 4090) | Simplicité |
|---|---|---|
| **RunPod** (recommandé) | 0,30–0,50 $/h / 0,60–0,90 $/h | Template ComfyUI prêt à l'emploi, très simple |
| Vast.ai | 20–40 % moins cher | Plus de friction (config manuelle) |

---

## 3. Étape 1 — Créer le pod (RunPod)

1. Crée un compte sur [runpod.io](https://www.runpod.io), ajoute ~5 $ de crédit.
2. Menu **Pods** → **+ New Pod**.
3. **Select Template** → cherche `ComfyUI` → choisis le template officiel (ComfyUI préinstallé).
4. **GPU** : choisis `RTX 3090` (le meilleur rapport prix/qualité) ou `RTX 4090` (plus rapide).
5. **Network Volume** : crée un volume de **60 Go** (persistance des modèles), monté sur `/workspace` (≈ 0,07 $/mois par Go stocké, donc ~4 $/mois).
6. **Deploy**. Attends ~2 min que le pod démarre.
7. Ouvre l'interface ComfyUI via le bouton **Connect → HTTP Service** (port 8188).

---

## 4. Étape 2 — Télécharger les modèles (une seule fois)

Ouvre un terminal dans le pod (bouton **Connect → Terminal**) et exécute :

```bash
cd /workspace/ComfyUI/models

# 1) Checkpoint LTX-2.3 complet en FP8 (~16 Go) — C'EST CELUI du workflow
#    officiel "LTX-2.3 T2V" : il contient aussi l'audio VAE (vidéo + son).
huggingface-cli download Kijai/LTX2.3_comfy \
  ltx-2.3-22b-dev-fp8.safetensors \
  --local-dir checkpoints

# 2) VAE vidéo (TAE, obligatoire)
huggingface-cli download Kijai/LTX2.3_comfy taeltx2_3.safetensors --local-dir vae

# 3) (Si l'audio manque) VAE audio séparé — sinon le checkpoint suffit
huggingface-cli download Kijai/LTX2.3_comfy LTX23_audio_vae_bf16.safetensors --local-dir vae

# 4) Text encoder Gemma 3 12B en FP4 (~9,5 Go — le bon compromis pour 16/24 Go)
huggingface-cli download Comfy-Org/ltx-2 \
  split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors \
  --local-dir text_encoders

# 5) (Optionnel mais conseillé) Upscaler spatial x2 — notez le "-1.1", pas "-1.0"
huggingface-cli download Lightricks/LTX-2.3 \
  ltx-2.3-spatial-upscaler-x2-1.1.safetensors --local-dir latent_upscale_models

# 6) (Optionnel) LoRA distillée — nom EXACT du workflow officiel (génération plus rapide)
huggingface-cli download Lightricks/LTX-2.3 \
  ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors --local-dir loras
```

> ⚠️ Ces 6 noms sont ceux référencés par le workflow embarqué d'Agnes_IA
> (`core/ltx_comfy.py` → `build_ltx_workflow`). Si un fichier diffère sur ton
> pod, copie le workflow exporté (Menu → Export (API)) dans `ltx_workflow_api.json`
> à la racine du repo : Agnes_IA l'utilisera à la place (placeholders
> `__PROMPT__`, `__SEED__`, `__LENGTH__`, `__LATENT_W__`, `__LATENT_H__`).
> Si `huggingface-cli` n'existe pas : `pip install -U "huggingface_hub[cli]"`.
> Les nœuds LTX-2.3 (natif ComfyUI) : vérifie dans **ComfyUI Manager** que tu es à jour, sinon installe `Lightricks/ComfyUI-LTXVideo` (custom nodes officiels).

---

## 5. Étape 3 — Générer ta première vidéo audio-synchronisée

1. Dans ComfyUI, va dans **Template Library → Video** → charge le workflow **LTX-2.3 T2V** (ou glisse le JSON officiel Lightricks dans la fenêtre).
2. Dans les nœuds, sélectionne :
   - Checkpoint : `ltx-2.3-22b-dev-fp8.safetensors` (contient l'audio VAE)
   - Text encoder : `gemma_3_12B_it_fp4_mixed.safetensors`
   - VAE : `taeltx2_3.safetensors`
   - LoRA distillée : `ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors`
   - Upscaler : `ltx-2.3-spatial-upscaler-x2-1.1.safetensors`
3. **Règles du modèle** (sinon erreur) :
   - **Nombre de frames** = multiple de 8 + 1 : `25` (1 s), `121` (5 s), `241` (10 s)…
   - **Résolution** divisible par 32 (ex. 832×480, 480×832 en portrait, 1216×704…)
   - Prompt en anglais, détaillé (sujet, action, caméra, lumière, ambiance sonore).
4. Clique **Queue** et attends : 5 s de clip ≈ **1–3 min** sur RTX 4090, 3–6 min sur RTX 3090.
5. Résultat : un MP4 **avec le son et la bouche synchronisée** directement.

**Variantes de workflows dispo dans le template** : T2V (texte→vidéo), I2V (image→vidéo), **audio natif** (texte→vidéo avec son+lip-sync), FLF2V / IA2V (contrôles), ID-LoRA (personnage cohérent).

---

## 6. Étape 4 — Éteindre le pod (le coût s'arrête)

- Menu **Pods** → ton pod → **Stop**.
- Le volume réseau conserve tes modèles et tes vidéos.
- Au redémarrage, le pod reprend exactement où il en était (tu n'as plus à re-télécharger).

---

## 7. Coûts réels (comparaison avec Kling API)

| Usage | LTX-2.3 sur RTX 3090 louée | Kling 3.0 API |
|---|---|---|
| 1 clip 5 s (avec audio) | ~2 centimes (4 min de GPU @ 0,35 $/h) | 0,42–0,84 $ |
| 10 clips/semaine | ~0,80 $/mois de GPU + ~4 $/mois de stockage | 17–34 $/mois |
| 200 clips/mois | ~3,50 $/mois | ~168–336 $/mois |
| Illimité ? | Oui (tant que le pod tourne) | Non (payant par seconde) |

> Le GPU loué coûte le même prix que tu génères 1 ou 50 clips : **le coût par vidéo tend vers zéro à volume**.

---

## 8. ✅ Brancher le pod dans Agnes_IA (DÉJÀ IMPLÉMENTÉ)

L'intégration est codée (v9.0) : Agnes_IA envoie le workflow API au ComfyUI du pod,
récupère le MP4 (image + son) et l'expose comme une tâche simple classique —
**sans consommer un seul crédit Agnes**.

**1. Sur Render (déploiement)**
- Ajoute la variable d'environnement :
  - `LTX_COMFY_URL` = URL publique de ton pod (bouton **Connect → HTTP Service**,
    port 8188), ex. `https://xyz-8188.proxy.runpod.net` (sans slash final)
- Redéploie (Manual Deploy → Deploy latest commit).

**2. Dans l'UI**
- Le toggle **« ⚡ Moteur LTX-2.3 (pod GPU) »** apparaît dans le formulaire vidéo
  (visible uniquement si `LTX_COMFY_URL` est configuré).
- Activé : mode = Texte → vidéo, durées 5/7/10 s, résolutions
  768×1280 (portrait) / 1280×768 (paysage) / 1024×1024 (carré).
- Désactivé : formulaire Agnes classique (mode avancé, audio TTS, HD…).

**3. Côté serveur**
- `POST /api/tasks/simple-ltx` (multipart, mêmes champs que `/api/tasks/simple`
  moins `mode`/`audio_*`/`quality_boost`) → crée une tâche `simple`, lance la
  génération en arrière-plan : soumission `POST /prompt` → polling
  `GET /history/{prompt_id}` (toutes les 5 s) → téléchargement `GET /view` →
  `working_dir/{dir_name}/ltx_final.mp4` → `final_video_file` → `TASK_COMPLETED`
  (+ sauvegarde Supabase). La progression (connexion pod, chargement modèles,
  génération, encodage) est visible dans l'UI comme pour Agnes.
- Fichiers : `core/ltx_comfy.py` (workflow embarqué + client HTTP),
  `core/config.py` (`get_ltx_comfy_url` / `is_ltx_enabled`), `server.py`
  (`create_simple_ltx_task` + `_run_ltx_with_concurrency` / `_run_ltx`).
- Si les noms de fichiers de modèles diffèrent sur ton pod (ou pour un workflow
  personnalisé) : colle ton workflow **Export (API)** dans `ltx_workflow_api.json`
  à la racine du repo (placeholders `__PROMPT__`, `__SEED__`, `__LENGTH__`,
  `__LATENT_W__`, `__LATENT_H__` remplacés automatiquement).

**4. Vérifications du pod avant de lancer une vidéo**
- Le pod est **démarré** (pas en Stop) — sinon : « Pod LTX injoignable ».
- Les 6 fichiers de modèles (section 4) sont présents — sinon ComfyUI renvoie
  une erreur de chargement affichée dans l'UI.
- Première vidéo : le pod charge les modèles (~1-3 min), puis 5 s de clip ≈
  1–6 min selon le GPU.

---

## 9. Dépannage rapide

| Problème | Cause probable | Solution |
|---|---|---|
| `Out of memory` au chargement | Checkpoint BF16 au lieu de FP8 | Utilise `ltx-2.3-22b-dev-fp8.safetensors` + encoder Gemma FP4 |
| Erreur `text encoder not found` | Mauvais dossier | Vérifie `ComfyUI/models/text_encoders/` et le nom exact du fichier |
| Erreur de dimensions | Frames / résolution non conformes | Frames = multiple de 8 + 1 ; résolution divisible par 32 |
| Nœuds LTX introuvables | ComfyUI obsolète | ComfyUI Manager → Update ; installe `ComfyUI-LTXVideo` |
| Audio absent | Workflow sans Audio VAE | Le checkpoint dev contient l'audio VAE ; sinon charge `LTX23_audio_vae_bf16` |
| Pod injoignable (Agnes_IA) | Pod éteint / URL fausse | Démarre le pod ; vérifie `LTX_COMFY_URL` (proxy 8188) |
| Pod lent | Carte < 24 Go | Reste sur RTX 3090/4090 ; désactive l'upscale 2 étages pour tester |

---

## Références

- Modèle : https://huggingface.co/Lightricks/LTX-2.3
- Licence : https://github.com/Lightricks/LTX-2/blob/main/LICENSE (LTX-2 Community, < 10 M$ gratuit)
- Checkpoints FP8/VAE : https://huggingface.co/Kijai/LTX2.3_comfy
- Text encoder Gemma 3 12B : https://huggingface.co/Comfy-Org/ltx-2 (split_files/text_encoders)
- Workflows officiels ComfyUI : Template Library → Video → LTX-2.3 (ou repo `Lightricks/ComfyUI-LTXVideo`)
- Docs ComfyUI LTX-2.3 : https://docs.comfy.org/tutorials/video/ltx/ltx-2-3
