"""How far to explore one saved site, from the person's reason (G166 slice 2, owner 2026-10-14 evening).

"By default we explore the bare minimum of a website … unless the query makes the agent look further inside the
website. If I say 'I love the design' in all the pages or something like that (or not so explicitly), then the agent
has a reason to dive into the website."

The default stays minimal (D4 a): the landing page's viewport and its metadata. Depth follows the person's reason, and
the reason is read from three places, all deterministic and all already in the bank:

* **The explicit answer** — G191's ``saved_why.reasons`` ids (``design``, ``product``, ``technique``, ``read_later``)
  and a project (``product``'s plan).
* **The person's own words about the save** — ``saved_why.text`` and a ``## Saved because`` section on the link's
  episode — read through closed keyword families (English and Spanish), so "love how every page looks" means the
  design, across the site, and "their docs are great" names the docs page.
* **What they said about it in conversations** — the current claims on the saved page whose evidence is the person's
  own turn (``evidence.kind == "user"``) or that are ``user_stated``, read through the same families.
* **One ask on the link** (looks v2, 2026-10-15) — the queue row's ``asked``: ``look`` is the person's "Save its look"
  click (or a trusted agent they asked), a design reason whose landing picture becomes a Look even when the look has
  not changed since the last visit (``save_look``).

**The split (owner's question: "say how you split it").** Cicada's backend never calls a model to plan. It turns the
reason into a **plan** — which kinds of pages to visit, in order, what to capture on each, the page cap, the words to
find the relevant section by, whether the best captures become Looks — and it is the plan's floor and ceiling: the
record is checked against it (the cap, the pace, robots.txt, the host). The person's own agent supplies the judgment
*while it explores*: the capture script picks a page for each kind from the links the site itself shows, and the agent
may swap in a page it judges more representative (same host, allowed by robots.txt, never past the cap) or name the
section that answers the person's words. Nothing the agent says can make a visit deeper than the plan.

Pure functions plus one read of the saved page and its episode. Nothing here writes, fetches or opens a browser.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlsplit, urlunsplit

PLAN_V = 1
#: A visit never loads more pages of one site than this (the landing page included).
MAX_PAGES = 6
#: Never faster than a person would browse (slice 1's rail, ``explore_queue.PACE_SECONDS``).
PACE_SECONDS = 8
#: The shot kinds a page can ask for (``site_captures.SHOT_KINDS`` minus the thumbnail, which rides the viewport).
SHOTS = ("viewport", "full", "mobile", "dark")
DEPTHS = ("capture", "read", "product", "look")
REASONS = ("design", "product", "technique", "read_later")
MAX_FOCUS = 8
MAX_SAID = 12

#: What a page is, by its path and its link label: ``kind → words``. A path segment or a label word that equals or
#: starts with one of these names the kind. The capture script receives the words it needs in the plan, so this table
#: is the one place a page kind is defined (the script carries no table of its own).
PAGE_KINDS: dict[str, tuple[str, ...]] = {
    "pricing": ("pricing", "plans", "price", "prices", "precios", "planes", "tarifas"),
    "docs": ("docs", "documentation", "developers", "developer", "guides", "guide", "reference", "api", "manual",
             "documentacion", "documentación"),
    "product": ("product", "products", "features", "feature", "platform", "solutions", "tour", "how-it-works",
                "producto", "productos", "caracteristicas", "características"),
    "blog": ("blog", "posts", "articles", "journal", "news", "stories", "writing", "noticias", "articulos"),
    "about": ("about", "about-us", "company", "team", "who-we-are", "nosotros", "empresa", "equipo"),
    "changelog": ("changelog", "releases", "release-notes", "updates", "whats-new", "novedades"),
    "showcase": ("showcase", "customers", "examples", "gallery", "work", "case-studies", "clientes", "galeria"),
}
#: Pages an explore visit never opens: signing in, accounts, carts. The script skips them and the record drops them.
AVOID: tuple[str, ...] = ("login", "log-in", "signin", "sign-in", "signup", "sign-up", "register", "account",
                          "accounts", "checkout", "cart", "logout", "log-out", "signout", "password", "auth", "oauth",
                          "sso", "subscribe", "unsubscribe", "admin", "dashboard", "settings", "cuenta", "registro",
                          "iniciar-sesion", "carrito")

#: Each reason's plan (design §2.5, amended by the owner 2026-10-14 evening): the page kinds after the saved page
#: (``home`` is the site's front page, skipped when the saved page is it), the shots on the saved page (``home`` here)
#: and on every other page, the depth word the queue and the record carry.
_PLANS: dict[str, dict] = {
    "design": {"kinds": ("home", "pricing", "docs", "product", "blog"), "home": SHOTS, "other": SHOTS, "depth": "look",
               "auto_look": True},
    "product": {"kinds": ("home", "pricing", "about", "docs"), "home": ("viewport", "full"), "other": ("viewport",),
                "depth": "product", "lift": True},
    "technique": {"kinds": (), "home": ("viewport", "full"), "other": ("viewport",), "depth": "read",
                  "section": True},
    "read_later": {"kinds": (), "home": ("viewport",), "other": ("viewport",), "depth": "capture"},
}
_MINIMAL = {"kinds": (), "home": ("viewport",), "other": ("viewport",), "depth": "capture"}
#: "Every page", "the whole site": the person meant more than a sample, so a design plan widens to these kinds too.
_WIDE_KINDS = ("about", "showcase", "changelog")

#: The closed keyword families the person's words are read through. Each is a list of regexes over lowercased text,
#: matched on word boundaries. A family is a reason; ``wide`` widens; a page kind's own words name that page.
_FAMILIES: dict[str, tuple[str, ...]] = {
    "design": (r"design(?:ed|s)?", r"look(?:s)?(?! for| into| up| at)", r"look and feel", r"beautiful", r"gorgeous",
               r"pretty", r"aesthetic(?:s)?", r"typograph(?:y|ic)", r"fonts?", r"typefaces?", r"colou?rs?",
               r"palettes?", r"layouts?", r"ui", r"ux", r"visual(?:s|ly)?", r"styl(?:e|ed|ing)", r"animations?",
               r"motion", r"illustrations?", r"branding", r"minimal(?:ist)?", r"landing page", r"diseño",
               r"bonit[oa]s?", r"est[ée]tica", r"tipograf[íi]a", r"colores", r"se ve(?:n)? (?:bien|incre[íi]ble)"),
    "product": (r"products?", r"tools?", r"apps?", r"services?", r"pric(?:e|es|ing)", r"costs?", r"alternatives?",
                r"competitors?", r"startups?", r"compan(?:y|ies)", r"saas", r"platforms?", r"what (?:it|they) do(?:es)?",
                r"producto", r"herramienta", r"precios?", r"competencia", r"alternativa"),
    "technique": (r"how to", r"how they", r"techniques?", r"tricks?", r"patterns?", r"approach(?:es)?", r"methods?",
                  r"implement(?:ation|ed|ing)?", r"tutorials?", r"learn(?:ing)?", r"reuse", r"recipes?",
                  r"snippets?", r"algorithms?", r"explain(?:s|ed|er)?", r"t[ée]cnica", r"c[óo]mo (?:lo )?hac",
                  r"truco", r"patr[óo]n", r"aprender"),
    "read_later": (r"read (?:it )?later", r"to read", r"long read", r"essays?", r"articles?", r"leer (?:despu[ée]s|luego)",
                   r"art[íi]culo"),
    "wide": (r"every page", r"all (?:the |of the |their )?pages", r"each page", r"whole (?:site|website)",
             r"entire (?:site|website)", r"across the (?:site|website)", r"everywhere", r"all over",
             r"todas las p[áa]ginas", r"todo el (?:sitio|web)", r"cada p[áa]gina"),
}
_STOP = frozenset("""the a an and or but of to in on for with this that these those it its they their them is are was
were be been very really just love loved like liked great good nice cool amazing awesome much many how what why
when where which who there here from into about all every each site website page pages saved save want wanted would
could should more most some any also than then because como para que los las del una uno con por pero muy esto esta
este todo toda""".split())
_WORD = re.compile(r"[a-záéíóúñü][a-z0-9áéíóúñü'-]{3,}")


def _compiled() -> dict[str, re.Pattern]:
    return {name: re.compile(r"\b(?:" + "|".join(pats) + r")\b", re.I) for name, pats in _FAMILIES.items()}


_FAMILY_RES = _compiled()
_KIND_RES = {kind: re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", re.I)
             for kind, words in PAGE_KINDS.items()}


# --------------------------------------------------------------------------- reading the person's words


def signals(text: str) -> dict:
    """What a piece of the person's words asks for: ``{reasons: [...], wide: bool, kinds: [...], words: [...]}`` —
    the matched words are kept so a plan can say *why* (never the whole sentence)."""
    text = " ".join(str(text or "").lower().split())
    out: dict = {"reasons": [], "wide": False, "kinds": [], "words": []}
    if not text:
        return out
    for name, rx in _FAMILY_RES.items():
        hits = [m.group(0) for m in rx.finditer(text)]
        if not hits:
            continue
        out["words"] += hits
        if name == "wide":
            out["wide"] = True
        else:
            out["reasons"].append(name)
    for kind, rx in _KIND_RES.items():
        hits = [m.group(0) for m in rx.finditer(text)]
        if hits:
            out["kinds"].append(kind)
            out["words"] += hits
    out["words"] = list(dict.fromkeys(out["words"]))[:8]
    return out


def focus_terms(texts: list[str]) -> list[str]:
    """Up to :data:`MAX_FOCUS` content words from the person's words — what the relevant section is found by."""
    out: list[str] = []
    for text in texts:
        for word in _WORD.findall(str(text or "").lower()):
            word = word.strip("'-")
            if word in _STOP or len(word) < 4 or word in out:
                continue
            if any(rx.fullmatch(word) for rx in _FAMILY_RES.values()):
                continue
            out.append(word)
    return out[:MAX_FOCUS]


