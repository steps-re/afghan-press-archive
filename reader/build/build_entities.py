"""Build a place-name finding aid over the corpus.

What a library means by a finding aid is an index someone can browse when they do not yet know
what to search for. Full-text search only answers questions you can already phrase.

The hard rule here is that no name is invented. Every place comes from GeoNames (CC-BY 4.0),
matched against the corpus by exact normalised phrase using the SAME normalisation as the
search index, so a hit means those characters are on that page. Nothing is inferred from
context, no model is called, and the output is a pointer into the text rather than a claim
about it. A reader following a link sees the page image and decides for themselves.

The interesting engineering problem is precision, not recall. Afghan settlement names are
ordinary Persian words -- there are villages called Bāgh (garden), Sang (stone), Naw (new) --
so a naive gazetteer match tags most of the corpus with nonsense. Two deterministic filters
handle it, both documented below, and both preferring to drop a real place over keeping a
false one: a finding aid that sends a scholar to fifty wrong pages is worse than one that
misses a village.
"""
import io, json, os, re, sqlite3, sys, unicodedata, urllib.request, zipfile

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
OUT = os.path.join(DATA, "entities.json")

# Afghanistan is the subject; the rest are the polities the Afghan press of 1870-1930 actually
# wrote about. Without them the index misses Peshawar, Bukhara, Istanbul and Delhi entirely.
COUNTRIES = ["AF", "IR", "PK", "UZ", "TJ", "TM", "IN", "TR"]

# SIGNIFICANCE, NOT FREQUENCY. The first build of this index filtered on document frequency --
# drop any name appearing on more than 2% of pages as a probable common word -- and it failed
# in the most useful possible way: it dropped KABUL (9,102 pages) while keeping دیوار "wall",
# دروازه "gate", انجمن "society" and دوستی "friendship", all of which name hamlets somewhere in
# Afghanistan. The lesson is that frequency runs the wrong way. A place that matters to this
# corpus is mentioned constantly, and GeoNames' Afghan coverage is mostly unpopulated villages
# whose names are ordinary nouns, so a frequency ceiling removes the signal and keeps the noise.
#
# Filtering on the gazetteer's own significance markers instead cuts ~53,000 candidate places
# to a few hundred that a historian would recognise, and needs no frequency rule at all.
ADMIN_CODES = {"PPLC",    # national capital
               "PPLA",    # first-order administrative capital (provincial seat)
               "PPLA2",   # second-order (district seat)
               "PPLA3"}
MIN_POP = 20000           # a place of this size in 1870-1930 terms is a town, not a hamlet

# Significance filtering fixed Afghanistan but not the neighbours: a modern Indian steel town
# (Bhilai, founded 1955) and a Turkish provincial capital (Ordu, whose name is the ordinary
# Persian word اردو "army/camp") both cleared a population bar while being either anachronistic
# or a pure homograph. Outside Afghanistan the gazetteer is not the right instrument at all --
# what matters is not how big a city is today but whether the Afghan press of 1870-1930 wrote
# about it. That is a historical judgement, so it is made explicitly, once, here, and can be
# argued with. Every entry is a city that appears in the standard historiography of the period's
# Afghan press and its Persianate, Indian and Ottoman horizons.
PERIOD_CITIES = {
    "PK": ["Peshawar", "Lahore", "Karachi", "Quetta", "Rawalpindi", "Multan", "Sialkot"],
    "IN": ["Delhi", "Mumbai", "Kolkata", "Hyderabad", "Lucknow", "Amritsar", "Aligarh",
           "Srinagar", "Madras", "Agra", "Bhopal"],
    "IR": ["Tehran", "Mashhad", "Herat", "Esfahan", "Shiraz", "Tabriz", "Qom", "Kerman",
           "Yazd", "Bushehr", "Zahedan"],
    "UZ": ["Bukhara", "Samarkand", "Tashkent", "Khiva", "Andijon", "Kokand"],
    "TJ": ["Dushanbe", "Khujand"],
    "TM": ["Merv", "Mary", "Ashgabat"],
    "TR": ["Istanbul", "Ankara", "Izmir", "Bursa", "Konya", "Erzurum"],
}

