"""Shared HTML for the v3 boards: theme tokens (Direction D), controls, icons, the room card."""
import html as _h
from px import G

ASSET = {
    "claude": "/_blob/63b5b6405c2851709b189be573b69775", "chatgptDark": "/_blob/9104d79fe74d48383ac19ca1b3ea5278",
    "codexDark": "/_blob/6b0b3977422a11ff088eba319cdca8e6", "chrome": "/_blob/82ca1941186da467c0d5cb813db6d0e6",
    "youtube": "/_blob/f4140689d53a807bfc1ef28970b149e0", "linkedin": "/_blob/d3450e2331f105c87ccb0ad5498ef0e5",
    "xDark": "/_blob/47d1694ce6f7200a819ed94d7fb3785c", "reddit": "/_blob/5f076d837533d2a32df032db2154ce36",
    "brave": "/_blob/19d2b0ea48f6438df297ddbf779157f3",
}
NAMES = {"claude": "Claude Code", "chatgptDark": "ChatGPT", "codexDark": "Codex", "chrome": "Chrome", "youtube": "YouTube",
         "linkedin": "LinkedIn", "xDark": "X", "reddit": "Reddit", "brave": "Brave"}
MONO = {"chatgptDark", "codexDark", "xDark"}
FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Text',system-ui,sans-serif"
DISPLAY = "'SF Pro Display',-apple-system,BlinkMacSystemFont,system-ui,sans-serif"

