"""Cicada's site-explore capture: one scripted visit to one saved site, inside browser-harness.

Run it in ONE browser-harness call (the harness's helpers — cdp, switch_tab, js, wait_for_load,
wait_for_network_idle — are already in scope there):

    browser-harness <<'PY'
    exec(open("/path/to/skills/site-explore/explore_capture.py").read())
    print(explore_capture("https://example.com/", depth="capture", context="signed_in"))
    PY

It prints one JSON object: the outcome, when it was captured (aware UTC), the final URL and HTTP status, the paths of
the screenshots it saved, and the page's structure (title, description, JSON-LD, the h1–h3 outline, fonts, CSS
custom properties, notable components, at most 1,500 words of visible text). Hand those fields to
`cicada_record_capture`. Cicada reads the colours and the look's hash from the pixels itself.

What it never does: sign in, type anything, click or hide a cookie or consent banner, change the user agent or any
header, retry a page that refused, touch a tab it did not open, or bring a tab to the front. A sign-in, a captcha or a
block ends the visit with outcome needs_login or blocked and no screenshot. It opens its own background tab — in the
person's signed-in session (context="signed_in") or in a fresh cookie-less browser context it creates and disposes
(context="isolated") — and closes it when done.

Depth (the person's reason for saving it decides; the default is capture):
  capture  the viewport at 1440×900 (2×) and a 640×400 thumbnail;
  look     + the full page (lazy images scrolled in at a reading pace), mobile at 390×844, and dark mode when the
             site has one;
  product  + the full page;
  read     + the full page.
"""
import base64
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

EXPLORE_VERSION = "1"
VIEW_W, VIEW_H, VIEW_DPR = 1440, 900, 2
THUMB_W = 640
MOBILE_W, MOBILE_H = 390, 844
FULL_MAX_PX = 12000
SCROLL_STEP, SCROLL_PAUSE = 900, 0.4
JPEG_QUALITY = 80

