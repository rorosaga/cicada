"""Cicada's site-explore capture: one scripted visit to one saved site, inside browser-harness.

Run it in ONE browser-harness call (the harness's helpers — cdp, switch_tab, js, wait_for_load,
wait_for_network_idle — are already in scope there), with the plan Cicada's claim gave for the site:

    browser-harness <<'PY'
    exec(open("/path/to/skills/site-explore/explore_capture.py").read())
    print(explore_capture("https://example.com/", plan={...the plan JSON...}, context="signed_in"))
    PY

It prints one JSON object: the outcome, when it was captured (aware UTC), the final URL and HTTP status, the paths of
the screenshots it saved, and the page's structure (title, description, JSON-LD, the h1–h3 outline, fonts, CSS
custom properties, notable components, at most 1,500 words of visible text) and `design`: the page's computed type
and colour roles, read in the page by one bounded script (`_DESIGN_JS`: the body text, headings, captions, links and a
drop cap — family, size, weight, line-height, letter-spacing, colour — plus the page's ground and its most-used
colours). Hand those fields to `cicada_record_capture`. Cicada reads the colours and the look's hash from the pixels
itself, and checks `design` against its token schema (`api/services/design_tokens.py`). `design.specimens` are the
page's type specimens: "Aa" drawn by the page itself in each family it renders (at most six, each a transparent PNG
of at most 400x120 px, on a canvas the script never adds to the page), so the person sees the real type.

Every screenshot waits for the page to settle (`_settle`): its web fonts loaded, the images in the first viewport
complete, no layout change for 500 ms, and the animations in the viewport finished — an infinite one, or motion no
animation names (a script-driven intro), gets a short grace — all inside a hard cap of 9 seconds after the load, after
which it captures anyway. `page.settle` records how long it waited and, when it ran out, what it was still waiting on.

The plan (Cicada's, from the person's reason; G166 slice 2) says how far to go. With no reason it is the saved page
alone: a viewport and a thumbnail. A reason adds page kinds (``pages``: the front page, pricing, docs, a product page,
a blog post…) with the shots each wants (full page, mobile, dark), a section to find (``focus``), and a cap
(``max_pages``). For each further kind the script picks a link the site itself shows whose path or label names that
kind — or the page an earlier visit opened (``known``) — on the same host only, never a sign-in or account page, never
a page robots.txt disallows (read once, cookie-less, from the page's own origin; not read means no further page), and
at least ``pace_seconds`` (8) after the page before. A wall on a further page ends the visit there. ``pages=[url, …]``
lets the agent swap in its own picks (still same host, robots, cap); ``focus_heading`` names the section itself.

What it never does: sign in, type anything, click or hide a cookie or consent banner, change the user agent or any
header, retry a page that refused, touch a tab it did not open, or bring a tab to the front. A sign-in, a captcha or a
block ends the visit with outcome needs_login or blocked and no screenshot. It opens its own background tab — in the
person's signed-in session (context="signed_in") or in a fresh cookie-less browser context it creates and disposes
(context="isolated") — and closes it when done.
"""
import base64
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from urllib import robotparser
from urllib.parse import urlsplit, urlunsplit