def said_in_conversations(memory_path: Path, entity_id: str) -> list[str]:
    """The person's own words about a saved page from their conversations: the current claims on its page whose
    evidence is the person's turn, or that the person stated. Read-only; [] when the page has none or is unreadable."""
    from api.services import claims, markdown_parser

    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,120}", str(entity_id or "")):
        return []
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    if not path.is_file():
        return []
    try:
        parsed = markdown_parser.parse(path)
        found = claims.parse_claims(parsed.body)
    except Exception:  # noqa: BLE001 — a hand-broken page plans as if nothing was said
        return []
    out = []
    for claim in found:
        # Current beliefs only, and never an event (a dated happening says what was done, not why it was saved).
        if claims.is_event(claim) or not claims.is_current(claim):
            continue
        persons = claim.source_trust == "user_stated" or any(e.kind == "user" for e in claim.evidence or [])
        if persons and str(claim.text or "").strip():
            out.append(" ".join(str(claim.text).split())[:400])
    return out[:MAX_SAID]


def saved_because(memory_path: Path, episode_id: str | None) -> str | None:
    """The ``## Saved because`` section a save carried (a Telegram ``/save`` reason), or None."""
    from api.services import markdown_parser

    if not episode_id or not re.fullmatch(r"ep_[0-9A-Za-z_-]{1,80}", str(episode_id)):
        return None
    path = Path(memory_path) / "episodes" / f"{episode_id}.md"
    try:
        body = markdown_parser.parse(path).body
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"(?m)^## Saved because[ \t]*$", body or "")
    if m is None:
        return None
    rest = body[m.end():]
    nxt = re.search(r"(?m)^## ", rest)
    return " ".join((rest[: nxt.start()] if nxt else rest).split())[:500] or None


