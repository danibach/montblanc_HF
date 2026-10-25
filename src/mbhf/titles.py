"""The title of an outing: the take-off's name alone, decided by Sarah on 25 October 2026 (« {take-off} from {start} »
was tried the same day and dropped for now).

* the main name is the take-off of the register (FFVL, OpenStreetMap or provisional: as pilots call it), else the
  mapped take-off or the summit reached on foot; a village alone is never the main name;
* the name is cleaned (``clean_name``): no opening dates (« ouvert du 1/5 au 31/10 »), no season in brackets
  (« (ete) »), no quotes, one language for a bilingual name (« Mont Blanc / Monte Bianco » -> « Mont Blanc »),
  capitals the French way and a few lost accents put back (« cret » -> « Crêt »);
* the same cleaning is used for the names of the register (FFVL, OpenStreetMap), so the map says what the titles say.

Before this, the titles mixed the take-off, the summit and the village, raw FFVL names included
(« La clusaz - aiguille des calvaires (ete) »), and ten outings were all « Pointe de Beauregard ».
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

_SMALL = {"de", "des", "du", "la", "le", "les", "et", "sur", "sous", "en", "au", "aux", "d", "l", "à", "a"}
# FFVL names lost their accents; the most common words get them back
_ACCENTS = {"cret": "crêt", "tete": "tête", "pre": "pré", "pres": "prés", "chatel": "châtel", "chateau": "château",
            "foret": "forêt", "teton": "téton", "fretes": "frêtes", "saleve": "salève", "riviere": "rivière"}
# « Décollage du Col des Frêtes », « Décollage FFVL de Planpraz »: the word take-off says nothing in a title
_TAKEOFF_WORD = re.compile(r"^(?:d[ée]collage|d[ée]co|take-?off|startplatz)\b(?:\s+parapente)?(?:\s+ffvl)?"
                           r"(?:\s+(?:du|de\s+la|des|de\s+l'|de|d'))?\s*(?=\S)", re.I)
# a bracket that holds a season, an opening period or dates: « (ete) », « (Ete 1er Mai au 31 Octobre) »
_NOTE = re.compile(r"\s*\((?=[^)]*(?:\bet[ée]\b|hiver|winter|summer|ouvert|\d))[^)]*\)", re.I)


def _key(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _capitals(name: str) -> str:
    """Capitals the French way: a word in small letters gets its capital, except the small words inside the name
    (« Col de la Forclaz »); a word in capitals is lowered first; a few lost accents are put back."""
    shout = name == name.upper()
    parts = re.split(r"([\s\-'’/]+)", name)
    out = []
    for i, w in enumerate(parts):
        if not w or not w[0].isalpha():
            out.append(w)
            continue
        word = w.lower() if shout else w
        low = word.lower()
        word = _ACCENTS[low] if low in _ACCENTS else word
        if i > 0 and low in _SMALL:  # « Col de la Forclaz », « Crêt-du-Merle »
            out.append(low)
        else:
            out.append(word[0].upper() + word[1:])
    return "".join(out)


def clean_name(name: Optional[str], places: tuple = ()) -> Optional[str]:
    """A take-off or summit name fit for a title, or None when nothing is left. ``places``: the commune and the start
    of the outing; an FFVL « COMMUNE - SITE » loses the part that only names one of them."""
    s = re.sub(r"\s+", " ", (name or "").strip())
    if not s:
        return None
    s = re.sub(r"\s*[-–,]?\s*\(?\s*ouvert\b[^)]*\)?\s*$", "", s, flags=re.I)        # « - ouvert du 1/5 au 31/10 »
    s = _NOTE.sub("", s)                                                              # « (ete) », « (Ete 1er Mai …) »
    s = s.replace('"', "").replace("«", "").replace("»", "").replace("“", "").replace("”", "")
    if " / " in s:                                                                     # « Mont Blanc / Monte Bianco »
        s = s.split(" / ")[0]
    s = _TAKEOFF_WORD.sub("", s)
    parts = [p.strip() for p in re.split(r"\s+[-–]\s+", s) if p.strip()]
    keys = [_key(p) for p in places if p]
    kept = [p for p in parts if not any(_key(p) and (_key(p) == k or _key(p) in k.split() or _key(p) in k) for k in keys)]
    s = " – ".join(kept or parts)
    s = re.sub(r"\s+", " ", s).strip(" -–,")
    if not s:
        return None
    s = _capitals(s)
    return s[0].upper() + s[1:]


def outing_title(main: Optional[str], start_place: Optional[str], commune: Optional[str] = None) -> Optional[str]:
    """The take-off's name alone, cleaned (Sarah, 25 October 2026: « juste le nom du déco pour l'instant »); the start
    and commune are only used to drop a village prefix (« La Clusaz - Crêt du Loup » -> « Crêt du Loup »). None when
    there is no main name."""
    return clean_name(main, (commune, start_place)) or None
