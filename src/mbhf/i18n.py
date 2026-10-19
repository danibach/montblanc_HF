"""French for everything a participant sees.

The analysis code writes its messages in English (command line, JSON, tests). At the boundary of
the web app, ``translate`` turns them into French. A message that no rule knows is returned
unchanged and ``tests/test_i18n.py`` fails on the known scenarios if one is missed, so a new
English message must come with its French rule here.
"""

from __future__ import annotations

import re
from datetime import datetime

LANGS = ("en", "fr")

ROLE = {
    "en": {
        "bike_out": "Ride out (bike)",
        "ascent": "Walk up",
        "flight": "Flight",
        "walk_after_landing": "Walk after landing",
        "bike_return": "Ride back (bike)",
    },
    "fr": {
        "bike_out": "Trajet aller à vélo",
        "ascent": "Montée à pied",
        "flight": "Vol",
        "walk_after_landing": "Marche après l'atterrissage",
        "bike_return": "Retour à vélo",
    },
}
ROLE_START = {
    "en": {
        "bike_out": "Start of the ride out",
        "ascent": "Start of the walk up",
        "flight": "Take-off",
        "walk_after_landing": "Landing",
        "bike_return": "Start of the ride back",
    },
    "fr": {
        "bike_out": "Début du trajet aller à vélo",
        "ascent": "Début de la montée à pied",
        "flight": "Décollage",
        "walk_after_landing": "Atterrissage",
        "bike_return": "Début du retour à vélo",
    },
}
# Short names of a part inside a sentence ("la partie « montée à pied »").
ROLE_SHORT_FR = {
    "bike_out": "trajet aller à vélo",
    "ascent": "montée à pied",
    "flight": "vol",
    "walk_after_landing": "marche après l'atterrissage",
    "bike_return": "retour à vélo",
}

LABEL_FR = {
    "Start of the track": "Début de la trace",
    "End of the track": "Fin de la trace",
    "Last exit from the Nid d'Aigle cylinder (clock starts)": "Dernière sortie du cylindre du Nid d'Aigle (le chrono démarre)",
    "First entry into the summit cylinder on foot (clock stops)": "Première entrée à pied dans le cylindre du sommet (le chrono s'arrête)",
    "Final exit from the summit cylinder": "Sortie finale du cylindre du sommet",
    "Nid d'Aigle": "Nid d'Aigle",
    "Mont-Blanc summit": "Sommet du Mont-Blanc",
    "Bike": "Vélo",
    "On foot": "À pied",
    "Flight": "Vol",
    "Start": "Début",
    "End": "Fin",
    "Nid d'Aigle exit": "Sortie du Nid d'Aigle",
    "Summit entry": "Entrée au sommet",
    "Altitude (m)": "Altitude (m)",
    "Ground speed (km/h)": "Vitesse sol (km/h)",
    "Longitude": "Longitude",
    "Latitude": "Latitude",
}
NEAR_FR = {"Nid d'Aigle": "au Nid d'Aigle", "Mont-Blanc summit": "au sommet du Mont-Blanc"}
NEAR_EN = {"Nid d'Aigle": "at Nid d'Aigle", "Mont-Blanc summit": "at the Mont-Blanc summit"}

VERDICT_FR = {
    "tram": "tramway",
    "lift": "remontée mécanique",
    "review": "à examiner",
    "on_foot": "à pied",
    "clear": "rien à signaler",
    "not_checked": "non vérifié",
}
KIND_FR = {"tram": "tramway", "lift": "remontée mécanique"}
CONFIDENCE_FR = {"high": "confiance élevée", "medium": "confiance moyenne", "low": "confiance faible", "n/a": "non évaluée"}

_DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
_MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def tr(lang: str, text: str) -> str:
    """Exact label lookup (labels, not sentences)."""
    return LABEL_FR.get(text, text) if lang == "fr" else text


def fmt_date(dt: datetime, lang: str) -> str:
    if lang == "fr":
        return f"{_DAYS[dt.weekday()]} {dt.day} {_MONTHS[dt.month - 1]} {dt.year}"
    return dt.strftime("%a %d %b %Y")


def decimal_comma(text: str) -> str:
    """12.5 -> 12,5 (not inside times or file names: those have no digit.digit)."""
    return re.sub(r"(?<=\d)\.(?=\d)", ",", text)


# ---------------------------------------------------------------------------------------------
# sentence rules: (regex, French), applied to the whole message; first match wins
# ---------------------------------------------------------------------------------------------
_HOW = [
    (r"best climb rate over the window", "meilleure vitesse ascensionnelle sur la fenêtre"),
    (r"implied climb rate across a recording gap", "vitesse ascensionnelle déduite d'un trou d'enregistrement"),
    (r"speed ([\d.]+) km/h over a very short stretch", r"vitesse de \1 km/h sur un tronçon très court"),
    (r"(\d+)% of the stretch faster than ([\d.]+) km/h", r"\1 % du tronçon à plus de \2 km/h"),
    (r"implied speed ([\d.]+) km/h across a recording gap", r"vitesse déduite de \1 km/h sur un trou d'enregistrement"),
]


