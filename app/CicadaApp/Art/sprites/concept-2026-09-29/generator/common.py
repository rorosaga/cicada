import html as _h

ASSET = {
    "heroDay": "/_blob/38a8fb1a35ee6a10a984780a9e9bc9e1", "heroNight": "/_blob/6bedd64547a9570331ae4fb9900689f5",
    "claude": "/_blob/63b5b6405c2851709b189be573b69775", "chatgptDark": "/_blob/9104d79fe74d48383ac19ca1b3ea5278",
    "codexDark": "/_blob/6b0b3977422a11ff088eba319cdca8e6", "chrome": "/_blob/82ca1941186da467c0d5cb813db6d0e6",
    "youtube": "/_blob/f4140689d53a807bfc1ef28970b149e0", "linkedin": "/_blob/d3450e2331f105c87ccb0ad5498ef0e5",
    "xDark": "/_blob/47d1694ce6f7200a819ed94d7fb3785c", "reddit": "/_blob/5f076d837533d2a32df032db2154ce36",
    "brave": "/_blob/19d2b0ea48f6438df297ddbf779157f3",
}
NAMES = {"claude": "Claude Code", "chatgptDark": "ChatGPT", "codexDark": "Codex", "chrome": "Chrome", "youtube": "YouTube",
         "linkedin": "LinkedIn", "xDark": "X", "reddit": "Reddit", "brave": "Brave"}

FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Text',system-ui,sans-serif"
DISPLAY = "'SF Pro Display',-apple-system,BlinkMacSystemFont,system-ui,sans-serif"

BASE_CSS = f"""body{{margin:0;background:#141416;font-family:{FONT};color:#f2f2f4;-webkit-font-smoothing:antialiased}}
button{{font-family:{FONT}}}
a{{color:#5ea9ff;text-decoration:none}}
.btnp{{display:inline-flex;align-items:center;gap:8px;height:34px;padding:0 18px;border:0;border-radius:9px;background:#0066cc;color:#ffffff;font:600 14px {FONT}}}
.btnn{{display:inline-flex;align-items:center;gap:8px;height:30px;padding:0 12px;border-radius:8px;border:1px solid rgba(255,255,255,.09);background:#26262b;color:#f2f2f4;font:500 13px {FONT}}}
.btns{{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 9px;border-radius:6px;border:1px solid rgba(255,255,255,.09);background:#26262b;color:#f2f2f4;font:500 12px {FONT}}}
.btnt{{border:0;background:none;padding:0;color:#5ea9ff;font:500 13px {FONT}}}
.lbl{{font-size:11px;font-weight:500;color:#9a9aa3}}
.cap{{font-size:12px;color:#9a9aa3}}
.sec{{font-size:11px;font-weight:500;color:#9a9aa3}}
.tag{{display:inline-flex;align-items:center;gap:5px;height:20px;padding:0 7px;border-radius:5px;background:#2c2c32;color:#d6d6dc;font:500 11px {FONT}}}
.card{{background:#1f1f23;border-radius:14px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.07)}}
.tile{{background:#1b1b20;border-radius:10px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.06)}}
.sentence{{font:600 30px {DISPLAY};letter-spacing:-0.4px;color:#f2f2f4}}
.tail{{font-size:18px;font-style:italic;color:#b4b4bb}}
.px{{image-rendering:pixelated}}
"""


def esc(s):
    return _h.escape(str(s), quote=True)


