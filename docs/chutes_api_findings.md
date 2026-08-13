# Chutes.AI — éléments vérifiés

Sources officielles consultées le 13 août 2026.

- https://chutes.ai/docs/examples/video-generation
  - Guide officiel pour Wan2.1-14B.
  - Capacités annoncées : text-to-video, image-to-video et text-to-image.
  - Résolutions citées : 1280*720, 720*1280, 832*480, 480*832 et 1024*1024.
  - Le schéma d’entrée montre `prompt`, `negative_prompt`, `resolution`, `seed`, `steps`, `fps` et `frames`.
  - Le guide décrit un déploiement de Chute personnalisé nécessitant des GPU cloud multi-GPU, pas un modèle à installer sur le PC de l’utilisateur.

- https://chutes.ai/docs/api-reference/overview
  - L’API officielle est REST et expose des groupes Users, Chutes, Invocations, Pricing, Jobs et autres.

- https://chutes.ai/docs/api-reference/general
  - Base API documentée : `https://api.chutes.ai`.
  - Health-check : `GET /ping`.
  - Authentification documentée : API Key ou Bearer Token.

- https://chutes.ai/docs/api-reference/chutes
  - `GET /chutes/` liste les chutes et accepte notamment `include_public`, `template`, `name`, `slug`, pagination et `include_schemas`.
  - `GET /chutes/{chute_id_or_name}` récupère une chute par ID ou nom.
  - Les endpoints documentés utilisent `Authorization` et peuvent aussi accepter `X-Chutes-Hotkey`, `X-Chutes-Signature` et `X-Chutes-Nonce`.

- https://chutes.ai/docs/api-reference/invocations
  - La référence documente l’usage et les statistiques d’invocations, mais ne donne pas encore dans la page consultée un endpoint générique explicite de génération vidéo.

Conclusion de sécurité : ne pas inventer le nom d’un modèle vidéo ni son endpoint d’invocation. Il faut utiliser la clé utilisateur côté serveur pour interroger `/chutes/?include_public=true&include_schemas=true`, identifier le chute vidéo réellement disponible, puis adapter le payload à son schéma officiel.