# --------------------------------------------------------------------------- the plan


def plan_for(why: dict | None = None, *, words: list[str] | None = None, said: list[str] | None = None,
             known: dict[str, str] | None = None, walled: list[str] | None = None, asked: str | None = None) -> dict:
    """The plan for one site, deterministic.

    ``why`` is G191's answer (``reasons``, ``project``, ``text``); ``words`` any other words the person wrote about the
    save; ``said`` what they said about it in conversations; ``known`` the site map's ``{kind: url}`` from an earlier
    visit (so a re-visit opens the same pricing page and the two captures compare); ``walled`` pages an earlier visit
    found behind a sign-in or a block (never opened again — the ToS rail)."""
    why = why if isinstance(why, dict) else {}
    because: list[dict] = []
    reasons: list[str] = []
    if asked == "look":
        reasons.append("design")
        because.append({"from": "ask", "signal": "look"})
    for r in why.get("reasons") or []:
        if r in REASONS and r not in reasons:
            reasons.append(r)
            because.append({"from": "reason", "signal": r})
    if why.get("project"):
        if "product" not in reasons:
            reasons.append("product")
        because.append({"from": "reason", "signal": "project"})
    wide = False
    named: list[str] = []
    texts = [t for t in [why.get("text"), *(words or [])] if isinstance(t, str) and t.strip()]
    for source, items in (("text", texts), ("conversation", [s for s in said or [] if isinstance(s, str)])):
        for item in items:
            sig = signals(item)
            if not (sig["reasons"] or sig["wide"] or sig["kinds"]):
                continue
            for r in sig["reasons"]:
                if r not in reasons:
                    reasons.append(r)
            wide = wide or sig["wide"]
            named += [k for k in sig["kinds"] if k not in named]
            because.append({"from": source, "signal": ",".join(sig["reasons"] + (["wide"] if sig["wide"] else [])
                                                               + [f"page:{k}" for k in sig["kinds"]]),
                            "words": sig["words"]})
    plans = [_PLANS[r] for r in reasons] or [_MINIMAL]
    depth = max((p["depth"] for p in plans), key=DEPTHS.index)
    home = [s for s in SHOTS if any(s in p["home"] for p in plans)]
    other = [s for s in SHOTS if any(s in p["other"] for p in plans)]
    kinds: list[str] = []
    for k in named:   # a page the person named comes first after the landing page
        if k not in kinds:
            kinds.append(k)
    for p in plans:
        for k in p["kinds"]:
            if k not in kinds:
                kinds.append(k)
    if wide:
        for k in (*_PLANS["design"]["kinds"], *_WIDE_KINDS):
            if k not in kinds:
                kinds.append(k)
    if named and depth == "capture":
        depth = "product"   # the person named a page: it is worth its own picture
        home = [s for s in SHOTS if s in ("viewport", "full")]
    kinds = kinds[:MAX_PAGES - 1]
    known = known if isinstance(known, dict) else {}
    pages = [{"kind": "saved", "shots": home}]
    for k in kinds:
        page = {"kind": k, "shots": other, "match": list(PAGE_KINDS.get(k, ()))}
        if isinstance(known.get(k), str) and known[k].startswith("http"):
            page["known"] = known[k]
        pages.append(page)
    texts_all = texts + [s for s in said or [] if isinstance(s, str)]
    plan = {"v": PLAN_V, "depth": depth, "max_pages": len(pages), "pace_seconds": PACE_SECONDS, "pages": pages,
            "avoid": list(AVOID), "because": because or [{"from": "default", "signal": "minimal"}]}
    if any(p.get("auto_look") for p in plans):
        plan["auto_look"] = True
    if asked == "look":
        plan["save_look"] = True
    if any(p.get("lift") for p in plans):
        plan["lift"] = True
    if any(p.get("section") for p in plans):
        plan["section"] = True
        plan["focus"] = focus_terms(texts_all)
    if walled:
        plan["avoid_urls"] = [u for u in walled if isinstance(u, str)][:50]
    return plan