def _how(text: str) -> str:
    for pat, rep in _HOW:
        text = re.sub(pat, rep, text)
    return text


def _role(m: str) -> str:
    return ROLE_SHORT_FR.get(m, m)


_RULES: list[tuple[str, object]] = [
    # --- files
    (r"^(.+): no track points found$", r"\1 : aucun point de trace trouvé."),
    (r"^(.+): (\d+) of (\d+) points have no timestamp; timestamps are required to time a track$",
     r"\1 : \2 points sur \3 n'ont pas d'horodatage. Les horodatages sont obligatoires pour chronométrer une trace."),
    (r"^(.+): fewer than 2 usable timed points$", r"\1 : moins de 2 points utilisables avec horodatage."),
    (r"^(.+): (\d+) points without timestamp were dropped$", r"\1 : \2 points sans horodatage ont été écartés."),
    (r"^(.+): (\d+) points with invalid coordinates were dropped$", r"\1 : \2 points aux coordonnées invalides ont été écartés."),
    (r"^FIT support needs", "La lecture des fichiers FIT n'est pas disponible sur ce serveur."),
    (r"^unknown mode hint", "Type de partie inconnu."),
    (r"^(.+): unsupported format .*$", r"\1 : format non accepté. Utilisez IGC, GPX, KML ou FIT."),
    (r"^(.+): cannot read file \(.*\)$", r"\1 : fichier illisible."),
    (r"^(.+): file too large \(.*\)$", r"\1 : fichier trop volumineux."),
    (r"^(.+): not a valid GPX file \(.*\)$", r"\1 : ce n'est pas un fichier GPX valide."),
    (r"^(.+): not a valid KML file \(.*\)$", r"\1 : ce n'est pas un fichier KML valide."),
    (r"^(.+): not a readable FIT file \(.*\)$", r"\1 : ce n'est pas un fichier FIT lisible."),
    (r"^(.+): gx:Track has (\d+) timestamps but (\d+) coordinates$",
     r"\1 : la trace KML contient \2 horodatages mais \3 coordonnées."),
    (r"^(.+): this KML only has a plain line path without timestamps; .*$",
     r"\1 : ce KML ne contient qu'une ligne simple, sans horodatage. Les horodatages sont obligatoires (une trace gx:Track avec des éléments <when>). Si votre application propose aussi un export GPX, utilisez-le."),
    (r"^(.+): no gx:Track found in KML$", r"\1 : aucune trace gx:Track trouvée dans le KML."),
    (r"^(.+): no valid HFDTE date header; timestamps cannot be built$",
     r"\1 : pas d'en-tête de date HFDTE valide, les horodatages ne peuvent pas être reconstitués."),
    (r"^(.+): (\d+) 2D-fix \(V\) records were ignored$", r"\1 : \2 enregistrements en 2D (V) ont été ignorés."),
    # --- merging files
    (r"^no track to merge$", "Aucune trace à fusionner."),
    (r"^(.+): (\d+) points fall inside the time range of a more specific file and were not used$",
     r"\1 : \2 points tombent dans la plage horaire d'un fichier plus précis et n'ont pas été utilisés."),
    (r"^fewer than 2 points remain after merging$", "Moins de 2 points après la fusion des fichiers."),
    (r"^gap of ([\d.]+) min at (\S+) \(moved ([\d.]+) km while not recorded\)$",
     r"Trou d'enregistrement de \1 min à \2 (\3 km parcourus sans enregistrement)."),
    (r"^position jump of (\d+) km/h at (\S+)$", r"Saut de position à \1 km/h à \2."),
    # --- segmentation
    (r"^a track needs at least 2 points to be segmented$", "Une trace doit avoir au moins 2 points."),
    (r"^no labelling satisfies the file hints.*$",
     "Aucun découpage ne respecte à la fois le contenu indiqué pour chaque fichier et les instants de transition choisis. "
     "Vérifiez que les instants sont dans l'ordre chronologique et cohérents avec ce que contient chaque fichier."),
    (r"^no flight part found: such a track would not be registered$",
     "Aucun vol détecté : une telle trace ne serait pas enregistrée."),
    (r"^flight lasts only (\d+) s; check the detection$", r"Le vol ne dure que \1 s : vérifiez la détection."),
    (r"^flight loses only (\d+) m of altitude; check the detection$",
     r"Le vol ne perd que \1 m d'altitude : vérifiez la détection."),
    (r"^no ascent on foot found$", "Aucune montée à pied détectée."),
    (r"^the start of (\w+) \((\S+)\) is ambiguous; check it on the plot and fix the transition by hand if needed$",
     lambda m: f"Le début de la partie « {_role(m.group(1))} » ({m.group(2)}) est ambigu : vérifiez-le sur les graphiques "
               "et fixez la transition vous-même si besoin."),
    (r"^(\w+): the recording has a ([\d.]+) min gap just before it, so its exact start is uncertain$",
     lambda m: f"Partie « {_role(m.group(1))} » : l'enregistrement a un trou de {m.group(2)} min juste avant, "
               "son début exact est donc incertain."),
    # --- chrono
    (r"^some fixes have no altitude and cannot be tested against the altitude bands$",
     "Certains points n'ont pas d'altitude et ne peuvent pas être comparés aux bandes d'altitude."),
    (r"^FLAGGED: the approach seems to use the Mont-Blanc tramway \(not authorised\): no ranking and no badge until reviewed$",
     "TRACE SIGNALÉE : l'approche semble utiliser le tramway du Mont-Blanc (non autorisé). Ni classement ni badge tant que l'équipe n'a pas examiné la trace."),
    (r"^FLAGGED: the approach seems to use a lift \(not authorised\): no ranking and no badge until reviewed$",
     "TRACE SIGNALÉE : l'approche semble utiliser une remontée mécanique (non autorisée). Ni classement ni badge tant que l'équipe n'a pas examiné la trace."),
    (r"^the approach has a stretch to review for a possible tram or lift ride$",
     "L'approche comporte un tronçon à examiner : un trajet en tramway ou en remontée mécanique est possible."),
    (r"^the track never enters the summit cylinder on foot(.*)$", lambda m: _summit_never(m.group(1))),
    (r"^the track leaves the summit cylinder on foot, not by flight \(at (\S+)\); no HF/BHF badge$",
     r"La trace quitte le cylindre du sommet à pied et non en vol (à \1) : pas de badge HF ni BHF."),
    (r"^the track never leaves the summit cylinder$", "La trace ne quitte jamais le cylindre du sommet."),
    (r"^the track does not pass through the Nid d'Aigle cylinder on foot before the summit: no climbing chrono and no ranking \(the HF/BHF badge does not need it\)$",
     "La trace ne passe pas à pied par le cylindre du Nid d'Aigle avant le sommet : pas de chrono de montée ni de classement "
     "(le badge HF ou BHF n'en a pas besoin)."),
    (r"^a crossing happened across a recording gap of two minutes or more; the chrono is only accurate to within that gap$",
     "Un passage de cylindre a eu lieu pendant un trou d'enregistrement de deux minutes ou plus : le chrono n'est précis qu'à la durée de ce trou près."),
    (r"^the summit is reached before leaving Nid d'Aigle: inconsistent track$",
     "Le sommet est atteint avant la sortie du Nid d'Aigle : trace incohérente."),
    (r"^no flight part in the track: it would not be registered in the ranking$",
     "Aucune partie vol dans la trace : elle ne serait pas enregistrée au classement."),
    # --- tram and lift check
    (r"^tram and lift check NOT performed: no line geometry loaded.*$",
     "Le contrôle du tramway et des remontées mécaniques n'est pas encore actif : le tracé des lignes n'est pas chargé."),
    (r"^the tram timetable for this date is not loaded: the tram was assumed to be running$",
     "Les horaires du tramway pour cette date ne sont pas chargés : le tramway est supposé en service."),
    (r"^some fixes have no altitude: the climb-rate test could not use them$",
     "Certains points n'ont pas d'altitude : le test de vitesse ascensionnelle ne les a pas utilisés."),
    (r"^follows the rails but not fast \((.*): (n/a|[\d.]+ m/h), ([\d.]+) km/h\)$",
     lambda m: f"suit la voie, mais pas vite ({_how(m.group(1))} : {m.group(2)}, {m.group(3)} km/h)"),
    (r"^fast on the rails \((.*)\) but the tram is not running then$",
     r"rapide sur la voie (\1) alors que le tramway ne circule pas à ce moment-là"),
    (r"^fast near the rails \((.*)\) and labelled as a bike ride, (\d+) m from the line: possibly a bicycle on a parallel road$",
     r"rapide près de la voie (\1), classé comme trajet à vélo, à \2 m de la ligne : peut-être un vélo sur une route parallèle"),
    (r"^follows the rails, tram running \((yes|unknown)\), (.*): (n/a|[\d.]+ m/h)$",
     lambda m: f"suit la voie, tramway en service ({'oui' if m.group(1) == 'yes' else 'horaires inconnus'}), "
               f"{_how(m.group(2))} : {m.group(3)}"),
    (r"^follows the lift line at walking pace \((.*)\)$", lambda m: f"suit la ligne de la remontée à pas de marche ({_how(m.group(1))})"),
    (r"^fast near the lift line \((.*)\) and labelled as a bike ride, (\d+) m from the line: possibly a bicycle on a parallel road$",
     lambda m: f"rapide près de la ligne de la remontée ({_how(m.group(1))}), classé comme trajet à vélo, à {m.group(2)} m de la ligne : "
               "peut-être un vélo sur une route parallèle"),
    (r"^follows the lift line at lift speed \((.*)\)$", lambda m: f"suit la ligne de la remontée à la vitesse d'une remontée ({_how(m.group(1))})"),
    (r"^(tram|lift|review): (tram|lift) (\S+Z) - (.*)$", None),   # duplicate of the transport section: dropped by the service
    # --- service
    (r"^Choose at least one track file.*$", "Choisissez au moins un fichier de trace (IGC, GPX, KML ou FIT)."),
]


