"""Storyboard Pavo-style : bible visuelle, scènes cohérentes et prompts de plans.

Ce module ne dépend d'aucun fournisseur privé. Il prépare des scènes structurées
que le moteur vidéo Agnes peut ensuite générer une par une.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

GENRE_PROFILES = {
    "comédie": {"tone": "rythme vif, réactions expressives, timing comique et chute claire", "camera": "travelling léger et plans rapprochés sur les réactions"},
    "cinéma": {"tone": "mise en scène dramatique, silence maîtrisé et émotion réaliste", "camera": "travelling cinématographique, profondeur de champ et plans larges"},
    "action": {"tone": "énergie contrôlée, mouvement lisible et tension progressive", "camera": "caméra portée stabilisée, plans dynamiques et suivi du sujet"},
    "horreur": {"tone": "ambiance inquiétante, tension lente et révélation progressive", "camera": "mouvements lents, ombres profondes et cadrages partiellement obstrués"},
    "romance": {"tone": "intimité naturelle, regards subtils et émotion chaleureuse", "camera": "gros plans doux, lumière dorée et travelling lent"},
    "science-fiction": {"tone": "échelle futuriste, technologie crédible et émerveillement", "camera": "plans architecturaux, néons volumétriques et mouvement orbital"},
}


def _clean(value: str, fallback: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return (text[:limit] or fallback)


def build_storyboard(payload: dict[str, Any]) -> dict[str, Any]:
    title = _clean(payload.get("title"), "Mini-film Agnes")
    premise = _clean(payload.get("premise"), "Une rencontre inattendue change la journée du personnage principal.", 1000)
    genre = _clean(payload.get("genre"), "cinéma", 40).lower()
    profile = GENRE_PROFILES.get(genre, GENRE_PROFILES["cinéma"])
    try:
        count = max(2, min(8, int(payload.get("scene_count", 4))))
    except (TypeError, ValueError):
        count = 4
    try:
        duration = max(5, min(15, int(payload.get("duration", 7))))
    except (TypeError, ValueError):
        duration = 7

    lead = _clean(payload.get("character"), "Alex, 30 ans, visage expressif, vêtements cohérents", 300)
    location = _clean(payload.get("location"), "un quartier urbain réaliste au coucher du soleil", 300)
    visual_bible = {
        "lead_character": lead,
        "wardrobe": "mêmes vêtements, mêmes couleurs et mêmes accessoires dans chaque plan",
        "face_and_body": "visage, âge, coiffure, silhouette et proportions identiques",
        "world": location,
        "style": "photorealistic, cinematic, natural motion, coherent identity",
        "negative": "identity drift, face change, wardrobe change, extra fingers, flicker, morphing, blur, subtitles",
    }
    beats = [
        ("Ouverture", "présente le personnage et le lieu avec un détail visuel mémorable"),
        ("Déclencheur", "introduit l'événement qui lance l'action"),
        ("Escalade", "fait monter l'enjeu avec une réaction claire du personnage"),
        ("Résolution", "offre une conclusion visuelle satisfaisante et une dernière image forte"),
    ]
    scenes = []
    for index in range(count):
        label, beat = beats[index] if index < len(beats) else (f"Plan {index + 1}", "prolonge l'action en respectant la continuité")
        prompt = (
            f"{label} du mini-film {title}. {premise} "
            f"Personnage principal : {lead}. Lieu : {location}. "
            f"Action de ce plan : {beat}. Genre : {genre}. Ton : {profile['tone']}. "
            f"Caméra : {profile['camera']}. Durée : {duration} secondes. "
            "Conserver exactement le même visage, la même tenue, les mêmes couleurs et le même décor que les autres plans. "
            "Mouvement naturel, rendu photoréaliste, lumière cohérente, aucun texte à l'écran."
        )
        scenes.append({
            "id": f"scene_{index + 1}_{uuid.uuid4().hex[:6]}",
            "index": index + 1,
            "title": label,
            "duration": duration,
            "transition": "cut" if index == 0 else ("match_cut" if index % 2 else "dissolve"),
            "prompt": prompt,
            "status": "draft",
        })
    return {
        "id": f"story_{uuid.uuid4().hex[:10]}",
        "title": title,
        "premise": premise,
        "genre": genre,
        "visual_bible": visual_bible,
        "scenes": scenes,
        "publication": {"status": "draft", "requires_approval": True},
    }
