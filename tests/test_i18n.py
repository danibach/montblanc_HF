"""The languages of the site (site/i18n.js and site/i18n/*.js), run with Node: no browser.

The four catalogues must say the same things: same keys, same {places}, same plural forms; every text the code asks
for must exist; no text is left unused. The detection of the language is checked with the browser's language lists."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parent.parent / "site"
NODE = shutil.which("node")
LANGS = ["en", "fr", "de", "it"]
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def node(tmp_path, script):
    """Run ``script`` (an ES module) next to a copy of the page's modules; returns its stdout parsed as JSON."""
    for path in SITE.glob("*.js"):
        shutil.copy(path, tmp_path / path.name)
    if not (tmp_path / "i18n").exists():
        shutil.copytree(SITE / "i18n", tmp_path / "i18n")
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "run.mjs").write_text(script)
    done = subprocess.run([NODE, "run.mjs"], cwd=tmp_path, capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


@pytest.fixture(scope="module")
def catalogues(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cat")
    script = "const out = {};\n" + "".join(
        f"out.{c} = (await import('./i18n/{c}.js')).default;\n" for c in LANGS) + "console.log(JSON.stringify(out));\n"
    return node(tmp, script)


def places(value):
    texts = value.values() if isinstance(value, dict) else [value]
    return set().union(*(set(re.findall(r"\{(\w+)\}", t)) for t in texts))


def test_every_language_has_the_same_keys(catalogues):
    for code in LANGS[1:]:
        assert set(catalogues[code]) == set(catalogues["en"]), (
            code, sorted(set(catalogues["en"]) ^ set(catalogues[code]))[:10])


def test_every_language_keeps_the_places_and_the_plurals(catalogues):
    en = catalogues["en"]
    for code in LANGS[1:]:
        for key, value in catalogues[code].items():
            assert isinstance(value, dict) == isinstance(en[key], dict), (code, key, "plural in one language only")
            if isinstance(value, dict):
                assert set(value) == {"one", "other"}, (code, key)
            # a form may leave out the number ("the last outing"), never add a place the others do not have
            assert places(value) <= places(en[key]), (code, key)
            if not isinstance(value, dict):
                assert places(value) == places(en[key]), (code, key)


def test_no_text_is_empty(catalogues):
    for code in LANGS:
        for key, value in catalogues[code].items():
            for text in (value.values() if isinstance(value, dict) else [value]):
                assert text.strip(), (code, key)


def test_the_badge_is_named_the_same_in_its_texts(catalogues):
    # the "Validation pending" badge is quoted in several texts: they must use the name the badge itself carries
    for code in LANGS:
        name = catalogues[code]["status.pending"]
        for key in ("upload.published", "batch.sumChecked", "mark.published"):
            assert name in catalogues[code][key], (code, key)
        # and so is the list of tracks without a flight, quoted in the help
        assert re.sub(r"\s*\(.*", "", catalogues[code]["upload.noFlightTitle"]).strip() in catalogues[code]["help.refused.2.a"], code
        # and the badge in the help's answer about it, and the button to mark a flight
        assert name in catalogues[code]["help.upload.5.a"] and catalogues[code]["upload.markButton"] in catalogues[code]["help.refused.2.a"], code


def used_keys():
    """Keys the code asks for: t('key'), tr('key'), data-i18n attributes, and the prefixes of the keys it builds."""
    exact, prefixes = set(), set()
    for path in list(SITE.glob("*.js")) + [SITE / "index.html"]:
        if path.name == "i18n.js":
            continue
        text = path.read_text()
        exact.update(re.findall(r"""\btr?\(\s*'([\w.]+)'""", text))
        exact.update(re.findall(r"""data-i18n(?:-label)?="([\w.]+)\"""", text))
        prefixes.update(re.findall(r"""\btr?\(\s*`([\w.]+\.)\$\{""", text))
        # keys kept in tables (SEASONS, SORTS, STATUS…) are plain strings with a dot: found by the catalogue check below
        exact.update(re.findall(r"""'((?:season|sort|src|climb|status|mode|ffvl\.status|ffvl\.kind|help\.col|help\.up|wind|unit|mp|v3|heat|map|nav|col|stat|detail|filter|upload|batch|engine|api|sheet)\.[\w.]+)'""", text))
    return exact, prefixes


def test_every_text_the_code_asks_for_exists(catalogues):
    exact, prefixes = used_keys()
    missing = sorted(k for k in exact if k not in catalogues["en"] and not any(k.startswith(p) for p in prefixes))
    # a quoted word that only looks like a key (a CSS class, a route) is not a text: tolerate none, list what is found
    assert not missing, missing


def test_every_key_is_used_somewhere(catalogues):
    exact, prefixes = used_keys()
    sources = "\n".join(p.read_text() for p in list(SITE.glob("*.js")) + [SITE / "index.html"] if p.name != "i18n.js")
    orphans = []
    for key in catalogues["en"]:
        if key in exact or any(key.startswith(p) for p in prefixes):
            continue
        if f"'{key}'" in sources or f'"{key}"' in sources:
            continue
        # a key built from a key of the same family (the 8 winds, the help's `help.col.${…}`) is found by its prefix
        if re.search(r"""`%s\$\{""" % re.escape(key.rsplit(".", 1)[0] + "."), sources):
            continue
        orphans.append(key)
    assert not orphans, orphans


def test_the_language_is_the_browsers_first_one_the_site_has(tmp_path):
    out = node(tmp_path, """
Object.defineProperty(globalThis, 'navigator', { value: { languages: ['es-ES', 'it-IT', 'fr'] }, configurable: true });
const { detectLang, langOf, localeFor } = await import('./i18n.js');
console.log(JSON.stringify({
  first: detectLang(),
  none: detectLang(['es', 'pt-BR'], null),
  swiss: detectLang(['gsw-CH'], null),
  saved: detectLang(['fr'], 'de'),
  badSaved: detectLang(['fr'], langOf('xx')),
  region: langOf('de-AT'),
  upper: langOf('FR_ch'),
  empty: langOf(''),
  localeCH: localeFor('fr', ['fr-CH', 'en']),
  localeOther: localeFor('de', ['fr-CH']),
  localeGsw: localeFor('de', ['gsw']),
}));""")
    assert out == {"first": "it", "none": "en", "swiss": "de", "saved": "de", "badSaved": "fr", "region": "de",
                   "upper": "fr", "empty": None, "localeCH": "fr-CH", "localeOther": "de", "localeGsw": "de-CH"}


def test_a_text_is_filled_and_a_plural_follows_the_language(tmp_path):
    out = node(tmp_path, """
Object.defineProperty(globalThis, 'navigator', { value: { languages: ['en'] }, configurable: true });
const i = await import('./i18n.js');
const r = {};
for (const code of ['en', 'fr', 'de', 'it']) {
  await i.setLang(code);
  r[code] = { one: i.t('unit.outing', { n: 1 }), many: i.t('unit.outing', { n: 1234 }), zero: i.t('unit.outing', { n: 0 }),
              missing: i.t('no.such.key'), day: i.fmtDay('2021-09-29'), num: i.fmtNumber(1606), dec: i.fmtDecimal(12.34) };
}
console.log(JSON.stringify(r));""")
    assert out["en"]["one"] == "1 outing" and out["en"]["many"] == "1,234 outings"
    assert out["en"]["day"] == "29 Sep 2021" and out["en"]["dec"] == "12.3"
    assert out["fr"]["one"] == "1 sortie" and out["fr"]["zero"] == "0 sortie"  # French: 0 is singular
    assert out["fr"]["dec"] == "12,3" and out["de"]["one"] == "1 Tour" and out["it"]["many"].endswith("uscite")
    assert re.search(r"29 (sept|Sept)", out["fr"]["day"]) and "2021" in out["de"]["day"]
    assert all(v["missing"] == "no.such.key" for v in out.values())  # an unknown key shows itself, never "undefined"


def test_a_missing_text_falls_back_to_english(tmp_path):
    out = node(tmp_path, """
const i = await import('./i18n.js');
await i.setLang('fr');
console.log(JSON.stringify({ lang: i.getLang(), bad: await i.setLang('xx'), after: i.getLang(), link: i.tr('upload.needAccount', { link: 'LINK' }) }));""")
    assert out["lang"] == "fr" and out["bad"] == "en" and out["after"] == "en"
    assert "LINK" in out["link"]