def _summit_never(tail: str) -> str:
    out = "La trace n'entre jamais à pied dans le cylindre du sommet"
    m = re.match(r" \(closest approach (\d+) m, radius (\d+) m\)(.*)$", tail)
    if m:
        out += f" (point le plus proche à {m.group(1)} m, rayon de {m.group(2)} m)"
        tail = m.group(3)
    else:
        m = re.match(r" \(inside the radius, altitudes were (\d+) to (\d+) m against a band of (\d+) to (\d+) m\)(.*)$", tail)
        if m:
            out += (f" (dans le rayon, les altitudes allaient de {m.group(1)} à {m.group(2)} m "
                    f"pour une bande de {m.group(3)} à {m.group(4)} m)")
            tail = m.group(5)
    if "; it entered only while flying" in tail:
        out += " ; elle n'y est entrée qu'en vol"
    return out + "."


def translate(lang: str, message: str) -> str:
    """The French for one analysis message (unchanged for English or for an unknown message)."""
    if lang != "fr":
        return message
    for pat, rep in _RULES:
        m = re.match(pat, message)
        if not m:
            continue
        if rep is None:
            return message
        out = rep(m) if callable(rep) else m.expand(rep)
        return decimal_comma(out)
    return message


# ---------------------------------------------------------------------------------------------
# messages written by the service itself, in both languages
# ---------------------------------------------------------------------------------------------
MSG = {
    "no_file": {
        "en": "Choose at least one track file (IGC, GPX, KML or FIT).",
        "fr": "Choisissez au moins un fichier de trace (IGC, GPX, KML ou FIT).",
    },
    "bad_time": {
        "en": "{label}: cannot read {text!r} as a time. Use a form like 2026-09-12T09:41:10Z "
              "(add Z for UTC, or an offset such as +02:00).",
        "fr": "{label} : impossible de lire « {text} » comme un horaire. Utilisez une forme comme 2026-09-12T09:41:10Z "
              "(Z pour UTC) ou 2026-09-12T11:41:10+02:00.",
    },
    "bad_ext": {
        "en": "{name}: this file type is not accepted. Use IGC, GPX, KML or FIT.",
        "fr": "{name} : ce type de fichier n'est pas accepté. Utilisez IGC, GPX, KML ou FIT.",
    },
    "bad_mode": {"en": "{name}: unknown part type {mode!r}.", "fr": "{name} : type de partie inconnu."},
    "empty": {
        "en": "{name}: the file is empty. Check the export and send it again.",
        "fr": "{name} : le fichier est vide. Vérifiez l'export et envoyez-le à nouveau.",
    },
    "too_many": {
        "en": "This track has {n:,} points, more than the {max:,} the service accepts. "
              "Export the days separately or at a lower recording rate.",
        "fr": "Cette trace compte {n} points, plus que les {max} acceptés par le service. "
              "Exportez les journées séparément ou avec une fréquence d'enregistrement plus basse.",
    },
    "cut_walk_start": {"en": "Start of the walk", "fr": "Début de la montée à pied"},
    "cut_takeoff": {"en": "Take-off", "fr": "Décollage"},
    "cut_landing": {"en": "Landing", "fr": "Atterrissage"},
    "cut_bike_return_start": {"en": "Start of the ride back", "fr": "Début du retour à vélo"},
}


def msg(lang: str, key: str, **kw) -> str:
    text = MSG[key]["fr" if lang == "fr" else "en"]
    if key == "too_many" and lang == "fr":
        kw = {**kw, "n": f"{kw['n']:,}".replace(",", " "), "max": f"{kw['max']:,}".replace(",", " ")}
    return text.format(**kw)
