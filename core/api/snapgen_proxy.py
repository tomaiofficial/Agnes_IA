"""core.api.snapgen_proxy — Reverse proxy pour SnapGenAI

Charge snapgen.ai via notre serveur et injecte du CSS/JS pour :
- Cacher les éléments de pricing/paywall
- Garder le formulaire de prompt fonctionnel
- Supprimer les upsells et bannières premium
"""

import logging
import re
from urllib.parse import urljoin

import requests
from fastapi import Request
from fastapi.responses import HTMLResponse, Response

logger = logging.getLogger(__name__)

_SNAPGEN_BASE = "https://snapgen.ai"
_SNAPGEN_API = "https://api.snapgen.ai"

# CSS injecté pour cacher les éléments de pricing/paywall
_INJECT_CSS = """
<style>
  /* Cacher les éléments de pricing, paywall, upgrade */
  [class*="price"], [class*="pricing"], [class*="paywall"],
  [class*="upgrade"], [class*="subscription"], [class*="plan"],
  [class*="credit"], [class*="credits"], [class*="token"],
  [data-testid*="price"], [data-testid*="paywall"],
  [class*="billing"], [class*="payment"], [class*="checkout"],
  [class*="modal"][class*="premium"], [class*="modal"][class*="upgrade"],
  [class*="modal"][class*="pay"],
  a[href*="/pricing"], a[href*="/plans"], a[href*="/subscribe"],
  a[href*="checkout"], a[href*="payment"],
  button[class*="upgrade"], button[class*="pricing"],
  [class*="banner"][class*="promo"], [class*="banner"][class*="sale"],
  [class*="offer"], [class*="discount"], [class*="coupon"] {
    display: none !important;
  }

  /* Forcer le mode sombre cohérent */
  body { background: #0a0a0f !important; }

  /* Masquer les toasts/prompts de pricing */
  [role="dialog"][class*="price"],
  [role="dialog"][class*="upgrade"],
  [role="alert"][class*="price"] {
    display: none !important;
  }
</style>
"""

# JS injecté pour supprimer dynamiquement les éléments pricing au fur et à mesure
_INJECT_JS = """
<script>
(function() {
  // Sélecteurs d'éléments à supprimer
  const HIDE_SELECTORS = [
    '[class*="price"]', '[class*="pricing"]', '[class*="paywall"]',
    '[class*="upgrade"]', '[class*="subscription"]', '[class*="plan"]',
    '[class*="credit"]', '[class*="credits"]',
    '[class*="billing"]', '[class*="payment"]', '[class*="checkout"]',
    'a[href*="/pricing"]', 'a[href*="/plans"]', 'a[href*="/subscribe"]',
    'a[href*="checkout"]', 'a[href*="payment"]',
    '[class*="modal"][class*="premium"]',
    '[class*="modal"][class*="upgrade"]',
    '[class*="modal"][class*="pay"]',
    '[class*="offer"]', '[class*="discount"]',
  ];

  function hideElements(root) {
    for (const sel of HIDE_SELECTORS) {
      try {
        root.querySelectorAll(sel).forEach(el => {
          el.style.setProperty('display', 'none', 'important');
          el.style.setProperty('visibility', 'hidden', 'important');
          el.style.setProperty('opacity', '0', 'important');
          el.style.setProperty('pointer-events', 'none', 'important');
        });
      } catch(e) {}
    }
  }

  // Observer les changements DOM
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (node.nodeType === 1) hideElements(node);
      }
    }
  });

  // Lancer quand le DOM est prêt
  function init() {
    hideElements(document);
    observer.observe(document.body || document.documentElement, {
      childList: true, subtree: true
    });
    // Nettoyage périodique
    setInterval(() => hideElements(document), 2000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
</script>
"""


def _rewrite_html(html: str, base_url: str = "/snapgen-proxy") -> str:
    """Réécrit les URLs dans le HTML pour passer par le proxy."""
    # Injecter CSS et JS avant </head>
    inject = _INJECT_CSS + _INJECT_JS
    if "</head>" in html:
        html = html.replace("</head>", inject + "</head>", 1)
    elif "<head>" in html:
        html = html.replace("<head>", "<head>" + inject, 1)

    # Réécrire les URLs relatives vers snapgen.ai
    # href="/xxx" -> href="/snapgen-proxy/xxx"
    html = re.sub(r'href="/((?!snapgen-proxy)[^"]*)"', f'href="{base_url}/\\1"', html)
    html = re.sub(r'src="/((?!snapgen-proxy)[^"]*)"', f'src="{base_url}/\\1"', html)

    return html


async def proxy_request(path: str, request: Request) -> Response:
    """Proxy une requête vers snapgen.ai."""
    target_url = f"{_SNAPGEN_BASE}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    try:
        headers = {
            "User-Agent": request.headers.get("user-agent", "Mozilla/5.0"),
            "Accept": request.headers.get("accept", "*/*"),
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        resp = requests.get(target_url, headers=headers, timeout=30)
        content_type = resp.headers.get("content-type", "")

        if "text/html" in content_type:
            html = resp.text
            html = _rewrite_html(html)
            return HTMLResponse(
                content=html,
                status_code=resp.status_code,
                headers={"Cache-Control": "no-cache"},
            )
        else:
            # Passer les autres types directement
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type=content_type,
            )

    except requests.exceptions.Timeout:
        return HTMLResponse("<h1>Timeout — snapgen.ai ne répond pas</h1>", status_code=504)
    except Exception as e:
        logger.error(f"[SnapGenProxy] Error: {e}", exc_info=True)
        return HTMLResponse(f"<h1>Erreur proxy: {str(e)[:200]}</h1>", status_code=502)