CSS = f"""body{{margin:0;background:#0b0b0c;-webkit-font-smoothing:antialiased;font-family:{FONT}}}
.t-dark{{--rail:#0C0D0E;--base:#111213;--pane:#141517;--hover:#1B1C1E;--focus:#18191B;--option:#1D1E21;--button:#232427;--selected:#222326;--menu:#1B1C1E;--key:#26272A;--badge:#3A3B3F;--t1:#F5F5F6;--t2:#D0D1D4;--t3:#8D8F94;--t4:#6A6C71;--accentText:#0A84FF;--primary:#0A84FF;--ring:rgba(255,255,255,.07);--ringStrong:rgba(255,255,255,.12);--floatRing:rgba(255,255,255,.10);--floatShadow:0 0 0 0 transparent;--warning:#F59E0B;--markInvert:none;--focusRing:rgba(10,132,255,.9)}}
.t-light{{--rail:#EFEFEC;--base:#F7F7F5;--pane:#FBFBFA;--hover:#EFEFEC;--focus:#FFFFFF;--option:#F7F7F5;--button:#F2F2F0;--selected:#E8E8E5;--menu:#FFFFFF;--key:#EAEAE7;--badge:#D9D9D6;--t1:#141415;--t2:#38393C;--t3:#6A6B70;--t4:#8A8B90;--accentText:#0062CC;--primary:#007AFF;--ring:rgba(0,0,0,.07);--ringStrong:rgba(0,0,0,.12);--floatRing:rgba(0,0,0,.08);--floatShadow:0 12px 32px rgba(0,0,0,.14);--warning:#B45309;--markInvert:invert(1);--focusRing:rgba(0,122,255,.9)}}
.surf{{background:var(--base);color:var(--t1);font-family:{FONT};font-size:13px;line-height:1.35}}
.surf *{{box-sizing:border-box}}
.card{{background:var(--focus);border-radius:14px;box-shadow:inset 0 0 0 1px var(--ring)}}
.tile{{background:var(--focus);border-radius:10px;box-shadow:inset 0 0 0 1px var(--ring)}}
.btnp{{display:inline-flex;align-items:center;gap:8px;height:34px;padding:0 18px;border:0;border-radius:9px;background:var(--primary);color:#FFFFFF;font:600 14px {FONT}}}
.btnn{{display:inline-flex;align-items:center;gap:8px;height:34px;padding:0 12px;border:0;border-radius:8px;background:var(--button);box-shadow:inset 0 0 0 1px var(--ringStrong);color:var(--t1);font:500 13px {FONT}}}
.btns{{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 10px;border:0;border-radius:7px;background:var(--button);box-shadow:inset 0 0 0 1px var(--ringStrong);color:var(--t1);font:500 12px {FONT}}}
.btnq{{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 10px;border:0;border-radius:7px;background:transparent;color:var(--t2);font:500 12px {FONT}}}
.link{{border:0;background:none;padding:0;color:var(--accentText);font:500 13px {FONT};cursor:pointer}}
.tbtn{{display:inline-flex;align-items:center;gap:6px;border:0;background:none;padding:4px 6px;border-radius:6px;color:var(--t2);font:500 13px {FONT}}}
.lbl{{font-size:11px;font-weight:500;color:var(--t3)}}
.meta{{font-size:12px;color:var(--t3)}}
.body{{font-size:13px;color:var(--t2)}}
.sentence{{font:600 30px {DISPLAY};letter-spacing:-0.4px;color:var(--t1)}}
.tail{{font-size:18px;font-style:italic;color:var(--t2)}}
.whisper{{font-size:12px;color:var(--t3)}}
.plate{{position:absolute;display:flex;align-items:center;gap:3px;padding-left:4px;box-sizing:border-box;font:600 11px {FONT};color:#F5EBD3;letter-spacing:0;white-space:nowrap}}
.mk{{display:block;flex:none}}
.pop{{position:absolute;background:var(--menu);border-radius:12px;box-shadow:inset 0 0 0 1px var(--floatRing),var(--floatShadow);padding:14px 16px;display:flex;flex-direction:column;gap:10px}}
.row{{display:flex;align-items:center;gap:10px;height:36px;padding:0 10px;border-radius:8px;font-size:13px}}
.row .t{{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--t1)}}
.row .m{{font-size:12px;color:var(--t3);white-space:nowrap}}
.row .s{{font-size:12px;color:var(--t2);white-space:nowrap;text-align:right}}
.tabs{{display:flex;gap:4px;align-items:center}}
.tab{{border:0;background:none;padding:5px 9px;border-radius:7px;font:500 13px {FONT};color:var(--t3);white-space:nowrap}}
.tab[aria-selected="true"]{{background:var(--selected);color:var(--t1)}}
.menu{{white-space:nowrap;display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 10px;border:0;border-radius:7px;background:var(--button);box-shadow:inset 0 0 0 1px var(--ringStrong);font:500 12px {FONT};color:var(--t1)}}
.field{{height:28px;width:180px;border:0;border-radius:7px;background:var(--option);box-shadow:inset 0 0 0 1px var(--ringStrong);color:var(--t1);font:12px {FONT};padding:0 10px 0 28px}}
.field::placeholder{{color:var(--t3)}}
.kbd{{font:500 11px ui-monospace,Menlo,monospace;color:var(--t3);background:var(--key);border-radius:4px;padding:1px 5px}}
.px{{image-rendering:pixelated}}
.cap{{font-size:12px;color:var(--t3);text-align:center}}
"""


def esc(s):
    return _h.escape(str(s), quote=True)


def page(title, w, h, body, cls='t-dark surf', css=''):
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
{CSS}{css}
</style>
</helmet>
<div class="{cls}" style="width: {w}px; height: {h}px; overflow: hidden; position: relative;">
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


def mark(key, size=14, alt=None, extra=''):
    inv = 'filter: var(--markInvert);' if key in MONO else ''
    return (f'<img class="mk" src="{ASSET[key]}" alt="{esc(alt or NAMES.get(key, key))}" width="{size}" height="{size}" '
            f'style="{inv}{extra}">')


def plate_mark(key, size=12):
    """On a pixel plate the plate is always dark art, so a monochrome mark stays white."""
    return f'<img class="mk" src="{ASSET[key]}" alt="{esc(NAMES.get(key, key))}" width="{size}" height="{size}">'


