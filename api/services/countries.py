"""Country names, English and Spanish, folded to one canonical key — a closed table for ``org_sites``' context check.

Only what is needed to say "the page names Spain, the Wikidata item is in the United States": whole-word matches of a
country's common names. Ambiguous words that are also ordinary words or US states ("Georgia", "Jordan", "Chad",
"Niger", "Turkey", "China" as porcelain) are left out or kept only in an unambiguous spelling, so a page that names
none of these reads as naming no country — which is never a conflict.
"""
from __future__ import annotations

import re

from api.services import text_fold

#: canonical -> spellings (folded on load). English first, then Spanish where it differs.
_TABLE: dict[str, tuple[str, ...]] = {
    "afghanistan": ("afghanistan", "afganistan"),
    "albania": ("albania",),
    "algeria": ("algeria", "argelia"),
    "andorra": ("andorra",),
    "angola": ("angola",),
    "argentina": ("argentina",),
    "armenia": ("armenia",),
    "australia": ("australia",),
    "austria": ("austria",),
    "azerbaijan": ("azerbaijan", "azerbaiyan"),
    "bahrain": ("bahrain", "barein"),
    "bangladesh": ("bangladesh",),
    "belarus": ("belarus", "bielorrusia"),
    "belgium": ("belgium", "belgica"),
    "bolivia": ("bolivia",),
    "bosnia": ("bosnia and herzegovina", "bosnia y herzegovina"),
    "brazil": ("brazil", "brasil"),
    "bulgaria": ("bulgaria",),
    "cambodia": ("cambodia", "camboya"),
    "cameroon": ("cameroon", "camerun"),
    "canada": ("canada",),
    "chile": ("chile",),
    "china": ("people's republic of china", "republica popular china", "mainland china"),
    "colombia": ("colombia",),
    "costa rica": ("costa rica",),
    "croatia": ("croatia", "croacia"),
    "cuba": ("cuba",),
    "cyprus": ("cyprus", "chipre"),
    "czechia": ("czech republic", "czechia", "republica checa", "chequia"),
    "denmark": ("denmark", "dinamarca"),
    "dominican republic": ("dominican republic", "republica dominicana"),
    "ecuador": ("ecuador",),
    "egypt": ("egypt", "egipto"),
    "el salvador": ("el salvador",),
    "estonia": ("estonia",),
    "ethiopia": ("ethiopia", "etiopia"),
    "finland": ("finland", "finlandia"),
    "france": ("france", "francia"),
    "germany": ("germany", "alemania", "deutschland"),
    "ghana": ("ghana",),
    "greece": ("greece", "grecia"),
    "guatemala": ("guatemala",),
    "honduras": ("honduras",),
    "hong kong": ("hong kong",),
    "hungary": ("hungary", "hungria"),
    "iceland": ("iceland", "islandia"),
    "india": ("india",),
    "indonesia": ("indonesia",),
    "iran": ("iran",),
    "iraq": ("iraq", "irak"),
    "ireland": ("ireland", "irlanda"),
    "israel": ("israel",),
    "italy": ("italy", "italia"),
    "japan": ("japan", "japon"),
    "kazakhstan": ("kazakhstan", "kazajistan"),
    "kenya": ("kenya",),
    "kuwait": ("kuwait",),
    "latvia": ("latvia", "letonia"),
    "lebanon": ("lebanon", "libano"),
    "lithuania": ("lithuania", "lituania"),
    "luxembourg": ("luxembourg", "luxemburgo"),
    "malaysia": ("malaysia", "malasia"),
    "malta": ("malta",),
    "mexico": ("mexico",),
    "moldova": ("moldova", "moldavia"),
    "monaco": ("monaco",),
    "morocco": ("morocco", "marruecos"),
    "nepal": ("nepal",),
    "netherlands": ("netherlands", "the netherlands", "holland", "paises bajos", "holanda"),
    "new zealand": ("new zealand", "nueva zelanda"),
    "nicaragua": ("nicaragua",),
    "nigeria": ("nigeria",),
    "north korea": ("north korea", "corea del norte"),
    "norway": ("norway", "noruega"),
    "oman": ("oman",),
    "pakistan": ("pakistan",),
    "panama": ("panama",),
    "paraguay": ("paraguay",),
    "peru": ("peru",),
    "philippines": ("philippines", "filipinas"),
    "poland": ("poland", "polonia"),
    "portugal": ("portugal",),
    "puerto rico": ("puerto rico",),
    "qatar": ("qatar", "catar"),
    "romania": ("romania", "rumania"),
    "russia": ("russia", "rusia", "russian federation"),
    "saudi arabia": ("saudi arabia", "arabia saudita", "arabia saudi"),
    "serbia": ("serbia",),
    "singapore": ("singapore", "singapur"),
    "slovakia": ("slovakia", "eslovaquia"),
    "slovenia": ("slovenia", "eslovenia"),
    "south africa": ("south africa", "sudafrica"),
    "south korea": ("south korea", "corea del sur", "republic of korea"),
    "spain": ("spain", "espana"),
    "sri lanka": ("sri lanka",),
    "sweden": ("sweden", "suecia"),
    "switzerland": ("switzerland", "suiza"),
    "taiwan": ("taiwan",),
    "thailand": ("thailand", "tailandia"),
    "tunisia": ("tunisia", "tunez"),
    "turkey": ("turkiye", "turquia", "republic of turkey"),
    "ukraine": ("ukraine", "ucrania"),
    "united arab emirates": ("united arab emirates", "emiratos arabes unidos", "uae"),
    "united kingdom": ("united kingdom", "great britain", "britain", "england", "scotland", "wales", "reino unido",
                       "inglaterra", "escocia", "uk"),
    "united states": ("united states", "united states of america", "estados unidos", "usa", "u.s.", "u.s.a."),
    "uruguay": ("uruguay",),
    "uzbekistan": ("uzbekistan", "uzbekistan"),
    "venezuela": ("venezuela",),
    "vietnam": ("vietnam", "viet nam"),
}

_INDEX: dict[str, str] = {}
for _canon, _spellings in _TABLE.items():
    for _s in _spellings:
        _INDEX[text_fold.fold(_s)] = _canon
_PATTERN = re.compile(r"(?<![\w.])(" + "|".join(sorted((re.escape(k) for k in _INDEX), key=len, reverse=True))
                      + r")(?![\w])")


def canonical_countries(text: str) -> set[str]:
    """The canonical keys of every country ``text`` names, whole-word, case- and accent-insensitive."""
    folded = text_fold.fold(text or "")
    return {_INDEX[m.group(1)] for m in _PATTERN.finditer(folded)}
