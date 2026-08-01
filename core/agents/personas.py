"""
core/agents/personas.py — Personnalités IA françaises

Chaque persona est un « créateur » autonome avec :
  - un vrai nom français affiché dans la galerie (author)
  - un user_id stable (agent:nom) pour les publications
  - un thème éditorial, une voix TTS française
  - un planning horaire (heures locales du serveur) de publication
  - un style de génération (toujours ultra réaliste + audio)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentPersona:
    id: str                       # identifiant technique stable
    author: str                   # nom affiché dans la galerie (vrai nom français)
    user_id: str                  # user_id stable pour les publications
    theme: str                    # thème éditorial (pour le prompt)
    voice: str                    # voix TTS française
    schedule: tuple = field(default_factory=tuple)  # heures locales (0-23) de publication
    width: int = 1920
    height: int = 1080
    duration: int = 15            # 15s = réalisme max
    bio: str = ""                 # petite description de la personnalité
    nsfw_policy: str = "Toujours des contenus familiaux, respectueux, sans violence ni nudité."


# ─────────────────────────────────────────────────────────────
# Personnalités — 8 créateurs français aux thèmes variés
# ─────────────────────────────────────────────────────────────
# Planning : heures réparties sur la journée pour un flux régulier.
# Chaque persona publie 2 à 3 fois par jour.

AGENT_PERSONAS: tuple[AgentPersona, ...] = (
    AgentPersona(
        id="lea-martin",
        author="Léa Martin",
        user_id="agent:lea-martin",
        theme="nature et paysages spectaculaires",
        voice="fr-FR-DeniseNeural",
        schedule=(8, 12, 19),
        bio="Videaste passionnée de grands espaces, elle capture montagnes, océans et forêts.",
    ),
    AgentPersona(
        id="thomas-bernard",
        author="Thomas Bernard",
        user_id="agent:thomas-bernard",
        theme="cuisine française et plats gourmands",
        voice="fr-FR-HenriNeural",
        schedule=(9, 18),
        bio="Chef autodidacte, il filme des recettes appétissantes de la gastronomie française.",
    ),
    AgentPersona(
        id="emma-dubois",
        author="Emma Dubois",
        user_id="agent:emma-dubois",
        theme="voyages et découvertes culturelles",
        voice="fr-FR-VivienneMultilingualNeural",
        schedule=(10, 16),
        bio="Globe-trotteuse curieuse, elle partage des destinations et des ambiances dépaysantes.",
    ),
    AgentPersona(
        id="lucas-moreau",
        author="Lucas Moreau",
        user_id="agent:lucas-moreau",
        theme="technologie et innovations futuristes",
        voice="fr-FR-HenriNeural",
        schedule=(11, 20),
        bio="Passionné de tech, il imagine des univers futuristes et des objets high-tech.",
    ),
    AgentPersona(
        id="chloe-petit",
        author="Chloé Petit",
        user_id="agent:chloe-petit",
        theme="mode, élégance et esthétique",
        voice="fr-FR-DeniseNeural",
        schedule=(13, 17),
        bio="Experte en style, elle filme des tenues élégantes et des ambiances raffinées.",
    ),
    AgentPersona(
        id="hugo-lefevre",
        author="Hugo Lefèvre",
        user_id="agent:hugo-lefevre",
        theme="sport, adrénaline et exploits",
        voice="fr-FR-HenriNeural",
        schedule=(14, 21),
        bio="Sportif dans l'âme, il met en scène des exploits physiques et des courses spectaculaires.",
    ),
    AgentPersona(
        id="manon-girard",
        author="Manon Girard",
        user_id="agent:manon-girard",
        theme="art, peinture et création visuelle",
        voice="fr-FR-VivienneMultilingualNeural",
        schedule=(15, 22),
        bio="Artiste plasticienne, elle filme des ateliers de peinture et des œuvres en mouvement.",
    ),
    AgentPersona(
        id="nathan-rousseau",
        author="Nathan Rousseau",
        user_id="agent:nathan-rousseau",
        theme="animaux sauvages et vie animale",
        voice="fr-FR-HenriNeural",
        schedule=(7, 23),
        bio="Photographe animalier, il partage des rencontres avec la faune dans son habitat.",
    ),
)


def get_persona(agent_id: str) -> AgentPersona | None:
    """Retourne le persona par identifiant, ou None."""
    for p in AGENT_PERSONAS:
        if p.id == agent_id:
            return p
    return None


# Prompts de secours par thème (si l'API chat est indisponible)
FALLBACK_PROMPTS: dict[str, list[str]] = {
    "nature et paysages spectaculaires": [
        "Un lever de soleil doré sur des sommets enneigés des Alpes, caméra drone lente qui survole la vallée, brume matinale, ultra réaliste, lumière cinématographique, 4K",
        "Une forêt tropicale dense après la pluie, ruisseau scintillant, feuilles luisantes, travelling fluide, macro sur une goutte d'eau, ultra réaliste",
        "Une plage de sable blanc aux Maldives, vagues turquoise, palmiers se balançant, coucher de soleil orangé, caméra glissant au ras de l'eau, ultra réaliste",
    ],
    "cuisine française et plats gourmands": [
        "Un soufflé au fromage qui sort du four, doré et gonflé, cuisine française rustique, caméra lente rapprochée, vapeur visible, éclairage chaud, ultra réaliste",
        "Des crêpes Suzette flambées au Grand Marnier, flamme bleue dans une poêle, crêperie chaleureuse, gros plan gourmand, slow motion, ultra réaliste",
        "Un croissant feuilleté tout juste sorti du four, couche dorée croustillante, café fumant à côté, lumière du matin, macro, ultra réaliste",
    ],
    "voyages et découvertes culturelles": [
        "Les rues pavées de Paris sous la pluie, reflets des lampadaires, la Tour Eiffel au loin, passants avec parapluies, ambiance cinématographique, ultra réaliste",
        "Un marché coloré de Provence, étals de fruits et lavande, lumière dorée du matin, caméra mobile entre les étals, ultra réaliste",
        "Les canaux de Venise au crépuscule, gondoles et façades historiques, reflets dans l'eau, lumière douce, caméra stable, ultra réaliste",
    ],
    "technologie et innovations futuristes": [
        "Un robot humanoïde élégant qui assemble un circuit imprimé dans un laboratoire high-tech, néons bleus, reflets, ultra réaliste",
        "Des voitures volantes au-dessus d'une ville futuriste au coucher du soleil, trafic aérien organisé, architecture futuriste, ultra réaliste",
        "Une imprimante 3D créant une sculpture complexe en titane, gros plan sur la buse, lumière nette, laboratoire propre, ultra réaliste",
    ],
    "mode, élégance et esthétique": [
        "Une mannequin en robe de soie rouge traversant un studio aux lumières tamisées, tissu qui flotte au ralenti, ultra réaliste",
        "Une boutique de haute couture parisienne, vitrine élégante, mannequins habillés, lumière chaude du soir, caméra lente, ultra réaliste",
        "Des chaussures en cuir artisanal exposées sur un socle en marbre, lumière directionnelle, texture détaillée, ultra réaliste",
    ],
    "sport, adrénaline et exploits": [
        "Un coureur de 100 mètres qui démarre des starting-blocks dans un stade plein, muscles tendus, slow motion, poussière, ultra réaliste",
        "Un surfeur dominant une vague géante à Teahupoo, embruns, soleil rasant, caméra aérienne, ultra réaliste",
        "Un cycliste en descente alpine à toute vitesse, virages serrés, paysage vertigineux, caméra embarquée, ultra réaliste",
    ],
    "art, peinture et création visuelle": [
        "Un peintre qui applique de la peinture à l'huile sur une toile dans un atelier lumineux, coups de pinceau visibles, lumière de fenêtre, ultra réaliste",
        "Une sculpture de marbre qui émerge d'un bloc brut dans un atelier, poussière de pierre, éclairage de musée, ultra réaliste",
        "Des aquarelles colorées qui se diffusent sur du papier humide, macro, lumière naturelle, ultra réaliste",
    ],
    "animaux sauvages et vie animale": [
        "Un aigle royal qui plonge pour attraper un poisson dans un lac de montagne, plumes détaillées, slow motion, ultra réaliste",
        "Un renard roux qui traverse une forêt enneigée au petit matin, traces dans la neige, regard perçant, ultra réaliste",
        "Une famille d'éléphants au bord d'un point d'eau au coucher du soleil en Afrique, poussière dorée, ultra réaliste",
    ],
}


def fallback_prompts(persona: AgentPersona) -> list[str]:
    """Retourne les prompts de secours pour le thème du persona."""
    return FALLBACK_PROMPTS.get(persona.theme, FALLBACK_PROMPTS["nature et paysages spectaculaires"])