_PAGE_JS = r"""
(() => {
  const q = (s, root) => Array.from((root || document).querySelectorAll(s));
  const vis = e => { if (!e) return false; const r = e.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const c = getComputedStyle(e); return c.display !== 'none' && c.visibility !== 'hidden' && c.opacity !== '0'; };
  const box = e => { const r = e.getBoundingClientRect();
    return {x: Math.round(r.left + scrollX), y: Math.round(r.top + scrollY), width: Math.round(r.width), height: Math.round(r.height)}; };
  const meta = n => { const m = document.querySelector(`meta[name="${n}"]`) || document.querySelector(`meta[property="${n}"]`);
    return m ? (m.getAttribute('content') || '').trim() : null; };
  const nav = (performance.getEntriesByType('navigation') || [])[0] || {};
  const outline = q('h1,h2,h3').filter(vis).slice(0, 60)
    .map(h => ({level: +h.tagName[1], text: (h.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 160)})).filter(h => h.text);
  const jsonld = [];
  q('script[type="application/ld+json"]').slice(0, 10).forEach(s => { try { const d = JSON.parse(s.textContent);
    (Array.isArray(d) ? d : (d['@graph'] || [d])).forEach(x => { if (x && typeof x === 'object') jsonld.push(x); }); } catch (e) {} });
  const wanted = ['Organization', 'Product', 'SoftwareApplication', 'Article', 'Person', 'WebSite', 'Corporation'];
  const ld = jsonld.filter(x => { const t = [].concat(x['@type'] || []); return t.some(v => wanted.includes(v)); }).slice(0, 6);
  const fonts = []; try { document.fonts.forEach(f => { if (f.status === 'loaded') { const n = f.family.replace(/["']/g, '');
    if (!fonts.includes(n)) fonts.push(n); } }); } catch (e) {}
  const style = sel => { const e = document.querySelector(sel); if (!e) return null; const c = getComputedStyle(e);
    return {family: c.fontFamily, size: c.fontSize, weight: c.fontWeight, lineHeight: c.lineHeight, color: c.color,
            background: c.backgroundColor, radius: c.borderRadius, padding: c.padding}; };
  const typography = {}; ['body', 'h1', 'h2', 'h3', 'p', 'a', 'button', 'nav'].forEach(s => { const v = style(s); if (v) typography[s] = v; });
  Object.values(typography).forEach(t => { const n = (t.family || '').split(',')[0].replace(/["']/g, '').trim();
    if (n && !fonts.includes(n)) fonts.push(n); });
  const tokens = {}; let darkRule = false;
  for (const sheet of Array.from(document.styleSheets)) { let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
    for (const r of Array.from(rules || [])) {
      if (r.media && /prefers-color-scheme:\s*dark/.test(r.media.mediaText || '')) darkRule = true;
      if (r.selectorText === ':root' && r.style) { for (const p of Array.from(r.style)) {
        if (p.startsWith('--') && Object.keys(tokens).length < 40) tokens[p] = r.style.getPropertyValue(p).trim(); } } } }
  const comps = [];
  const add = (name, e) => { if (e && vis(e) && comps.length < 24) comps.push({name, box: box(e)}); };
  add('nav', document.querySelector('header nav, nav, [role=navigation]'));
  const hero = q('section, header, main > div, [class*=hero]').find(s => s.querySelector('h1') && s.querySelector('a, button'));
  add('hero', hero);
  const grid = q('*').find(p => { const kids = Array.from(p.children).filter(vis); if (kids.length < 3) return false;
    const cls = kids[0].className; if (!cls || typeof cls !== 'string') return false;
    const same = kids.filter(k => k.className === cls); if (same.length < 3) return false;
    const h = same.map(k => k.getBoundingClientRect().height); return Math.max(...h) - Math.min(...h) < 40; });
  add('card-grid', grid);
  const text = (document.body ? document.body.innerText : '') || '';
  if (/[$€£]\s?\d|\/mo\b|per month|pricing/i.test(text) || /pricing/.test(location.pathname)) add('pricing', q('[class*=pric], [id*=pric]').find(vis) || document.body);
  add('code', q('pre code, pre').find(vis));
  add('video', q('video, iframe[src*="youtube"], iframe[src*="vimeo"]').find(vis));
  add('form', q('form').find(vis));
  add('footer', document.querySelector('footer, [role=contentinfo]'));
  const consentSel = ['#onetrust-banner-sdk', '#onetrust-consent-sdk', '#CybotCookiebotDialog', '.qc-cmp2-container', '#usercentrics-root',
    '#didomi-host', '#truste-consent-track', '.fc-consent-root', '.cc-window', '#cookie-banner', '#cookieConsent',
    '[aria-label*="cookie" i]', '[id*="cookie" i][class*="banner" i]', '[class*="cookie-consent" i]'];
  const consentEl = consentSel.map(s => { try { return q(s).find(vis); } catch (e) { return null; } }).find(Boolean);
  const consentBox = consentEl ? (() => { const r = consentEl.getBoundingClientRect();
    return {x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height)}; })() : null;
  const consentWall = !!consentBox && consentBox.width * consentBox.height > innerWidth * innerHeight * 0.6;
  const account = q('header img[alt*="avatar" i], header [aria-label*="account" i], nav img[alt*="avatar" i], ' +
    '[data-testid*="avatar" i], img[class*="avatar" i], [aria-label*="profile menu" i], [aria-label*="your account" i]').some(vis);
  const captcha = q('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="challenges.cloudflare.com"], .cf-turnstile, #challenge-form, #cf-challenge-running').length > 0
    || /just a moment|attention required|verify you are human|are you a robot/i.test(document.title);
  const password = q('input[type=password]').some(vis) && text.length < 2000;
  const parked = /domain (is )?for sale|buy this domain|this domain may be for sale|parked free|domain parking/i.test(document.title + ' ' + text.slice(0, 2000));
  const host = location.hostname;
  const score = l => { const s = (l.innerText + ' ' + l.pathname).toLowerCase();
    return ['feature', 'product', 'pricing', 'about', 'company', 'docs', 'design', 'brand'].findIndex(k => s.includes(k)); };
  const links = q('nav a[href], header a[href], footer a[href]').filter(a => a.hostname === host && a.pathname !== location.pathname)
    .map(a => ({url: a.href.split('#')[0], label: (a.innerText || '').trim().slice(0, 80), rank: score(a)}))
    .filter(l => l.rank >= 0).sort((a, b) => a.rank - b.rank);
  const seen = new Set(); const next = []; for (const l of links) { if (!seen.has(l.url) && next.length < 2) { seen.add(l.url); next.push({url: l.url, label: l.label}); } }
  return JSON.stringify({
    title: document.title || '', description: meta('description') || meta('og:description'),
    og: {site_name: meta('og:site_name'), title: meta('og:title'), image: meta('og:image')},
    jsonld: ld, outline, fonts: fonts.slice(0, 12), typography, tokens, components: comps,
    text: text.replace(/\s+/g, ' ').trim().split(' ').slice(0, 1500).join(' '),
    final_url: location.href, http_status: nav.responseStatus || null, last_modified: document.lastModified || null,
    scroll_height: Math.min(document.documentElement.scrollHeight || 0, 100000),
    consent_overlay: !!consentBox, consent_box: consentBox, consent_wall: consentWall,
    account_visible: account, captcha, password_wall: password, parked, dark_rule: darkRule, next_pages: next
  });
})()
"""


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _shot(out_dir, name, **params):
    """One JPEG screenshot of the attached tab, saved under ``out_dir``; returns its path."""
    data = cdp("Page.captureScreenshot", _response_timeout=60, format="jpeg", quality=JPEG_QUALITY, **params)["data"]
    path = os.path.join(out_dir, f"{name}.jpg")
    with open(path, "wb") as handle:
        handle.write(base64.b64decode(data))
    return path