# Homographs that survive every structural filter because they are simultaneously a real
# settlement and an everyday Persian word. Listed by their normalised form, with the gloss that
# makes the collision obvious. Dropping them costs a handful of genuine mentions and removes
# thousands of false ones.
STOPWORDS = {
    "اردو": "army, camp",          "کلمه": "word",
    "اسیر": "captive",             "بهار": "spring (season)",
    "اندیشه": "thought",           "بدین": "in this",
    "جم": "Jamshid, a given name", "گوشه": "corner",
    "دیوار": "wall",               "دروازه": "gate",
    "انجمن": "society, assembly",  "دوستی": "friendship",
    "سالار": "leader",             "پناه": "refuge",
    "دراز": "long",                "جزیره": "island",
    "گمان": "supposition",         "سرور": "joy, lord",
    "خانه": "house",               "زمان": "time",
    "دولت": "state, government",   "بیان": "expression",
    "میان": "between",             "نو": "new",
    "باغ": "garden",               "سنگ": "stone",
    "شهر": "city",                 "ده": "village, ten",
    # Found by reading the built index rather than by reasoning about it: each of these was a
    # top-20 "place" until someone looked at the Persian.
    "داریم": "we have",            "میزان": "balance, scale; a month",
    "خوشی": "happiness",           "شیوه": "manner, method",
    "شوه": "manner (variant)",     "خواهان": "wanting, desirous",
    "گوشته": "meat, past (variant)", "کوهستان": "mountain country",
    "ساغر": "goblet",
    # norm() folds ة and ۀ to ه but leaves the Urdu heh-goal ہ alone, because it is shared with
    # the search index and changing it would mean reindexing 69,624 pages. So spellings that
    # differ only by that character have to be listed separately.
    "گشته": "having become",       "گوشتہ": "meat, past (Urdu heh)",
    "گشتہ": "having become (Urdu heh)",
    # Dushanbe was a village until the 1920s and is not what this corpus is naming: دوشنبه is
    # also the ordinary word for Monday, which is what 474 hits in a periodical run actually are.
    "دوشنبه": "Monday",
}

ARABIC = re.compile(r"[؀-ۿ]")
HARAKAT = dict.fromkeys(range(0x064B, 0x0653), None)
DROP = dict.fromkeys(map(ord, "«»؛،؟!?.,:;()[]{}\"'’‘—–-*/\\|_=+<>#%&@~`^$"), " ")
MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه",
                     "ﻻ": "لا", "ـ": "", "‌": " ", "‏": "", "‎": ""})
MARK = re.compile(r"\[(?:ILL|\?|BLANK PAGE|PLATE)\]")


def norm(t: str) -> str:
    """Identical to app.main.norm. It must stay identical: the whole guarantee of this index is
    that a match here is a match there."""
    t = MARK.sub(" ", t or "")
    t = re.sub(r"\[([^\]]*)\؟?\]", r"\1", t)
    t = unicodedata.normalize("NFKC", t).translate(MAP).translate(HARAKAT).translate(DROP)
    t = re.sub(r"[۰-۹٠-٩\d]+", " 0 ", t)
    return " ".join(w for w in t.split() if w)


# The stoplist is written in plain Persian for readability, but matching happens on normalised
# forms, so it has to be folded the same way the corpus was.
STOP_NORM = {}


def fetch_gazetteer() -> list:
    """GeoNames country dumps. Columns are documented at download.geonames.org/export/dump/."""
    rows = []
    for cc in COUNTRIES:
        url = f"https://download.geonames.org/export/dump/{cc}.zip"
        print(f"  fetching {cc}", flush=True)
        raw = urllib.request.urlopen(url, timeout=180).read()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            txt = z.read(f"{cc}.txt").decode("utf-8", "replace")
        for line in txt.split("\n"):
            f = line.split("\t")
            if len(f) < 15 or f[6] != "P":            # P = populated place
                continue
            pop = int(f[14] or 0)
            code = f[7]
            if cc == "AF":
                if pop < MIN_POP and code not in ADMIN_CODES:
                    continue
            elif f[1] not in PERIOD_CITIES.get(cc, ()):
                continue
            names = [f[1]] + [a for a in (f[3] or "").split(",") if a]
            arabic = [n.strip() for n in names if ARABIC.search(n)]
            if not arabic:
                continue
            rows.append({"geonameid": f[0], "name": f[1], "country": cc, "feature": code,
                         "lat": float(f[4]), "lon": float(f[5]), "population": pop,
                         "variants": sorted(set(arabic))})
    return rows