EXPLORE_VERSION = "4"
MAX_PAGES = 6
PACE_SECONDS = 8
ROBOTS_MAX = 65536
SECTION_WORDS = 400
VIEW_W, VIEW_H, VIEW_DPR = 1440, 900, 2
THUMB_W = 640
MOBILE_W, MOBILE_H = 390, 844
FULL_MAX_PX = 12000
SCROLL_STEP, SCROLL_PAUSE = 900, 0.4
JPEG_QUALITY = 80
#: Settling before the first screenshot (looks polish, owner 2026-10-15: "the pic was taken too early"). The cap is
#: hard: after it the shot is taken anyway and ``settle.timed_out`` says what was still pending.
SETTLE_CAP = 9.0
SETTLE_NETWORK = 3.0        # the part of the cap network quiet may take
SETTLE_QUIET = 0.5          # no layout change for this long
SETTLE_POLL = 0.25
SETTLE_MOTION_GRACE = 2.5   # an infinite animation, or motion no animation names, is captured after this long
PROBE_SCALE = 0.125         # the tiny frames compared for motion: 180x112 px of the viewport
SPECIMEN_PX = 80            # "Aa" is drawn this tall (CSS px) on a canvas of at most 400x120
MAX_SPECIMENS = 6

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
  const found = []; const fseen = new Set();
  q('nav a[href], header a[href], footer a[href], main a[href], [role=navigation] a[href]').forEach(a => {
    if (found.length >= 120 || a.hostname !== host) return;
    const u = a.href.split('#')[0].split('?')[0]; if (fseen.has(u)) return; fseen.add(u);
    found.push({url: u, label: (a.innerText || a.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 80)}); });
  return JSON.stringify({
    title: (document.title || '').replace(/^\u{1F434}\s*/u, ''), description: meta('description') || meta('og:description'),
    og: {site_name: meta('og:site_name'), title: meta('og:title'), image: meta('og:image')},
    jsonld: ld, outline, fonts: fonts.slice(0, 12), typography, tokens, components: comps,
    text: text.replace(/\s+/g, ' ').trim().split(' ').slice(0, 1500).join(' '),
    final_url: location.href, http_status: nav.responseStatus || null, last_modified: document.lastModified || null,
    scroll_height: Math.min(document.documentElement.scrollHeight || 0, 100000),
    consent_overlay: !!consentBox, consent_box: consentBox, consent_wall: consentWall,
    account_visible: account, captcha, password_wall: password, parked, dark_rule: darkRule, next_pages: next,
    found
  });
})()
"""


#: The page's computed type and colour roles (looks v2). Computed styles, not stylesheet text: a framework's hashed font
#: names (``__Newsreader_a1b2c3``) are what the page renders, and Cicada cleans them. Bounded: at most 400 paragraphs
#: looked at for the body text and 2,500 visible elements sampled for the colours; nothing is clicked, typed or changed.
_DESIGN_JS = r"""
(() => {
  const vis = e => { if (!e) return false; const r = e.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false; const c = getComputedStyle(e);
    return c.display !== 'none' && c.visibility !== 'hidden' && c.opacity !== '0'; };
  const pick = sels => { for (const s of sels) { let all; try { all = document.querySelectorAll(s); } catch (e) { continue; }
    for (const e of Array.from(all).slice(0, 200)) { if (vis(e) && (e.innerText || '').trim()) return e; } } return null; };
  const style = (e, pseudo) => { if (!e) return null; const c = getComputedStyle(e, pseudo || null);
    return {family: c.fontFamily, size: c.fontSize, weight: c.fontWeight, line_height: c.lineHeight,
            letter_spacing: c.letterSpacing, color: c.color}; };
  const rgb = v => { const m = /rgba?\(([^)]+)\)/.exec(v || ''); if (!m) return null;
    const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number); if (p.length > 3 && p[3] < 0.05) return null; return p.slice(0, 3); };
  const hex = p => '#' + p.map(x => Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, '0')).join('');
  const chroma = p => (Math.max(...p) - Math.min(...p)) / 255;
  const paras = Array.from(document.querySelectorAll('main p, article p, p')).slice(0, 400).filter(vis);
  const body = paras.slice().sort((a, b) => (b.innerText || '').length - (a.innerText || '').length)[0] || document.body;
  const heading = pick(['h1', 'h2']);
  const sub = pick(['h2', 'h3']);
  const type = {body: style(body), heading: style(heading),
    subheading: sub && sub !== heading ? style(sub) : null,
    caption: style(pick(['figcaption', 'caption', '[class*="caption" i]', 'small', 'time'])),
    link: style(pick(['main p a[href]', 'article p a[href]', 'p a[href]', 'main a[href]', 'a[href]']))};
  const first = paras[0];
  if (first) { const fl = getComputedStyle(first, '::first-letter'); const base = parseFloat(getComputedStyle(first).fontSize) || 16;
    if ((parseFloat(fl.fontSize) || 0) > base * 1.6 || (fl.cssFloat || fl.float) === 'left') type.drop_cap = style(first, '::first-letter'); }
  Object.keys(type).forEach(k => { if (!type[k]) delete type[k]; });
  let ground = rgb(getComputedStyle(document.body).backgroundColor) || rgb(getComputedStyle(document.documentElement).backgroundColor) || [255, 255, 255];
  const text = {}, area = {};
  const add = (bag, p, w) => { if (!p) return; const h = hex(p); bag[h] = (bag[h] || 0) + w; };
  const els = Array.from(document.querySelectorAll('body *')).slice(0, 2500);
  for (const e of els) { const r = e.getBoundingClientRect(); if (r.width < 1 || r.height < 1 || r.top > innerHeight * 3) continue;
    const c = getComputedStyle(e); if (c.visibility === 'hidden' || c.display === 'none') continue;
    const own = Array.from(e.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('').length;
    if (own) add(text, rgb(c.color), own);
    add(area, rgb(c.backgroundColor), Math.min(r.width * r.height, innerWidth * innerHeight));
    if (parseFloat(c.borderTopWidth) > 0 && c.borderTopStyle !== 'none') add(text, rgb(c.borderTopColor), r.width); }
  const gh = hex(ground);
  const rank = bag => Object.entries(bag).sort((a, b) => b[1] - a[1]).map(([h]) => h);
  const used = [...new Set([...rank(text).slice(0, 6), ...rank(area).filter(h => h !== gh).slice(0, 4)])].slice(0, 10);
  const parse = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const ink = type.body ? rgb(type.body.color) : null;
  const linkc = type.link ? rgb(type.link.color) : null;
  const accent = [linkc, ...used.map(parse)].find(p => p && chroma(p) >= 0.3);
  const lum = p => p.reduce((s, x) => s + x, 0) / 3;
  const wash = rank(area).map(parse).find(p => hex(p) !== gh && chroma(p) > 0.02 && Math.abs(lum(p) - lum(ground)) < 60);
  const colors = {ground: gh}; if (ink) colors.ink = hex(ink); if (accent) colors.accent = hex(accent); if (wash) colors.wash = hex(wash);
  return JSON.stringify({type, colors, used});
})()
"""

#: One look at whether the page has settled, read-only: fonts, first-viewport images, a layout signature (offsets,
#: which ignore transforms, of up to 400 elements in the first viewport, plus the page height), and the running
#: animations and transitions in the first viewport (finite ones with the time they have left; infinite ones counted).
_SETTLE_JS = r"""
(() => {
  const vh = innerHeight, vw = innerWidth;
  const inView = r => r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
  let pendingImages = 0;
  for (const img of Array.from(document.images).slice(0, 400)) {
    if (!img.complete && inView(img.getBoundingClientRect())) pendingImages++; }
  const sig = [document.documentElement.scrollHeight];
  let n = 0;
  for (const e of Array.from(document.querySelectorAll('body *')).slice(0, 3000)) {
    if (n >= 400) break; const r = e.getBoundingClientRect(); if (!inView(r)) continue; n++;
    sig.push(e.offsetLeft, e.offsetTop, e.offsetWidth, e.offsetHeight); }
  let finite = 0, infinite = 0, left = 0;
  const anims = document.getAnimations ? document.getAnimations().slice(0, 500) : [];
  for (const a of anims) {
    if (a.playState !== 'running' || !a.effect) continue;
    const t = a.effect.target; if (!t || !t.getBoundingClientRect || !inView(t.getBoundingClientRect())) continue;
    const ct = a.effect.getComputedTiming();
    if (!isFinite(ct.endTime)) { infinite++; continue; }
    finite++; left = Math.max(left, ((ct.endTime || 0) - (ct.localTime || 0)) / Math.abs(a.playbackRate || 1)); }
  return JSON.stringify({fonts: document.fonts ? document.fonts.status : 'loaded', images: pendingImages,
    layout: sig.join(','), finite, infinite, left: Math.round(left), ready: document.readyState});
})()
"""

#: The type specimens: "Aa" drawn in each family the page renders, by the page's own font engine with its own loaded
#: faces, on a canvas that is never added to the page. A face that is not loaded within 1.5 s is left out (a
#: specimen in a fallback face would mislead). Read-only for the page; returns PNG data URLs.
_SPECIMEN_JS = r"""
(async (items) => {
  const out = [];
  for (const it of items) {
    const font = `${it.style || 'normal'} ${it.weight || 400} %dpx ${it.stack}`;
    try { await Promise.race([document.fonts.load(font, 'Aa'), new Promise(r => setTimeout(r, 1500))]); } catch (e) {}
    let loaded = true; try { loaded = document.fonts.check(font, 'Aa'); } catch (e) {}
    if (!loaded) continue;
    const c = document.createElement('canvas'); let ctx = c.getContext('2d'); ctx.font = font;
    const w = ctx.measureText('Aa').width;
    c.width = Math.max(16, Math.min(400, Math.ceil(w + 24))); c.height = 120;
    ctx = c.getContext('2d'); ctx.font = font; ctx.fillStyle = '#000'; ctx.textBaseline = 'alphabetic';
    ctx.fillText('Aa', 12, 96);
    out.push({stack: it.stack, data: c.toDataURL('image/png')});
  }
  return JSON.stringify(out);
})(%%s)
""" % SPECIMEN_PX

_ROBOTS_JS = r"""
fetch('/robots.txt', {credentials: 'omit', redirect: 'follow', cache: 'no-store'})
  .then(r => r.text().then(t => JSON.stringify({status: r.status, text: t.slice(0, %d)})))
  .catch(e => JSON.stringify({status: null, error: String(e).slice(0, 120)}))