ICON = {
    'home': '<path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z"></path>',
    'graph': '<circle cx="6" cy="6" r="2.5"></circle><circle cx="18" cy="8" r="2.5"></circle><circle cx="10" cy="18" r="2.5"></circle><path d="M8.3 7l7.4.8M7 8.3l2.2 7.4M16.4 10l-4.6 6"></path>',
    'clusters': '<rect x="4" y="4" width="7" height="7" rx="1.5"></rect><rect x="13" y="4" width="7" height="7" rx="1.5"></rect><rect x="4" y="13" width="7" height="7" rx="1.5"></rect><rect x="13" y="13" width="7" height="7" rx="1.5"></rect>',
    'feed': '<path d="M5 6h14M5 12h14M5 18h9"></path>',
    'moon': '<path d="M20 13.5A8 8 0 1 1 10.5 4a6.3 6.3 0 0 0 9.5 9.5z"></path>',
    'inbox': '<path d="M4 13l2.5-8h11L20 13v6H4z"></path><path d="M4 13h5l1 2h4l1-2h5"></path>',
    'sources': '<circle cx="12" cy="12" r="2"></circle><path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14"></path>',
    'projects': '<path d="M5 20V4M5 5h11l-2 4 2 4H5"></path>',
    'gear': '<circle cx="12" cy="12" r="3"></circle><path d="M12 2.8l1.4 2.4 2.7-.6.6 2.7 2.4 1.4-1.2 2.5 1.2 2.5-2.4 1.4-.6 2.7-2.7-.6L12 21.2l-1.4-2.4-2.7.6-.6-2.7-2.4-1.4L6.1 12 4.9 9.5l2.4-1.4.6-2.7 2.7.6z"></path>',
    'sunmoon': '<path d="M12 3a9 9 0 1 0 0 18z" fill="currentColor"></path><circle cx="12" cy="12" r="9"></circle>',
    'search': '<circle cx="11" cy="11" r="6"></circle><path d="M20 20l-4.5-4.5"></path>',
    'chev': '<path d="M9 6l6 6-6 6"></path>', 'chevd': '<path d="M6 9l6 6 6-6"></path>', 'chevl': '<path d="M15 6l-6 6 6 6"></path>',
    'check': '<path d="M5 12.5l4.5 4.5L19 7.5"></path>',
    'lock': '<rect x="5" y="11" width="14" height="9" rx="2"></rect><path d="M8 11V8a4 4 0 0 1 8 0v3"></path>',
    'warn': '<path d="M12 4l9 16H3z"></path><path d="M12 10v4M12 17.2v.1"></path>',
    'dot': '<circle cx="12" cy="12" r="3.2" fill="currentColor" stroke="none"></circle>',
    'ring': '<circle cx="12" cy="12" r="6.5"></circle>',
    'half': '<circle cx="12" cy="12" r="7"></circle><path d="M12 5a7 7 0 0 1 0 14z" fill="currentColor"></path>',
    'openbook': '<path d="M3 6.5c3-1.3 6-1.3 9 .5 3-1.8 6-1.8 9-.5V19c-3-1.3-6-1.3-9 .5-3-1.8-6-1.8-9-.5z"></path><path d="M12 7v12.5"></path>',
    'note': '<rect x="5" y="4" width="14" height="17" rx="2"></rect><path d="M9 2.5v3M15 2.5v3M9 11h6M9 15h4"></path>',
    'video': '<rect x="3" y="6" width="13" height="12" rx="2"></rect><path d="M16 10.5l5-3v9l-5-3z"></path>',
    'chat': '<path d="M5 5h14v10H10l-4 4v-4H5z"></path>',
    'page': '<path d="M7 3h7l4 4v14H7z"></path><path d="M14 3v4h4M10 12h5M10 16h5"></path>',
    'more': '<rect x="4" y="6" width="16" height="4" rx="1"></rect><rect x="5" y="11" width="14" height="3.5" rx="1"></rect><rect x="4" y="15.5" width="16" height="3.5" rx="1"></rect>',
    'pause': '<path d="M9 5v14M15 5v14"></path>',
    'play': '<path d="M8 5l11 7-11 7z"></path>',
    'filter': '<path d="M4 6h16M7 12h10M10 18h4"></path>',
    'agent': '<rect x="5" y="8" width="14" height="11" rx="3"></rect><path d="M12 4v4M9 13v1M15 13v1"></path>',
    'retry': '<path d="M4 12a8 8 0 1 0 2.3-5.6"></path><path d="M4 4v4h4"></path>',
    'ext': '<path d="M14 4h6v6M20 4l-9 9"></path><path d="M18 14v5H5V6h5"></path>',
    'x': '<path d="M6 6l12 12M18 6L6 18"></path>',
    'sidebar': '<rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="M9 5v14"></path>',
    'shelf': '<path d="M4 4v16M20 4v16M4 20h16M4 11.5h16"></path><path d="M7 11V6M9.5 11V7M12 11V5.5M7 19.5v-5M10 19.5v-4"></path>',
    'cart': '<path d="M4 9h16M4 15h16M5 9v6M19 9v6"></path><circle cx="7" cy="18.5" r="1.5"></circle><circle cx="17" cy="18.5" r="1.5"></circle><path d="M7 7h9"></path>',
    'crate': '<rect x="4" y="9" width="16" height="11" rx="1"></rect><path d="M4 13h16M4 16.5h16M8 9v11M16 9v11"></path><path d="M8 7h8"></path>',
    'stack': '<rect x="4" y="15" width="16" height="4" rx="1"></rect><rect x="5" y="10.5" width="14" height="4" rx="1"></rect><rect x="4" y="6" width="15" height="4" rx="1"></rect>',
    'plus': '<path d="M12 5v14M5 12h14"></path>',
    'send': '<path d="M5 12h14M13 6l6 6-6 6"></path>',
}
P = 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'


