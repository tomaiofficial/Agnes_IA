"""core.api.snapgen_proxy — Reverse proxy pour SnapGenAI

Charge snapgen.ai via notre serveur avec <base> pour que les assets
restent sur snapgen.ai, et injecte du CSS/JS pour :
- N'afficher QUE le modèle Veo 3 + champ de prompt
- Cacher pricing, navigation, header, footer, autres modèles
"""

import logging

import requests
from fastapi import Request
from fastapi.responses import HTMLResponse, Response

logger = logging.getLogger(__name__)

_SNAPGEN_BASE = "https://snapgen.ai"

_INJECT = """
<style>
  /* === RESET AGNES === */
  html, body { background: #0a0a0f !important; margin: 0 !important; padding: 0 !important; }

  /* === Cacher nav, header, footer, sidebar === */
  nav, header, footer,
  [class*="sidebar"], [class*="nav-"], [class*="footer"],
  [class*="Navbar"], [class*="Header"], [class*="Footer"],
  [role="navigation"], [role="banner"], [role="contentinfo"],
  [class*="topbar"], [class*="top-bar"] {
    display: none !important;
  }

  /* === Cacher pricing, paywall, upgrade, credits === */
  [class*="price"], [class*="pricing"], [class*="paywall"],
  [class*="upgrade"], [class*="subscription"], [class*="plan"],
  [class*="credit"], [class*="credits"], [class*="token"],
  [class*="billing"], [class*="payment"], [class*="checkout"],
  [class*="modal"][class*="premium"], [class*="modal"][class*="upgrade"],
  [class*="modal"][class*="pay"],
  a[href*="/pricing"], a[href*="/plans"], a[href*="/subscribe"],
  a[href*="checkout"], a[href*="payment"],
  button[class*="upgrade"], button[class*="pricing"],
  [class*="banner"][class*="promo"], [class*="banner"][class*="sale"],
  [class*="offer"], [class*="discount"], [class*="coupon"],
  [class*="login"], [class*="signin"], [class*="sign-in"],
  [class*="register"], [class*="signup"], [class*="sign-up"],
  [class*="auth"], [class*="loginBtn"], [class*="signInBtn"] {
    display: none !important;
  }

  /* === Cacher sauf zone prompt + bouton générer === */
  /* Masquer les cartes modèles sauf Veo 3 */
  [class*="model-card"], [class*="modelCard"],
  [class*="engine-card"], [class*="engineCard"],
  [class*="provider-card"], [class*="providerCard"],
  [class*="option-card"], [class*="optionCard"] {
    display: none !important;
  }

  /* === Forcer l'affichage de la zone prompt === */
  [class*="prompt"], [class*="Prompt"],
  textarea, input[type="text"],
  [class*="generate"], [class*="Generate"],
  [class*="submit"], [class*="Submit"],
  [class*="send"], [class*="Send"],
  [class*="create"], [class*="Create"] {
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
  }
</style>
"""

# JS : observer et masquer les éléments non-désirés au fur et à mesure
_INJECT_JS = """
<script>
(function() {
  const HIDE = [
    'nav', 'header', 'footer',
    '[class*="sidebar"]', '[class*="nav-"]', '[class*="footer"]',
    '[class*="Navbar"]', '[class*="Header"]', '[class*="Footer"]',
    '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
    '[class*="price"]', '[class*="pricing"]', '[class*="paywall"]',
    '[class*="upgrade"]', '[class*="subscription"]', '[class*="plan"]',
    '[class*="credit"]', '[class*="credits"]', '[class*="token"]',
    '[class*="billing"]', '[class*="payment"]', '[class*="checkout"]',
    '[class*="login"]', '[class*="signin"]', '[class*="sign-in"]',
    '[class*="register"]', '[class*="signup"]', '[class*="sign-up"]',
    '[class*="auth"]',
    'a[href*="/pricing"]', 'a[href*="/plans"]', 'a[href*="/subscribe"]',
    '[class*="modal"][class*="premium"]',
    '[class*="modal"][class*="upgrade"]',
    '[class*="modal"][class*="pay"]',
    '[class*="offer"]', '[class*="discount"]',
    '[class*="banner"][class*="promo"]',
  ];

  function hide(root) {
    for (const s of HIDE) {
      try { root.querySelectorAll(s).forEach(e => {
        e.style.cssText = 'display:none!important;visibility:hidden!important;opacity:0!important;pointer-events:none!important;max-height:0!important;overflow:hidden!important;';
      }); } catch(x) {}
    }
  }

  const obs = new MutationObserver(ms => {
    for (const m of ms) for (const n of m.addedNodes) if (n.nodeType === 1) hide(n);
  });

  function init() {
    hide(document);
    obs.observe(document.body || document.documentElement, { childList: true, subtree: true });
    setInterval(() => hide(document), 1500);
    // Auto-scroll vers la zone prompt après 2s
    setTimeout(() => {
      const ta = document.querySelector('textarea');
      if (ta) ta.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 2500);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
</script>
"""


def _inject(html: str) -> str:
    """Injecte <base>, CSS et JS dans le HTML."""
    base_tag = f'<base href="{_SNAPGEN_BASE}/">'
    inject = _INJECT + _INJECT_JS

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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
        return HTMLResponse("<h1>Timeout</h1>", status_code=504)
    except Exception as e:
        logger.error(f"[SnapGenProxy] Error: {e}", exc_info=True)
        return HTMLResponse(f"<h1>Erreur: {str(e)[:200]}</h1>", status_code=502)