def main():
    STOP_NORM.update({norm(k): v for k, v in STOPWORDS.items()})
    db = sqlite3.connect(os.path.join(DATA, "corpus.db"))
    total_pages = db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]

    cache = os.path.join(DATA, "_geonames_cache.json")
    if os.path.exists(cache):
        places = json.load(open(cache))
    else:
        places = fetch_gazetteer()
        json.dump(places, open(cache, "w"), ensure_ascii=False)
    print(f"  {len(places)} gazetteer places with Perso-Arabic forms", flush=True)

    # Several gazetteer entries can carry the same name (four Darwazahs, three Salars). Merge
    # them into one indexed place, keeping the most significant as the representative, so the
    # finding aid lists "Herat" once rather than four times with identical page lists.
    merged = {}
    for p in places:
        key = norm(p["name"])
        cur = merged.get(key)
        if cur is None or (p["population"], p["feature"] in ADMIN_CODES) > \
                (cur["population"], cur["feature"] in ADMIN_CODES):
            if cur:
                p = dict(p, variants=sorted(set(p["variants"]) | set(cur["variants"])),
                         merged_ids=cur.get("merged_ids", []) + [cur["geonameid"]])
            merged[key] = p
        else:
            cur["variants"] = sorted(set(cur["variants"]) | set(p["variants"]))
            cur.setdefault("merged_ids", []).append(p["geonameid"])
    places = list(merged.values())
    print(f"  {len(places)} places after merging same-name entries", flush=True)

    # phrase -> set of geonameids
    phrase2ids, byid = {}, {p["geonameid"]: p for p in places}
    for p in places:
        for v in p["variants"]:
            n = norm(v)
            # A one- or two-character name is not evidence of anything once normalisation has
            # folded the orthography.
            if len(n.replace(" ", "")) < 4 or n in STOP_NORM:
                continue
            phrase2ids.setdefault(n, set()).add(p["geonameid"])

    maxlen = max((len(p.split()) for p in phrase2ids), default=1)
    print(f"  {len(phrase2ids)} distinct normalised phrases, up to {maxlen} words", flush=True)

    hits = {}
    seen_pages = 0
    for book, page, txt in db.execute("SELECT book, page, txt FROM pages"):
        seen_pages += 1
        if seen_pages % 10000 == 0:
            print(f"  scanned {seen_pages}/{total_pages}", flush=True)
        if not txt:
            continue
        w = txt.split()
        found = set()
        for i in range(len(w)):
            for L in range(1, maxlen + 1):
                if i + L > len(w):
                    break
                ph = " ".join(w[i:i + L])
                if ph in phrase2ids:
                    found |= phrase2ids[ph]
        for gid in found:
            hits.setdefault(gid, []).append((book, page))

    out = {"generated_from": "GeoNames (CC-BY 4.0), download.geonames.org",
           "method": "Exact normalised phrase match against the search index's own "
                     "normalisation. No inference, no model. A hit means those characters "
                     "appear on that page.",
           "selection": f"National, provincial and district capitals, plus any populated place "
                        f"over {MIN_POP:,}. Afghanistan's gazetteer is mostly unpopulated "
                        f"villages whose names are ordinary Persian nouns, so indexing all of "
                        f"them produces noise, not a finding aid.",
           "known_limitation": "Some place names are also ordinary words or personal names "
                               "(Husayn, Andisheh). A page listed under a name contains that "
                               "string; it is not a claim that the page discusses the place. "
                               "Follow the link and read the image.",
           "filters": {"min_normalised_chars": 4, "min_population_afghanistan": MIN_POP,
                       "admin_codes": sorted(ADMIN_CODES),
                       "outside_afghanistan": "explicit list of cities the Afghan press of "
                                              "1870-1930 wrote about, not a population rule",
                       "homograph_stoplist": STOPWORDS},
           "total_pages": total_pages,
           "places": []}
    for gid, pages in hits.items():
        p = byid[gid]
        books = sorted({b for b, _ in pages})
        out["places"].append({
            "id": gid, "name": p["name"], "country": p["country"], "feature": p["feature"],
            "lat": p["lat"], "lon": p["lon"], "population": p["population"],
            "variants": p["variants"],
            "pages": len(pages), "books": len(books),
            "sample": [{"book": b, "page": pg} for b, pg in sorted(pages)[:200]],
            "source": f"https://www.geonames.org/{gid}",
        })
    out["places"].sort(key=lambda r: -r["pages"])
    json.dump(out, open(OUT, "w"), ensure_ascii=False)
    print(f"done: {len(out['places'])} places indexed -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