def icon(name, size=14, color='currentColor', label=None):
    aria = f'role="img" aria-label="{esc(label)}"' if label else 'aria-hidden="true"'
    return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" {P} style="color: {color}; flex: none" {aria}>{ICON[name]}</svg>'


BLOCK = 'style="display: block"'


def pixel_block(g, pal, px=4, plates=(), radius=10, extra_style='', label=None):
    """A room (or prop) as crisp SVG with snapped HTML plates on top."""
    ov = []
    for (x, y, w, h, key, count) in plates:
        if key.startswith('icon:'):
            mk = icon(key[5:], 12, '#F5EBD3')
        else:
            mk = plate_mark(key, 12)
        ov.append(f'<div class="plate" style="left: {x * px}px; top: {y * px}px; width: {w * px}px; height: {h * px}px">{mk}<span>{esc(f"{count:,}" if isinstance(count, int) else count)}</span></div>')
    aria = f'role="img" aria-label="{esc(label)}"' if label else ''
    return (f'<div {aria} style="position: relative; width: {g.w * px}px; height: {g.h * px}px; border-radius: {radius}px; overflow: hidden; flex: none; {extra_style}">'
            f'{g.svg(px, pal, BLOCK)}{"".join(ov)}</div>')


def button_primary(label, ic=None):
    return f'<button class="btnp" type="button">{icon(ic, 14, "#FFFFFF") if ic else ""}{esc(label)}</button>'


def engine_menu(label='Claude plan · Sonnet', key='claude', alt='Claude'):
    return f'<button class="btnn" type="button" aria-haspopup="menu">{mark(key, 14, alt=alt)}{esc(label)}{icon("chevd", 10)}</button>'


def details_button(open_=False):
    return (f'<button class="tbtn" type="button" aria-expanded="{"true" if open_ else "false"}">'
            f'{icon("chevd" if open_ else "chev", 11)}Details</button>')