def plan_for_depth(depth: str | None) -> dict:
    """The plan a bare depth word implies (a slice-1 row, or a script called without a plan)."""
    reason = {"look": "design", "product": "product", "read": "technique"}.get(str(depth or ""))
    return plan_for({"reasons": [reason]} if reason else None)


def for_site(memory_path: Path, site, asked: str | None = None) -> dict:
    """The plan for a :class:`explore_candidates.SavedSite`: its why, the ``## Saved because`` words on its episode,
    what the person said about it in conversations, what the site map already knows about the site, and the queue
    row's one ask (``asked``)."""
    from api.services import media_ingestor, site_map

    entry = media_ingestor.load_url_index(memory_path).get(site.key) or {}
    because = saved_because(memory_path, str(entry.get("episode_id") or "") or None)
    smap = site_map.read(memory_path, site.site)
    return plan_for(site.why, words=[because] if because else None,
                    said=said_in_conversations(memory_path, site.entity_id),
                    known=site_map.known_by_kind(smap), walled=site_map.walled_urls(smap), asked=asked)


def depth_of(why: dict | None) -> str:
    """The depth word for the queue and the estimate (no conversation read, no bank read)."""
    return plan_for(why)["depth"]


# --------------------------------------------------------------------------- page kinds, URLs, robots, pace


def _segments(url: str) -> list[str]:
    try:
        path = urlsplit(url).path or "/"
    except ValueError:
        return []
    return [s for s in re.split(r"[/_.]+", path.lower()) if s]


def page_kind(url: str, label: str | None = None) -> str:
    """``home``, one of :data:`PAGE_KINDS`, ``account`` (never opened) or ``other`` — by path first, then label."""
    segs = _segments(url)
    if not segs:
        return "home"
    joined = "/".join(segs)
    for word in AVOID:
        if word in segs or joined.startswith(word):
            return "account"
    for kind, words in PAGE_KINDS.items():
        if any(s == w or s.startswith(w + "-") for s in segs for w in words):
            return kind
    lab = " ".join(str(label or "").lower().split())
    if lab:
        if any(re.search(rf"\b{re.escape(w)}\b", lab) for w in AVOID):
            return "account"
        for kind, rx in _KIND_RES.items():
            if rx.search(lab):
                return kind
    return "other"


