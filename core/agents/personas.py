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
    avatar_prompt: str = ""       # prompt de la photo de profil IA (portrait TikTok-like)


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
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'une jeune femme française d'environ 25 ans "
            "aux cheveux bruns ondulés, sourire chaleureux, fond flou de montagnes enneigées, "
            "selfie vlog en extérieur, lumière naturelle dorée, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="thomas-bernard",
        author="Thomas Bernard",
        user_id="agent:thomas-bernard",
        theme="cuisine française et plats gourmands",
        voice="fr-FR-HenriNeural",
        schedule=(9, 18),
        bio="Chef autodidacte, il filme des recettes appétissantes de la gastronomie française.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'un homme français d'environ 35 ans "
            "avec un tablier de chef, sourire confiant, fond flou d'une cuisine chaleureuse, "
            "selfie vlog, lumière chaude, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="emma-dubois",
        author="Emma Dubois",
        user_id="agent:emma-dubois",
        theme="voyages et découvertes culturelles",
        voice="fr-FR-VivienneMultilingualNeural",
        schedule=(10, 16),
        bio="Globe-trotteuse curieuse, elle partage des destinations et des ambiances dépaysantes.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'une jeune femme française d'environ 28 ans "
            "aux cheveux blonds, sourire lumineux, fond flou d'une ville historique, "
            "selfie vlog de voyage, lumière dorée, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="lucas-moreau",
        author="Lucas Moreau",
        user_id="agent:lucas-moreau",
        theme="technologie et innovations futuristes",
        voice="fr-FR-HenriNeural",
        schedule=(11, 20),
        bio="Passionné de tech, il imagine des univers futuristes et des objets high-tech.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'un homme français d'environ 30 ans "
            "portant des lunettes fines, sourire curieux, fond flou d'un laboratoire high-tech "
            "aux néons bleus, selfie vlog, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="chloe-petit",
        author="Chloé Petit",
        user_id="agent:chloe-petit",
        theme="mode, élégance et esthétique",
        voice="fr-FR-DeniseNeural",
        schedule=(13, 17),
        bio="Experte en style, elle filme des tenues élégantes et des ambiances raffinées.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'une jeune femme française d'environ 26 ans "
            "élégante, sourire chic, fond flou d'un studio de mode, selfie vlog, "
            "lumière tamisée, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="hugo-lefevre",
        author="Hugo Lefèvre",
        user_id="agent:hugo-lefevre",
        theme="sport, adrénaline et exploits",
        voice="fr-FR-HenriNeural",
        schedule=(14, 21),
        bio="Sportif dans l'âme, il met en scène des exploits physiques et des courses spectaculaires.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'un homme français athlétique d'environ 27 ans, "
            "sourire sportif, fond flou d'un terrain de sport au coucher du soleil, "
            "selfie vlog après l'entraînement, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="manon-girard",
        author="Manon Girard",
        user_id="agent:manon-girard",
        theme="art, peinture et création visuelle",
        voice="fr-FR-VivienneMultilingualNeural",
        schedule=(15, 22),
        bio="Artiste plasticienne, elle filme des ateliers de peinture et des œuvres en mouvement.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'une jeune femme française d'environ 29 ans "
            "aux cheveux roux, sourire créatif, fond flou d'un atelier de peinture lumineux, "
            "selfie vlog, lumière de fenêtre, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="nathan-rousseau",
        author="Nathan Rousseau",
        user_id="agent:nathan-rousseau",
        theme="animaux sauvages et vie animale",
        voice="fr-FR-HenriNeural",
        schedule=(7, 23),
        bio="Photographe animalier, il partage des rencontres avec la faune dans son habitat.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'un homme français d'environ 32 ans "
            "à la barbe légère, sourire naturel, fond flou d'une savane au lever du soleil, "
            "selfie vlog en extérieur, photoréaliste, haute qualité"
        ),
    ),
    # v9.5: 8 nouveaux créateurs — le flux est bien plus dense et varié (16 bots)
    AgentPersona(
        id="camille-morel",
        author="Camille Morel",
        user_id="agent:camille-morel",
        theme="jardinage et plantes d'intérieur",
        voice="fr-FR-DeniseNeural",
        schedule=(8, 16),
        bio="Botaniste passionnée, elle filme des jardins luxuriants et des plantes d'intérieur.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'une jeune femme française d'environ 27 ans "
            "sourire paisible, fond flou d'un jardin luxuriant et de plantes vertes, "
            "selfie vlog, lumière naturelle, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="antoine-lefebvre",
        author="Antoine Lefebvre",
        user_id="agent:antoine-lefebvre",
        theme="cinéma et effets spectaculaires",
        voice="fr-FR-HenriNeural",
        schedule=(9, 17),
        bio="Cinephile et réalisateur amateur, il crée des plans et des effets dignes du grand écran.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'un homme français d'environ 33 ans "
            "avec une casquette de réalisateur, fond flou d'un plateau de tournage, "
            "selfie vlog, lumière de studio, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="juliette-roux",
        author="Juliette Roux",
        user_id="agent:juliette-roux",
        theme="danse et chorégraphies urbaines",
        voice="fr-FR-VivienneMultilingualNeural",
        schedule=(10, 18),
        bio="Danseuse urbaine, elle filme des chorégraphies énergiques dans des décors de rue.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'une jeune femme française d'environ 24 ans "
            "sourire énergique, fond flou d'un studio de danse urbain, selfie vlog, "
            "lumière dynamique, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="maxime-laurent",
        author="Maxime Laurent",
        user_id="agent:maxime-laurent",
        theme="astronomie et univers",
        voice="fr-FR-HenriNeural",
        schedule=(11, 19),
        bio="Astronaute amateur, il partage des ciels étoilés et des vues spectaculaires de l'univers.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'un homme français d'environ 31 ans "
            "regard rêveur, fond flou d'un observatoire au crépuscule avec ciel étoilé, "
            "selfie vlog, lumière bleutée, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="ines-fontaine",
        author="Inès Fontaine",
        user_id="agent:ines-fontaine",
        theme="pâtisserie fine et desserts",
        voice="fr-FR-DeniseNeural",
        schedule=(12, 20),
        bio="Pâtissière talentueuse, elle filme des desserts raffinés et des douceurs gourmandes.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'une jeune femme française d'environ 28 ans "
            "sourire gourmand, fond flou d'une pâtisserie élégante, selfie vlog, "
            "lumière chaude, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="romain-mercier",
        author="Romain Mercier",
        user_id="agent:romain-mercier",
        theme="architecture et design urbain",
        voice="fr-FR-HenriNeural",
        schedule=(13, 21),
        bio="Architecte passionné, il met en valeur des bâtiments et des espaces urbains modernes.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'un homme français d'environ 34 ans "
            "regard assuré, fond flou d'une ville moderne aux lignes architecturales, "
            "selfie vlog, lumière dorée, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="louise-garnier",
        author="Louise Garnier",
        user_id="agent:louise-garnier",
        theme="bien-être, yoga et méditation",
        voice="fr-FR-VivienneMultilingualNeural",
        schedule=(14, 22),
        bio="Coach bien-être, elle filme des séances de yoga et des ambiances apaisantes.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'une femme française sereine d'environ 30 ans, "
            "sourire doux, fond flou d'un espace nature apaisant, selfie vlog, "
            "lumière douce du matin, photoréaliste, haute qualité"
        ),
    ),
    AgentPersona(
        id="theo-blanchard",
        author="Théo Blanchard",
        user_id="agent:theo-blanchard",
        theme="jeux vidéo et univers virtuels",
        voice="fr-FR-HenriNeural",
        schedule=(15, 23),
        bio="Gamer passionné, il partage des univers virtuels immersifs et des ambiances de jeu.",
        avatar_prompt=(
            "Photo de profil TikTok ultra réaliste d'un jeune homme français d'environ 23 ans "
            "sourire joueur, fond flou d'un setup gaming aux néons colorés, "
            "selfie vlog, lumière LED, photoréaliste, haute qualité"
        ),
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
    "jardinage et plantes d'intérieur": [
        "Des mains qui arrosent un jardin verdoyant au petit matin, gouttelettes scintillantes, lumière dorée, macro sur une feuille, ultra réaliste",
        "Un salon chaleureux rempli de plantes d'intérieur luxuriantes, rayons de soleil à travers les feuilles, caméra lente, ultra réaliste",
        "Une serre victorienne avec des orchidées en fleurs, vapeur légère, lumière diffuse, travelling fluide, ultra réaliste",
    ],
    "cinéma et effets spectaculaires": [
        "Une caméra de cinéma sur un plateau de tournage, projecteurs éblouissants, fumée de théâtre, ralenti sur une explosion contrôlée, ultra réaliste",
        "Un hélicoptère de cascade qui frôle un canyon au lever du soleil, traînée de condensation, caméra embarquée, ultra réaliste",
        "Une scène de science-fiction : vaisseau qui décolle dans une ville nocturne, néons et particules, lumière spectaculaire, ultra réaliste",
    ],
    "danse et chorégraphies urbaines": [
        "Un danseur de breakdance qui tourne sur une place de ville, poussière soulevée, lumière dorée du soir, slow motion, ultra réaliste",
        "Deux danseurs urbains dans un studio aux néons colorés, mouvements synchronisés au ralenti, reflets au sol, ultra réaliste",
        "Une danseuse de street dance au crépuscule sur un rooftop, ville en arrière-plan, tissu qui flotte, lumière cinématique, ultra réaliste",
    ],
    "astronomie et univers": [
        "Une voie lactée spectaculaire au-dessus d'un observatoire de montagne, étoiles filantes, dôme ouvert, longue exposition, ultra réaliste",
        "Une nébuleuse colorée avec des nuages de gaz rose et bleu, étoiles brillantes, vue télescope profonde, ultra réaliste",
        "Un astronaute flottant devant une station spatiale, Terre en arrière-plan, lumière solaire intense, ultra réaliste",
    ],
    "pâtisserie fine et desserts": [
        "Un entremets au chocolat miroir qui coule, reflets parfaits, pâtisserie élégante, gros plan macro, lumière de vitrine, ultra réaliste",
        "Des macarons multicolores disposés sur un comptoir en marbre, textures détaillées, lumière douce, caméra lente, ultra réaliste",
        "Une tarte aux fruits frais sous une cloche en verre, étincelles de sucre, pâtisserie raffinée, macro, ultra réaliste",
    ],
    "architecture et design urbain": [
        "Une façade de gratte-ciel moderne vue du sol, lignes géométriques, ciel bleu contrasté, travelling vertical, ultra réaliste",
        "Un pont suspendu élégant au coucher du soleil, câbles et ombres graphiques, reflets sur l'eau, caméra drone, ultra réaliste",
        "Un intérieur minimaliste lumineux, grandes baies vitrées, mobilier design, lumière naturelle douce, travelling lent, ultra réaliste",
    ],
    "bien-être, yoga et méditation": [
        "Une femme en posture de yoga face à la mer au lever du soleil, lumière dorée, vagues douces, caméra lente, ultra réaliste",
        "Une séance de méditation dans une forêt de bambous, rayons de lumière traversant la brume, atmosphère paisible, ultra réaliste",
        "Des bougies et de la lavande sur un tapis de yoga, vapeur d'encens, lumière chaude tamisée, macro, ultra réaliste",
    ],
    "jeux vidéo et univers virtuels": [
        "Un joueur avec un casque VR qui explore un monde virtuel coloré, reflets dans ses yeux, néons de la pièce, ultra réaliste",
        "Un setup de gaming immersif avec clavier rétroéclairé RGB, écrans ultrawide, ambiance néon bleu et violet, caméra lente, ultra réaliste",
        "Un avatar héroïque qui s'avance dans un monde fantastique numérique, particules magiques, lumière spectaculaire, ultra réaliste",
    ],
}


def fallback_prompts(persona: AgentPersona) -> list[str]:
    """Retourne les prompts de secours pour le thème du persona."""
    return FALLBACK_PROMPTS.get(persona.theme, FALLBACK_PROMPTS["nature et paysages spectaculaires"])