""" % ROBOTS_MAX

_SECTION_JS = r"""
((want) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const h = Array.from(document.querySelectorAll('h1,h2,h3,h4')).find(e => norm(e.innerText) === want);
  if (!h) return JSON.stringify(null);
  const level = +h.tagName[1]; const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT); walker.currentNode = h;
  let n; while ((n = walker.nextNode())) {
    if (/^H[1-4]$/.test(n.tagName) && +n.tagName[1] <= level) break;
    if (['P', 'LI', 'PRE', 'BLOCKQUOTE', 'DD'].includes(n.tagName)) out.push(norm(n.innerText)); }
  return JSON.stringify({heading: want, text: out.join(' ').split(' ').slice(0, %d).join(' ')});
})(%%s)
""" % SECTION_WORDS


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now_ms():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _shot(out_dir, name, **params):
    """One JPEG screenshot of the attached tab, saved under ``out_dir``; returns its path."""
    data = cdp("Page.captureScreenshot", _response_timeout=60, format="jpeg", quality=JPEG_QUALITY, **params)["data"]
    path = os.path.join(out_dir, f"{name}.jpg")
    with open(path, "wb") as handle:
        handle.write(base64.b64decode(data))
    return path


def _metrics(width, height, dpr, mobile=False):
    cdp("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=dpr, mobile=mobile)


def _probe():
    try:
        got = json.loads(js(_SETTLE_JS) or "null")
    except Exception:  # noqa: BLE001
        return None
    return got if isinstance(got, dict) else None


def _frame():
    """A tiny frame of the viewport (180x112 px) — compared, never kept — to see whether anything still moves."""
    try:
        return cdp("Page.captureScreenshot", _response_timeout=10, format="jpeg", quality=50,
                   clip={"x": 0, "y": 0, "width": VIEW_W, "height": VIEW_H, "scale": PROBE_SCALE / VIEW_DPR})["data"]
    except Exception:  # noqa: BLE001
        return None


def _settle(cap=SETTLE_CAP):
    """Wait until the page has settled, at most ``cap`` seconds after its load event: the web fonts loaded, the images
    in the first viewport complete (or failed), no layout change for :data:`SETTLE_QUIET`, the viewport's finite
    animations and transitions finished, and the viewport's pixels still across two frames — an infinite animation,
    or motion no animation names (a script-driven intro), gets :data:`SETTLE_MOTION_GRACE` from the load instead.
    Returns what it recorded: ``{ms, timed_out, waiting_on?, motion?}``. A page whose state cannot be read is not
    waited on."""
    wait_for_load(timeout=20)
    start = time.monotonic()
    deadline = start + cap
    try:
        wait_for_network_idle(timeout=min(SETTLE_NETWORK, cap), idle_ms=500)
    except Exception:
        pass
    last_sig, sig_since, last_frame = None, time.monotonic(), None
    pending: list[str] = []
    while True:
        now = time.monotonic()
        state = _probe()
        if state is None:
            return {"ms": int((now - start) * 1000), "timed_out": False, "unread": True}
        sig = state.get("layout")
        if sig != last_sig:
            last_sig, sig_since = sig, now
        pending = []
        if state.get("fonts") != "loaded":
            pending.append("fonts")
        if state.get("images"):
            pending.append("images")
        if now - sig_since < SETTLE_QUIET:
            pending.append("layout")
        if state.get("finite"):
            pending.append("animations")
        motion = None
        if not pending:
            graced = now - start >= SETTLE_MOTION_GRACE
            if state.get("infinite") and graced:
                motion = "looping"
            else:
                frame = _frame()
                if frame is not None and frame == last_frame:
                    motion = "still"
                elif graced and last_frame is not None:
                    motion = "moving"
                last_frame = frame
                if motion is None:
                    pending.append("motion")
        if not pending:
            out = {"ms": int((time.monotonic() - start) * 1000), "timed_out": False}
            if motion and motion != "still":
                out["motion"] = motion
            return out
        if time.monotonic() >= deadline:
            return {"ms": int((time.monotonic() - start) * 1000), "timed_out": True, "waiting_on": pending}
        wait = SETTLE_POLL
        if pending == ["animations"] and state.get("left"):
            wait = max(SETTLE_POLL, min(state["left"] / 1000 + 0.05, 1.0))
        time.sleep(max(0.0, min(wait, deadline - time.monotonic())))


def _read_page():
    return json.loads(js(_PAGE_JS))


def _read_design(out_dir=None, prefix=""):
    """The page's computed type and colour roles, or None when the script could not read them (the capture stands).
    With ``out_dir``, also its type specimens (:func:`_specimens`) as ``specimens``."""
    try:
        got = json.loads(js(_DESIGN_JS) or "null")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(got, dict):
        return None
    if out_dir is not None and (specs := _specimens(out_dir, prefix, got)):
        got["specimens"] = specs
    return got


def _specimens(out_dir, prefix, design):
    """``[{family, path}]``: "Aa" in each distinct family the page renders (body first, at most six), drawn by the
    page's own font engine (``_SPECIMEN_JS``) and saved as PNGs under ``out_dir``. Never fatal."""
    items, seen = [], set()
    for role in ("body", "heading", "subheading", "caption", "link", "drop_cap"):
        t = ((design or {}).get("type") or {}).get(role)
        stack = (t or {}).get("family") if isinstance(t, dict) else None
        if not isinstance(stack, str) or not stack.strip() or len(stack) > 400 or stack.strip().lower() in seen:
            continue
        seen.add(stack.strip().lower())
        items.append({"stack": stack.strip(), "weight": str((t or {}).get("weight") or "400")[:4]})
        if len(items) >= MAX_SPECIMENS:
            break
    if not items:
        return []
    try:
        drawn = json.loads(js(_SPECIMEN_JS % json.dumps(items)) or "[]")
    except Exception:  # noqa: BLE001
        return []
    out = []
    for i, item in enumerate(drawn if isinstance(drawn, list) else [], 1):
        data = str((item or {}).get("data") or "")
        if not data.startswith("data:image/png;base64,"):
            continue
        path = os.path.join(out_dir, f"{prefix}type-{i}.png")
        try:
            with open(path, "wb") as handle:
                handle.write(base64.b64decode(data.split(",", 1)[1]))
        except (OSError, ValueError):
            continue
        out.append({"family": item.get("stack"), "path": path})
    return out


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