def _metrics(width, height, dpr, mobile=False):
    cdp("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=dpr, mobile=mobile)


def _settle(timeout=8.0):
    wait_for_load(timeout=20)
    try:
        wait_for_network_idle(timeout=timeout, idle_ms=500)
    except Exception:
        pass


def _read_page():
    return json.loads(js(_PAGE_JS))


def _scroll_through(height):
    """Scroll to the bottom at a reading pace so lazy images load (900 px steps, 400 ms apart, capped), then back."""
    y = 0
    while y < min(height, FULL_MAX_PX):
        y += SCROLL_STEP
        js(f"window.scrollTo(0, {y})")
        time.sleep(SCROLL_PAUSE)
    js("window.scrollTo(0, 0)")
    time.sleep(SCROLL_PAUSE)


def _host(url):
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _classify(page, nav_error):
    if nav_error:
        if any(m in nav_error for m in ("NAME_NOT_RESOLVED", "CONNECTION_REFUSED", "ADDRESS_UNREACHABLE", "CERT",
                                        "SSL", "CONNECTION_CLOSED", "CONNECTION_RESET", "TIMED_OUT")):
            return "gone"
        if "BLOCKED" in nav_error:
            return "blocked"
        return "failed"
    status = page.get("http_status")
    if status in (401, 403) or page.get("password_wall"):
        return "needs_login"
    if status in (429, 451) or page.get("captcha") or page.get("consent_wall"):
        return "blocked"
    if status in (404, 410):
        return "not_found"
    if page.get("parked"):
        return "parked"
    return "captured"


def explore_capture(url, depth="capture", context="signed_in", out_dir=None):
    """Visit ``url`` once and capture it. Returns the JSON string to hand to ``cicada_record_capture``."""
    depth = depth if depth in ("capture", "look", "product", "read") else "capture"
    isolated = context == "isolated"
    out_dir = out_dir or tempfile.mkdtemp(prefix="cicada-explore-")
    os.makedirs(out_dir, exist_ok=True)
    result = {"url": url, "explore_version": EXPLORE_VERSION, "depth": depth, "signed_in": not isolated,
              "shots": [], "loads": 1}
    browser_context, target = None, None
    try:
        if isolated:
            browser_context = cdp("Target.createBrowserContext")["browserContextId"]
            target = cdp("Target.createTarget", url="about:blank", browserContextId=browser_context,
                         background=True)["targetId"]
        else:
            target = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
        switch_tab(target)
        wait_for_load(timeout=5)   # let the blank tab's own first load commit, or it can abort ours (ERR_ABORTED)
        try:
            cdp("Emulation.setFocusEmulationEnabled", enabled=True)   # a background tab renders as if focused
        except Exception:
            pass
        _metrics(VIEW_W, VIEW_H, VIEW_DPR)
        nav = cdp("Page.navigate", url=url, _response_timeout=30)
        nav_error = nav.get("errorText") or ""
        if nav_error:
            result.update(outcome=_classify({}, nav_error), captured_at=_now_iso(), error=nav_error[:120])
            return json.dumps(result)
        _settle()
        page = _read_page()
        outcome = _classify(page, "")
        captured_at = _now_iso()
        final_url = page.get("final_url") or url
        if outcome == "captured" and _host(final_url) and _host(final_url) != _host(url) \
                and not _host(final_url).endswith("." + _host(url)) and not _host(url).endswith("." + _host(final_url)):
            outcome = "moved"
        last_modified = page.get("last_modified")
        try:   # document.lastModified is "now" when the server gave none: keep it only when it is older
            lm = datetime.strptime(last_modified, "%m/%d/%Y %H:%M:%S")
            if abs((datetime.now() - lm).total_seconds()) < 120:
                last_modified = None
        except (TypeError, ValueError):
            last_modified = None
        result.update(outcome=outcome, captured_at=captured_at, final_url=final_url,
                      http_status=page.get("http_status"), last_modified=last_modified,
                      account_visible=bool(page.get("account_visible")),
                      consent_overlay=bool(page.get("consent_overlay")), consent_box=page.get("consent_box"),
                      next_pages=page.get("next_pages") or [])
        if outcome in ("needs_login", "blocked"):
            return json.dumps(result)   # no screenshot of a wall is ever kept
        result["page"] = {k: page.get(k) for k in ("title", "description", "og", "jsonld", "outline", "fonts",
                                                   "typography", "tokens", "components", "text")}
        if outcome in ("not_found", "parked"):
            return json.dumps(result)
        result["shots"].append({"kind": "viewport", "path": _shot(out_dir, "viewport")})
        result["shots"].append({"kind": "thumb", "path": _shot(
            out_dir, "thumb", clip={"x": 0, "y": 0, "width": VIEW_W, "height": VIEW_H, "scale": THUMB_W / VIEW_W / VIEW_DPR})})
        if depth in ("look", "product", "read"):
            height = int(page.get("scroll_height") or VIEW_H)
            _scroll_through(height)
            _metrics(VIEW_W, VIEW_H, 1)
            full_h = max(VIEW_H, min(int(js("document.documentElement.scrollHeight") or height), FULL_MAX_PX))
            result["shots"].append({"kind": "full", "path": _shot(
                out_dir, "full", captureBeyondViewport=True, clip={"x": 0, "y": 0, "width": VIEW_W, "height": full_h,
                                                                  "scale": 1})})
            _metrics(VIEW_W, VIEW_H, VIEW_DPR)
        if depth == "look":
            _metrics(MOBILE_W, MOBILE_H, 2, mobile=True)   # viewport emulation only: the user agent is never changed
            time.sleep(0.8)
            result["shots"].append({"kind": "mobile", "path": _shot(out_dir, "mobile")})
            _metrics(VIEW_W, VIEW_H, VIEW_DPR)
            light_bg = js("getComputedStyle(document.body).backgroundColor")
            cdp("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
            time.sleep(0.6)
            dark_bg = js("getComputedStyle(document.body).backgroundColor")
            if page.get("dark_rule") or dark_bg != light_bg:
                result["shots"].append({"kind": "dark", "path": _shot(out_dir, "dark")})
            cdp("Emulation.setEmulatedMedia", features=[])
        return json.dumps(result)
    except Exception as exc:  # noqa: BLE001 — the agent records a failure; it never retries another way
        result.update(outcome="failed", captured_at=_now_iso(), error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return json.dumps(result)
    finally:
        for step in (lambda: cdp("Emulation.clearDeviceMetricsOverride"),
                     lambda: cdp("Emulation.setEmulatedMedia", features=[]),
                     lambda: cdp("Target.closeTarget", targetId=target) if target else None,
                     lambda: cdp("Target.disposeBrowserContext", browserContextId=browser_context)
                     if browser_context else None):
            try:
                step()
            except Exception:
                pass
