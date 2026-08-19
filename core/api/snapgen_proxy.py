"""core.api.snapgen_proxy — Reverse proxy pour SnapGenAI

Charge snapgen.ai via notre serveur et injecte du CSS/JS pour :
- Cacher les éléments de pricing/paywall
- Garder le formulaire de prompt fonctionnel
- Supprimer les upsells et bannières premium

Utilise une balise <base> pour que les assets (JS/CSS/images) chargent
directement depuis snapgen.ai sans passer par le proxy.
"""

import logging

import requests
from fastapi import Request
from fastapi.responses import HTMLResponse, Response

logger = logging.getLogger(__name__)

_SNAPGEN_BASE = "https://snapgen.ai"

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
  body { background: #0a0a0f !important; }
  [role="dialog"][class*="price"],
  [role="dialog"][class*="upgrade"],
  [role="alert"][class*="price"] {
    display: none !important;
  }
</style>
"""

# JS injecté pour supprimer dynamiquement les éléments pricing
_INJECT_JS = """
<script>
(function() {
  const H = [
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
  function hide(root) {
    for (const s of H) {
      try { root.querySelectorAll(s).forEach(e => {
        e.style.cssText = 'display:none!important;visibility:hidden!important;opacity:0!important;pointer-events:none!important;';
      }); } catch(x) {}
    }
  }
  const obs = new MutationObserver(ms => {
    for (const m of ms) for (const n of m.addedNodes) if (n.nodeType === 1) hide(n);
  });
  function init() {
    hide(document);
    obs.observe(document.body || document.documentElement, { childList: true, subtree: true });
    setInterval(() => hide(document), 2000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
</script>
"""


def _inject(html: str) -> str:
    """Injecte <base>, CSS et JS dans le HTML de snapgen.ai."""
    # Balise <base> pour que tous les assets restent sur snapgen.ai
    base_tag = f'<base href="{_SNAPGEN_BASE}/">'
    inject = _INJECT_CSS + _INJECT_JS

    if "</head>" in html:
        html = html.replace("</head>", base_tag + inject + "</head>", 1)
    elif "<head>" in html:
        html = html.replace("<head>", "<head>" + base_tag + inject, 1)
    else:
        html = base_tag + inject + html

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
            "Referer": _SNAPGEN_BASE + "/",
        }

        resp = requests.get(target_url, headers=headers, timeout=30)
        content_type = resp.headers.get("content-type", "")

        if "text/html" in content_type:
            html = _inject(resp.text)
            return HTMLResponse(
                content=html,
                status_code=resp.status_code,
                headers={"Cache-Control": "no-cache"},
            )
        else:
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