def _plan_from_depth(depth):
    """A plan for a bare depth word (a call without Cicada's plan): the saved page with the depth's shots."""
    shots = {"capture": ["viewport"], "look": ["viewport", "full", "mobile", "dark"], "product": ["viewport", "full"],
             "read": ["viewport", "full"]}.get(depth, ["viewport"])
    return {"depth": depth, "max_pages": 1, "pace_seconds": PACE_SECONDS, "pages": [{"kind": "saved", "shots": shots}]}


def _clean(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", "", ""))


def _segments(url):
    path = (urlsplit(url).path or "/").lower()
    return [s for s in path.replace("_", "/").replace(".", "/").split("/") if s]


def _matches(url, label, words):
    segs = _segments(url)
    if any(s == w or s.startswith(w + "-") for s in segs for w in words):
        return True
    lab = " " + " ".join((label or "").lower().split()) + " "
    return any(f" {w} " in lab for w in words)


def _avoided(url, label, plan):
    segs = _segments(url)
    joined = "/".join(segs)
    avoid = plan.get("avoid") or []
    if any(w in segs or joined.startswith(w) for w in avoid):
        return True
    lab = " " + " ".join((label or "").lower().split()) + " "
    return any(f" {w} " in lab for w in avoid) or url in set(plan.get("avoid_urls") or [])


def _read_robots():
    """robots.txt as this tab's own origin serves it, cookie-less. ``(raw, parser)``; parser None when unread."""
    try:
        raw = json.loads(js(_ROBOTS_JS) or "null") or {}
    except Exception as exc:  # noqa: BLE001
        raw = {"status": None, "error": f"{type(exc).__name__}"}
    status = raw.get("status")
    if not isinstance(status, int):
        return {"status": None}, None
    parser = robotparser.RobotFileParser()
    if status in (401, 403) or status >= 500:
        parser.disallow_all = True
    elif status >= 400:
        parser.allow_all = True
    else:
        parser.parse(str(raw.get("text") or "").splitlines()[:2000])
    return {"status": status, "text": str(raw.get("text") or "")[:ROBOTS_MAX]}, parser


def _robots_ok(parser, url):
    if parser is None:
        return False
    try:
        return bool(parser.can_fetch("*", url))
    except Exception:  # noqa: BLE001
        return False


def _pick_pages(plan, landing, found, parser, chosen=None):
    """``[(kind, url, chosen_by)]`` for the plan's further kinds: the agent's own picks first (same host, robots,
    cap), else for each kind the page an earlier visit opened when the site still links it, else the first link the
    site shows whose path or label names the kind. Never the saved page again, a sign-in page or a disallowed one."""
    host = (urlsplit(landing).hostname or "").lower()
    cap = max(0, min(int(plan.get("max_pages") or 1), MAX_PAGES) - 1)
    wanted = [p for p in plan.get("pages") or [] if p.get("kind") not in ("saved",)]
    landing_root = len(_segments(landing)) == 0
    links = [(c, l.get("label") or "") for l in found or [] if (c := _clean(l.get("url") or ""))]
    usable = lambda u, lab="": (u and (urlsplit(u).hostname or "").lower() == host and u != _clean(landing)  # noqa: E731
                                and not _avoided(u, lab, plan) and _robots_ok(parser, u))
    picks, used = [], set()
    for url in chosen or []:
        u = _clean(str(url))
        if len(picks) < cap and usable(u) and u not in used:
            kind = next((p["kind"] for p in wanted if _matches(u, "", p.get("match") or [])), "other")
            picks.append((kind, u, "agent"))
            used.add(u)
    if chosen:
        return picks
    for page in wanted:
        if len(picks) >= cap:
            break
        kind = page.get("kind")
        if kind == "home":
            if landing_root:
                continue
            u = _clean(f"{urlsplit(landing).scheme}://{urlsplit(landing).netloc}/")
            if usable(u) and u not in used:
                picks.append((kind, u, "script"))
                used.add(u)
            continue
        known = _clean(page.get("known") or "")
        if known and known in {c for c, _ in links} and usable(known) and known not in used:
            picks.append((kind, known, "script"))
            used.add(known)
            continue
        for u, label in links:
            if u not in used and _matches(u, label, page.get("match") or []) and usable(u, label):
                picks.append((kind, u, "script"))
                used.add(u)
                break
    return picks


def _section(page, plan, focus_heading=None):
    """The part of the saved page the person's words point at: the outline heading with the most focus words (or
    the agent's ``focus_heading``), and its text."""
    outline = [h.get("text") for h in page.get("outline") or [] if h.get("text")]
    want, by = None, "script"
    if focus_heading and focus_heading in outline:
        want, by = focus_heading, "agent"
    else:
        terms = [t.lower() for t in plan.get("focus") or []]
        best = 0
        for text in outline:
            score = sum(1 for t in terms if t in text.lower())
            if score > best:
                want, best = text, score
    if not want:
        return None
    try:
        got = json.loads(js(_SECTION_JS % json.dumps(want)) or "null")
    except Exception:  # noqa: BLE001
        return None
    if not got or not got.get("text"):
        return None
    got["chosen_by"] = by
    return got


def _shots(out_dir, prefix, wants, page):
    """The shots ``wants`` asks for on the page in the attached tab; returns ``[{kind, path}]``."""
    out = [{"kind": "viewport", "path": _shot(out_dir, f"{prefix}viewport")},
           {"kind": "thumb", "path": _shot(out_dir, f"{prefix}thumb", clip={"x": 0, "y": 0, "width": VIEW_W,
                                                                             "height": VIEW_H,
                                                                             "scale": THUMB_W / VIEW_W / VIEW_DPR})}]
    if "full" in wants:
        height = int(page.get("scroll_height") or VIEW_H)
        _scroll_through(height)
        _metrics(VIEW_W, VIEW_H, 1)
        full_h = max(VIEW_H, min(int(js("document.documentElement.scrollHeight") or height), FULL_MAX_PX))
        out.append({"kind": "full", "path": _shot(out_dir, f"{prefix}full", captureBeyondViewport=True,
                                                   clip={"x": 0, "y": 0, "width": VIEW_W, "height": full_h,
                                                         "scale": 1})})
        _metrics(VIEW_W, VIEW_H, VIEW_DPR)
    if "mobile" in wants:
        _metrics(MOBILE_W, MOBILE_H, 2, mobile=True)   # viewport emulation only: the user agent is never changed
        time.sleep(0.8)
        out.append({"kind": "mobile", "path": _shot(out_dir, f"{prefix}mobile")})
        _metrics(VIEW_W, VIEW_H, VIEW_DPR)
    if "dark" in wants:
        light_bg = js("getComputedStyle(document.body).backgroundColor")
        cdp("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
        time.sleep(0.6)
        dark_bg = js("getComputedStyle(document.body).backgroundColor")
        if page.get("dark_rule") or dark_bg != light_bg:
            out.append({"kind": "dark", "path": _shot(out_dir, f"{prefix}dark")})
        cdp("Emulation.setEmulatedMedia", features=[])
    return out


def _wait_pace(last_load, pace):
    """Never sooner than ``pace`` seconds after the page before (a person's pace), with half a second to spare."""
    if last_load is not None:
        left = pace + 0.5 - (time.monotonic() - last_load)
        if left > 0:
            time.sleep(left)


def _page_fields(page):
    return {k: page.get(k) for k in ("title", "description", "outline", "fonts", "tokens", "components")}


def explore_capture(url, depth="capture", context="signed_in", out_dir=None, plan=None, pages=None,
                    focus_heading=None):
    """Visit ``url`` and capture it as ``plan`` says. Returns the JSON string to hand to ``cicada_record_capture``."""
    if isinstance(plan, str):
        plan = json.loads(plan)
    plan = plan if isinstance(plan, dict) and plan.get("pages") else _plan_from_depth(
        depth if depth in ("capture", "look", "product", "read") else "capture")
    depth = str(plan.get("depth") or "capture")
    pace = max(PACE_SECONDS, int(plan.get("pace_seconds") or PACE_SECONDS))
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
        result["loaded_at"] = _now_ms()
        last_load = time.monotonic()
        nav = cdp("Page.navigate", url=url, _response_timeout=30)
        nav_error = nav.get("errorText") or ""
        if nav_error:
            result.update(outcome=_classify({}, nav_error), captured_at=_now_iso(), error=nav_error[:120])
            return json.dumps(result)
        settled = _settle()
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
        result["page"]["settle"] = settled
        if outcome in ("not_found", "parked"):
            return json.dumps(result)
        wants = (plan.get("pages") or [{}])[0].get("shots") or ["viewport"]
        design = _read_design(out_dir, "")
        if design:
            result["design"] = design
        result["shots"] = _shots(out_dir, "", wants, page)
        if plan.get("section"):
            section = _section(page, plan, focus_heading)
            if section:
                result["section"] = section
        further = [p for p in plan.get("pages") or [] if p.get("kind") != "saved"]
        if not further and not pages:
            return json.dumps(result)
        result["found"] = (page.get("found") or [])[:120]
        robots, parser = _read_robots()
        result["robots"] = robots
        picks = _pick_pages(plan, final_url, result["found"], parser, chosen=pages)
        by_kind = {p.get("kind"): p for p in plan.get("pages") or []}
        result["pages"] = []
        for i, (kind, page_url, chosen_by) in enumerate(picks, 1):
            _wait_pace(last_load, pace)
            entry = {"url": page_url, "kind": kind, "chosen_by": chosen_by, "loaded_at": _now_ms()}
            last_load = time.monotonic()
            result["loads"] += 1
            nav = cdp("Page.navigate", url=page_url, _response_timeout=30)
            if nav.get("errorText"):
                entry["outcome"] = _classify({}, nav.get("errorText"))
                result["pages"].append(entry)
                continue
            sub_settled = _settle()
            sub = _read_page()
            entry.update(outcome=_classify(sub, ""), http_status=sub.get("http_status"),
                         final_url=sub.get("final_url") or page_url)
            if entry["outcome"] in ("needs_login", "blocked"):
                result["pages"].append(entry)
                break   # a wall ends the visit: no screenshot of it, nothing after it
            entry["page"] = {**_page_fields(sub), "settle": sub_settled}
            if entry["outcome"] == "captured" and (sub_design := _read_design(out_dir, f"p{i}-")):
                entry["design"] = sub_design
            if entry["outcome"] == "captured":
                wants = (by_kind.get(kind) or {}).get("shots") or ["viewport"]
                entry["shots"] = _shots(out_dir, f"p{i}-", wants, sub)
            result["pages"].append(entry)
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
