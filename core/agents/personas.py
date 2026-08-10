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

import random
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


# ─────────────────────────────────────────────────────────────
# v10.0: Genres de mini-films — variété maximale des bots
# ─────────────────────────────────────────────────────────────
# Jusqu'ici chaque bot était enfermé dans son thème unique (nature,
# cuisine, tech…), d'où un feed répétitif. Désormais chaque publication
# tire UN GENRE au hasard (comédie, horreur, action, SF…) et écrit un
# mini-scénario de film dans ce genre. Les bots publient « tout et
# n'importe quoi » : films drôles, frissons, spectaculaires.

@dataclass(frozen=True)
class VideoGenre:
    id: str                       # identifiant technique stable
    name: str                     # nom affiché (ex : « Comédie »)
    instruction: str              # directive pour le chat IA (personnalité du genre)
    prompts: tuple = field(default_factory=tuple)  # prompts de secours variés du genre


VIDEO_GENRES: tuple[VideoGenre, ...] = (
    VideoGenre(
        id="comedie",
        name="Comédie",
        instruction=(
            "Ta spécialité : la comédie française absurde et drôle. Tu inventes des situations "
            "cocasses, des quiproquos, des personnages maladroits et des gags visuels irrésistibles."
        ),
        prompts=(
            "Une baguette géante qui traverse la place de la Bastille, un pigeon perché dessus tente de la garder, passants hilares, Paris ensoleillé, caméra drone qui suit, comédie burlesque, ultra réaliste, 4K",
            "Un mime coincé dans une boîte invisible au milieu du marché de Montmartre, il essaie de s'échapper sans briser son illusion, enfants qui rient, lumière dorée, comédie française, ultra réaliste",
            "Trois fromages de chèvre qui glissent sur un plateau en marbre comme des mini-voitures de course, départ en trombe, chute spectaculaire dans un bol de soupe, cuisine ensoleillée, comédie absurde, ultra réaliste",
            "Un cycliste parisien avec une baguette et des fleurs qui slalome entre des pigeons indifférents, évite un chien endormi et termine dans une fontaine, rue pavée, lumière de fin de journée, cascade comique, ultra réaliste",
            "Un chat obèse qui tente de sauter sur une étagère, rate son saut et atterrit sur un matou endormi, chaos de pelage, salon bourgeois, lumière chaleureuse, comédie, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="horreur",
        name="Horreur",
        instruction=(
            "Ta spécialité : l'horreur et le suspense. Tu crées des ambiances angoissantes, "
            "des ombres menaçantes, des créatures effrayantes, des moments qui glacent le sang."
        ),
        prompts=(
            "Un long couloir sombre d'un manoir français, une silhouette floue au fond, les portes claquent une à une, chandeliers qui tremblent, caméra tremblante au ras du sol, ambiance horreur, ultra réaliste",
            "Une jeune femme se retourne dans un miroir poussiéreux : son reflet reste immobile puis sourit, lumière de bougie vacillante, grenier inquiétant, horreur psychologique, ultra réaliste",
            "Une main décharnée sort lentement d'un puits de pierre ancien au crépuscule, brume au sol, corbeaux en alerte, forêt sombre en arrière-plan, caméra rapprochée, horreur gothique, ultra réaliste",
            "Un mannequin de vitrine parisienne bouge seul au milieu de la nuit, tête qui tourne vers la caméra, néons rouges vacillants, rue déserte sous la pluie, horreur urbaine, ultra réaliste",
            "Des silhouettes enfantines aux longs cheveux noirs qui avancent en courant dans un champ de maïs brumeux, s'approchant de la caméra, crépuscule orageux, horreur, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="action",
        name="Action",
        instruction=(
            "Ta spécialité : l'action spectaculaire. Courses-poursuites, cascades dangereuses, "
            "explosions contrôlées, bagarres chorégraphiées dignes du grand écran."
        ),
        prompts=(
            "Une course-poursuite à moto sur le périphérique parisien au coucher du soleil, cascades entre les voitures, étincelles, caméra embarquée nerveuse, action spectaculaire, ultra réaliste, 4K",
            "Un agent spécial saute d'un hélicoptère sur le toit d'un train en marche, roule et se relève en pleine vitesse, Alpes en arrière-plan, action, ultra réaliste",
            "Une explosion contrôlée derrière un cascadeur qui marche sans se retourner, mèche de cheveux dans le vent, ralenti épique, lumière orange, action, ultra réaliste",
            "Deux ninjas s'affrontent sur les toits d'un quartier la nuit, pluie fine, néons, sabres qui claquent, acrobaties impossibles, ralenti, action, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="science-fiction",
        name="Science-fiction",
        instruction=(
            "Ta spécialité : la science-fiction. Univers futuristes, robots, vaisseaux spatiaux, "
            "aliens, technologies impossibles et décors époustouflants."
        ),
        prompts=(
            "Un vaisseau spatial argenté traverse une nébuleuse violette et turquoise, traîne de particules lumineuses, Terre au loin, caméra large, science-fiction spectaculaire, ultra réaliste, 4K",
            "Un androïde aux yeux lumineux assemble un moteur à fusion dans une station spatiale, néons froids, reflets sur le métal, macro, science-fiction, ultra réaliste",
            "Une ville futuriste sous dôme la nuit, hovercars, hologrammes publicitaires, pluie de néons bleus et roses, caméra drone, cyberpunk, ultra réaliste",
            "Une porte dimensionnelle s'ouvre dans un laboratoire, un astronaute hésite devant le vortex bleu, instruments qui flottent, science-fiction, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="fantastique",
        name="Fantastique",
        instruction=(
            "Ta spécialité : le fantastique et la magie. Créatures légendaires, dragons, fées, "
            "sortilèges et mondes enchantés."
        ),
        prompts=(
            "Un dragon de glace déploie ses ailes au-dessus d'un fjord norvégien, cristaux qui se forment dans l'air, lumière arctique, caméra aérienne, fantastique épique, ultra réaliste, 4K",
            "Une fée lumineuse au milieu d'une clairière enchantée, poussière dorée, champignons géants, ruisseau scintillant, macro, fantastique, ultra réaliste",
            "Une licorne galope dans un champ de lavande au lever du soleil, crinière arc-en-ciel, brume légère, Provence, caméra latérale fluide, fantastique, ultra réaliste",
            "Un vieux grimoire s'ouvre tout seul dans une bibliothèque poussiéreuse, des lettres d'or s'envolent des pages, rayon de lumière, magie ancienne, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="thriller",
        name="Thriller",
        instruction=(
            "Ta spécialité : le thriller et le mystère. Suspense oppressant, enquêtes, fuites "
            "dans la nuit, tensions insoutenables."
        ),
        prompts=(
            "Un détective au pardessus inspecte une chambre d'hôtel sens dessus dessous, lampe torche, rideaux qui bougent, Paris pluvieux la nuit, plan-séquence tendu, thriller, ultra réaliste",
            "Un homme court dans une rame de métro vide, lumières qui clignotent, une enveloppe à la main, reflets dans les vitres noires, thriller urbain, caméra nerveuse, ultra réaliste",
            "Une porte blindée se verrouille lentement derrière une femme qui se retourne, système de sécurité rougeoyant, entrepôt désaffecté, éclairage froid, thriller, ultra réaliste",
            "Deux ombres se poursuivent sur les toits de Paris sous la lune, funambules de l'ombre, gargouilles, caméra dynamique, thriller nocturne, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="western",
        name="Western",
        instruction=(
            "Ta spécialité : le western. Déserts poussiéreux, saloons, duels au soleil couchant, "
            "trains à vapeur et grands espaces."
        ),
        prompts=(
            "Un cow-boy solitaire traverse une rue poussiéreuse, éperons qui tintent, saloon, roue de chariot qui grince, soleil de plomb, duel imminent, western, ultra réaliste, 4K",
            "Un duel au crépuscule entre deux pistoleros, mains qui hésitent au-dessus des holsters, poussière dorée en suspension, cactus, western spaghetti, ultra réaliste",
            "Un train à vapeur fonce dans les Rocheuses, un bandit court sur les wagons, fumée, sifflet, caméra latérale, western aventure, ultra réaliste",
            "Un mustang qui galope dans une plaine aride, poussière soulevée, ciel immense orange, coucher de soleil, western majestueux, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="film-noir",
        name="Film noir",
        instruction=(
            "Ta spécialité : le film noir. Paris 1955 en noir et blanc, détectives, bars enfumés, "
            "pluie sur les vitres, femmes mystérieuses."
        ),
        prompts=(
            "Un détective privé fume devant une fenêtre à stores, néon du bar qui clignote dehors, pluie sur la vitre, Paris 1955, noir et blanc, film noir, ultra réaliste",
            "Une femme mystérieuse en trench remonte un escalier en colimaçon, ombres parallèles des rambardes, lumière d'un projecteur, noir et blanc, film noir, ultra réaliste",
            "Un verre de whisky sur un comptoir en zinc, un chapeau déposé, fumée de cigarette, phonographe qui tourne, salle enfumée, noir et blanc, film noir, ultra réaliste",
            "Un homme marche sous les réverbères dans une rue mouillée, chapeau baissé, reflets des enseignes, vapeur d'égout, Paris nocturne, noir et blanc, film noir, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="romance",
        name="Romance",
        instruction=(
            "Ta spécialité : la romance parisienne. Rendez-vous sous la pluie, premiers baisers, "
            "regards qui se croisent, moments tendres et lumineux."
        ),
        prompts=(
            "Un couple danse sous la pluie sur le pont des Arts au coucher du soleil, parapluie abandonné, reflets dorés sur la Seine, romance parisienne, ralenti, ultra réaliste, 4K",
            "Deux mains qui se frôlent au-dessus d'une table de café, deux expressos, la Tour Eiffel scintillante au loin, lumière chaude du soir, romance, ultra réaliste",
            "Un homme offre un bouquet de lavande sur un quai de gare, le train démarre, regards qui se croisent, aube dorée, Provence, romance, ultra réaliste",
            "Un premier baiser timide sous les guirlandes d'un marché de Noël, flocons de neige, lanternes chaudes, Strasbourg, romance, ralenti, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="drame",
        name="Drame",
        instruction=(
            "Ta spécialité : le drame et l'émotion. Scènes poignantes, personnages bouleversants, "
            "lumières mélancoliques et moments qui touchent."
        ),
        prompts=(
            "Un vieil homme contemple la mer depuis une falaise bretonne, un mouchoir à la main, embruns, lumière grise émouvante, plan large, drame, ultra réaliste",
            "Une musicienne de rue joue du violon sous la pluie, pièces dans la capuche, passants pressés, reflets mélancoliques, drame urbain, ultra réaliste",
            "Un boxeur épuisé se relève dans un ring de quartier, projecteurs aveuglants, sueur et adversaire flous, foule silencieuse, drame sportif, ultra réaliste",
            "Une femme range les affaires de son père dans une malle, une photo jaunie dans les mains, lumière de fenêtre poussiéreuse, émotion, drame, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="documentaire-animalier",
        name="Documentaire animalier",
        instruction=(
            "Ta spécialité : le documentaire animalier. Faune sauvage, instants de vie capturés "
            "avec un réalisme époustouflant, comme National Geographic."
        ),
        prompts=(
            "Un guépard bondit sur sa proie dans la savane au lever du soleil, flou de mouvement, poussière dorée, caméra téléobjectif, documentaire animalier, ultra réaliste, 4K",
            "Une raie manta glisse dans un océan turquoise, banc de poissons argentés qui s'écarte, rayons de soleil sous-marins, documentaire, ultra réaliste",
            "Un colibri suspendu en vol, battement d'ailes au ralenti, fleur tropicale, lumière du matin, macro extrême, documentaire animalier, ultra réaliste",
            "Une meute de loups traverse une forêt enneigée au crépuscule, souffle visible, regards ambrés, silence, documentaire animalier, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="animation-pixar",
        name="Animation style Pixar",
        instruction=(
            "Ta spécialité : l'animation façon Pixar. Objets et animaux expressifs, couleurs vives, "
            "émotions enfantines, univers attachants et lumineux."
        ),
        prompts=(
            "Une petite lampe de bureau curieuse qui découvre une fleur dans un atelier, mouvements expressifs, couleurs vives, lumière douce, style animation Pixar, ultra réaliste",
            "Un robot de cuisine miniature qui affronte une pâte à crêpes rebelle dans une cuisine géante, gouttes qui voltigent, couleurs saturées, animation Pixar, ultra réaliste",
            "Un ballon rouge et un parapluie bleu qui deviennent amis dans un parc, dansent dans le vent, feuilles d'automne, animation Pixar, ultra réaliste",
            "Une petite souris astronaute qui flotte dans sa fusée en carton vers la lune, étoiles souriantes, couleurs pastel, animation Pixar, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="catastrophe",
        name="Catastrophe",
        instruction=(
            "Ta spécialité : les films catastrophe. Raz-de-marée, tornades, éruptions, immeubles "
            "qui vacillent — des scènes d'apocalypse spectaculaires."
        ),
        prompts=(
            "Un immense raz-de-marée s'approche d'une ville côtière, immeubles qui frémissent, ciel vert, caméra héliportée, catastrophe spectaculaire, ultra réaliste, 4K",
            "Une tornade massive traverse une plaine, débris qui tourbillonnent, un pick-up projeté, éclairs, lumière orange menaçante, catastrophe, ultra réaliste",
            "Une éruption volcanique crache des cendres et de la lave sur un village italien, coulée incandescente, ciel noir de cendres, catastrophe, ultra réaliste",
            "Un tremblement de terre fissure une avenue urbaine, voitures qui tanguent, façades qui s'effritent, panique, caméra instable, catastrophe, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="espionnage",
        name="Espionnage",
        instruction=(
            "Ta spécialité : l'espionnage. Agents secrets, gadgets impossibles, infiltrations, "
            "poursuites de luxe et plans dignes de James Bond."
        ),
        prompts=(
            "Un espion glisse le long d'un fil dans une salle des coffres aux lasers rouges, contorsions millimétrées, sueur sur le front, éclairage dramatique, espionnage, ultra réaliste, 4K",
            "Une voiture de sport noire s'élance depuis un yacht en feu, déploie des ailes et file au-dessus de la mer, Monaco, espionnage spectaculaire, ultra réaliste",
            "Un stylo transformé en gadget laser trace une carte sur un mur de marbre, agent secret en smoking, château français, espionnage, ultra réaliste",
            "Une poursuite en jet-ski dans les canaux de Venise, rideaux et agents ennemis, eau éclaboussée, bascule spectaculaire, espionnage, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="medieval-fantastique",
        name="Médiéval fantastique",
        instruction=(
            "Ta spécialité : le médiéval fantastique. Chevaliers en armure, châteaux forts, "
            "tournois, sorcières et dragons sur les vignobles."
        ),
        prompts=(
            "Un chevalier en armure gravit un escalier de donjon, torches qui flamboient, ombres dansantes, épée tirée, médiéval épique, ultra réaliste, 4K",
            "Un tournoi de joutes dans un château fort, lances qui s'entrechoquent, étendards, foule en liesse, poussière et soleil, médiéval, ultra réaliste",
            "Une sorcière prépare une potion violette fumante dans un chaudron, herbes qui flottent, chandelles, chaumière sombre, médiéval fantastique, ultra réaliste",
            "Un dragon doré survole une vallée de vignobles bordelais, ombre immense qui glisse sur les rangées, médiéval fantastique, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="post-apocalyptique",
        name="Post-apocalyptique",
        instruction=(
            "Ta spécialité : le post-apocalyptique. Mondes dévastés, nature qui reprend ses droits, "
            "survivants et déserts de ruines."
        ),
        prompts=(
            "Un survivant en combinaison traverse un Paris en ruines envahi par la végétation, Tour Eiffel tordue, brume, lumière grise, post-apocalyptique, ultra réaliste, 4K",
            "Une oasis verdoyante au milieu d'un désert de sable illimité, un dôme de verre, reflets, survie, post-apocalyptique, ultra réaliste",
            "Des véhicules bricolés filent sur une autoroute déserte, poussière et soleil couchant, road movie de survie, post-apocalyptique, ultra réaliste",
            "Un champ de panneaux solaires rouillés, un robot de soin qui traverse, ciel ocre, silence, post-apocalyptique, ultra réaliste",
        ),
    ),
    VideoGenre(
        id="sport-extreme",
        name="Sport extrême",
        instruction=(
            "Ta spécialité : le sport extrême. Snowboard vertigineux, wingsuit, escalade en solo, "
            "tubes de surf géants — l'adrénaline pure."
        ),
        prompts=(
            "Un snowboardeur dévale une pente vierge à toute vitesse, poudreuse qui explose, soleil rasant, Alpes, caméra embarquée, sport extrême, ultra réaliste, 4K",
            "Un base jumper saute d'une falaise, wingsuit déployée, vallée vertigineuse, nuages en dessous, sport extrême, ultra réaliste",
            "Un grimpeur en solo intégral escalade une paroi abrupte, doigts rougis, vide immense, lumière du matin, sport extrême, ultra réaliste",
            "Un surfeur prend un tube parfait à Nazaré, muraille d'eau au-dessus, embruns, lumière dramatique, sport extrême, ultra réaliste",
        ),
    ),
)


@dataclass(frozen=True)
class EditorialChoice:
    """Style éditorial choisi pour UNE publication : genre de mini-film ou thème du bot."""
    label: str                        # affiché dans les logs (ex : « Comédie »)
    instruction: str                  # directive pour le chat IA
    prompts: tuple = field(default_factory=tuple)  # prompts de secours


# Pondération : comédie et horreur sortent plus souvent (goût utilisateur),
# les autres genres équiprobables.
_GENRE_WEIGHTS: tuple[int, ...] = tuple(
    3 if g.id in ("comedie", "horreur") else 1 for g in VIDEO_GENRES
)


def pick_editorial(persona: AgentPersona) -> EditorialChoice:
    """Choisit le style éditorial d'UNE publication du bot.

    - 20 % de chances : le thème d'origine du persona (garde un peu d'identité)
    - 80 % : un genre de mini-film tiré au hasard (comédie, horreur, action, SF…)
      → chaque publication est différente, le feed devient « tout et n'importe quoi ».
    """
    if random.random() < 0.20:
        return EditorialChoice(
            label=persona.theme,
            instruction=f"Ta spécialité : {persona.theme}.",
            prompts=tuple(fallback_prompts(persona)),
        )
    genre = random.choices(VIDEO_GENRES, weights=_GENRE_WEIGHTS, k=1)[0]
    return EditorialChoice(
        label=genre.name,
        instruction=genre.instruction,
        prompts=genre.prompts,
    )


def fallback_prompts(persona: AgentPersona) -> list[str]:
    """Retourne les prompts de secours pour le thème du persona."""
    return FALLBACK_PROMPTS.get(persona.theme, FALLBACK_PROMPTS["nature et paysages spectaculaires"])