def page(title, w, h, css, body, bg='#141416', extra_root=''):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{esc(title)}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
<style>
{BASE_CSS}{css}
</style>
</helmet>
<div style="width: {w}px; height: {h}px; box-sizing: border-box; overflow: hidden; position: relative; background: {bg}; {extra_root}">
{body}
</div>
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{{"$preview":{{"width":{w},"height":{h}}}}}'>
class Component extends DCLogic {{
renderVals() {{ return {{}}; }}
}}
</script>
</body>
</html>
"""


def mark(key, size=14, extra=''):
    return f'<img src="{ASSET[key]}" alt="{esc(NAMES.get(key, key))}" width="{size}" height="{size}" style="display: block; flex: none; {extra}">'


P = 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
ICON = {
    'home': '<path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z"></path>',
    'graph': '<circle cx="6" cy="6" r="2.5"></circle><circle cx="18" cy="8" r="2.5"></circle><circle cx="10" cy="18" r="2.5"></circle><path d="M8.3 7l7.4.8M7 8.3l2.2 7.4M16.4 10l-4.6 6"></path>',
    'clusters': '<rect x="4" y="4" width="7" height="7" rx="1.5"></rect><rect x="13" y="4" width="7" height="7" rx="1.5"></rect><rect x="4" y="13" width="7" height="7" rx="1.5"></rect><rect x="13" y="13" width="7" height="7" rx="1.5"></rect>',
    'feed': '<path d="M5 6h14M5 12h14M5 18h9"></path>',
    'moon': '<path d="M20 13.5A8 8 0 1 1 10.5 4a6.3 6.3 0 0 0 9.5 9.5z"></path>',
    'inbox': '<path d="M4 13l2.5-8h11L20 13v6H4z"></path><path d="M4 13h5l1 2h4l1-2h5"></path>',
    'sources': '<circle cx="12" cy="12" r="2"></circle><path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14"></path>',
    'projects': '<path d="M5 20V4M5 5h11l-2 4 2 4H5"></path>',
    'gear': '<circle cx="12" cy="12" r="3"></circle><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"></path>',
    'sun': '<circle cx="12" cy="12" r="4"></circle><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"></path>',
    'search': '<circle cx="11" cy="11" r="6"></circle><path d="M20 20l-4.5-4.5"></path>',
    'chev': '<path d="M9 6l6 6-6 6"></path>', 'chevd': '<path d="M6 9l6 6 6-6"></path>', 'chevl': '<path d="M15 6l-6 6 6 6"></path>',
    'check': '<path d="M5 12.5l4.5 4.5L19 7.5"></path>',
    'lock': '<rect x="5" y="11" width="14" height="9" rx="2"></rect><path d="M8 11V8a4 4 0 0 1 8 0v3"></path>',
    'warn': '<path d="M12 4l9 16H3z"></path><path d="M12 10v4M12 17.2v.1"></path>',
    'circle': '<circle cx="12" cy="12" r="7"></circle>',
    'half': '<circle cx="12" cy="12" r="7"></circle><path d="M12 5a7 7 0 0 1 0 14z" fill="currentColor"></path>',
    'dot': '<circle cx="12" cy="12" r="7"></circle><circle cx="12" cy="12" r="3" fill="currentColor"></circle>',
    'chat': '<path d="M5 5h14v10H10l-4 4v-4H5z"></path>',
    'page': '<path d="M7 3h7l4 4v14H7z"></path><path d="M14 3v4h4M10 12h5M10 16h5"></path>',
    'note': '<rect x="5" y="4" width="14" height="17" rx="2"></rect><path d="M9 2.5v3M15 2.5v3M9 11h6M9 15h4"></path>',
    'video': '<rect x="3" y="6" width="13" height="12" rx="2"></rect><path d="M16 10.5l5-3v9l-5-3z"></path>',
    'pause': '<path d="M9 5v14M15 5v14"></path>',
    'filter': '<path d="M4 6h16M7 12h10M10 18h4"></path>',
    'agent': '<rect x="5" y="8" width="14" height="11" rx="3"></rect><path d="M12 4v4M9 13v1M15 13v1"></path>',
    'retry': '<path d="M4 12a8 8 0 1 0 2.3-5.6"></path><path d="M4 4v4h4"></path>',
    'ext': '<path d="M14 4h6v6M20 4l-9 9"></path><path d="M18 14v5H5V6h5"></path>',
    'up': '<path d="M12 19V5M6 11l6-6 6 6"></path>',
    'skip': '<path d="M6 6l12 12M18 6L6 18"></path>',
    'sidebar': '<rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="M9 5v14"></path>',
    'shelf': '<path d="M4 20h16M4 4h16M6 20V9M9 20V7M12 20v-9M16 20V8M19 20v-6"></path>',
    'more': '<circle cx="6" cy="12" r="1"></circle><circle cx="12" cy="12" r="1"></circle><circle cx="18" cy="12" r="1"></circle>',
}


def icon(name, size=14, color='currentColor', sw=None):
    p = P if sw is None else P.replace('stroke-width="1.8"', f'stroke-width="{sw}"')
    return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" {p} style="color: {color}; flex: none" aria-hidden="true">{ICON[name]}</svg>'


def room_block(g, plates, pal, px=4, radius=10):
    svg = g.svg(px, pal, 'style="display: block"')
    ov = []
    for (x, y, w, h, mk, count) in plates:
        size = 12 if h * px >= 14 else 10
        ov.append(f'<div style="position: absolute; left: {x*px}px; top: {y*px}px; width: {w*px}px; height: {h*px}px; display: flex; align-items: center; justify-content: center; gap: 3px">'
                  + (icon(mk[5:], size, '#F5EBD3') if mk.startswith('icon:') else mark(mk, size)) + (f'<span style="font: 600 10px {FONT}; color: #F5EBD3; letter-spacing: 0">{esc(count)}</span>' if count else '') + '</div>')
    return (f'<div style="position: relative; width: {g.w*px}px; height: {g.h*px}px; border-radius: {radius}px; overflow: hidden; flex: none">'
            f'{svg}{"".join(ov)}</div>')