def clean_page_url(url: str | None) -> str | None:
    """An ``http(s)`` page URL as the site map keeps it: no credentials, no query, no fragment."""
    raw = str(url or "").strip()
    if not raw or len(raw) > 2000:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return None
    host = parts.hostname.lower() + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, host, parts.path or "/", "", ""))


def host_of(url: str | None) -> str:
    try:
        host = (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def robots(status, text: str | None) -> robotparser.RobotFileParser | None:
    """robots.txt as the agent's browser read it, parsed by the standard library (the capture script parses it the
    same way, so the two sides cannot disagree). ``None`` when it was not read: no second page is opened then.
    A 401/403 or a 5xx disallows everything; any other 4xx allows everything (the usual reading)."""
    try:
        code = int(status) if status is not None else None
    except (TypeError, ValueError):
        code = None
    if code is None:
        return None
    parser = robotparser.RobotFileParser()
    if code in (401, 403) or code >= 500:
        parser.disallow_all = True
    elif code >= 400:
        parser.allow_all = True
    else:
        parser.parse(str(text or "").splitlines()[:2000])
    return parser


def allowed(parser: robotparser.RobotFileParser | None, url: str) -> bool:
    if parser is None:
        return False
    try:
        return bool(parser.can_fetch("*", url))
    except Exception:  # noqa: BLE001 — an unparseable rule is a no
        return False


def _when(value):
    from datetime import datetime, timezone

    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


#: A page's load time must fall inside its lease window, with this slack (the agent's clock against the server's).
CLOCK_SLACK_S = 120


def vet(pages, *, plan: dict, landing_url: str, landing_loaded_at=None, robots_parser=None, window_start=None,
        now=None) -> tuple[list[dict], dict[str, int]]:
    """The further pages a record may keep, checked against the plan — the backend's half of the split. A page is
    dropped when it is off the landing page's host, a sign-in or account page, one an earlier visit found walled,
    disallowed by robots.txt as the agent's browser read it (no robots.txt read: no further page at all), loaded
    outside the lease window, loaded sooner than :data:`PACE_SECONDS` after the page before it, or past the plan's cap.
    Returns ``(kept, {reason: count})``; ``kept`` carry the clean URL and a known kind."""
    from datetime import datetime, timedelta, timezone

    now = now or datetime.now(timezone.utc)
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    landing = clean_page_url(landing_url)
    host = host_of(landing_url)
    cap = max(0, int((plan or {}).get("max_pages") or 1) - 1)
    walled = {clean_page_url(u) for u in (plan or {}).get("avoid_urls") or []}
    start = (window_start or now - timedelta(hours=1)) - timedelta(seconds=CLOCK_SLACK_S)
    end = now + timedelta(seconds=CLOCK_SLACK_S)
    items = []
    for raw in list(pages or [])[:MAX_PAGES * 3]:
        if not isinstance(raw, dict):
            continue
        when = _when(raw.get("loaded_at"))
        if when is None or not start <= when <= end:
            drop("time")
            continue
        items.append((when, raw))
    items.sort(key=lambda pair: pair[0])
    last = _when(landing_loaded_at)
    seen = {landing}
    kept: list[dict] = []
    for when, raw in items:
        previous, last = last, when   # a page that was loaded paces the next one, kept or not
        url = clean_page_url(raw.get("url"))
        if url is None:
            drop("url")
            continue
        if host_of(url) != host:
            drop("host")
            continue
        if url in seen:
            drop("repeat")
            continue
        seen.add(url)
        kind = str(raw.get("kind") or "")
        found_kind = page_kind(url, raw.get("label"))
        if found_kind == "account":
            drop("account")
            continue
        if url in walled:
            drop("walled")
            continue
        if not allowed(robots_parser, url):
            drop("robots")
            continue
        if previous is not None and (when - previous).total_seconds() < PACE_SECONDS:
            drop("pace")
            continue
        if len(kept) >= cap:
            drop("cap")
            continue
        kept.append({**raw, "url": url, "kind": kind if kind in PAGE_KINDS else found_kind,
                     "loaded_at": when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")})
    return kept, dropped


def capped(plan: dict, pages_allowed: int) -> dict:
    """``plan`` cut to ``pages_allowed`` pages (the hour's room on this site, ``explore_queue.room``)."""
    n = max(1, min(int(pages_allowed), int(plan.get("max_pages") or 1)))
    if n >= int(plan.get("max_pages") or 1):
        return plan
    return {**plan, "pages": list(plan.get("pages") or [])[:n], "max_pages": n, "capped_by": "hour"}
