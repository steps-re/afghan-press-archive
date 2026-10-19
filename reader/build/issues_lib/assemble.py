"""Last stage of the issue index: merge the fitted issue boundaries with the masthead dates and
write app/issues/<book>.json.

Pipeline (run in one working dir holding <book>.jsonl from /api/download/book/<book>.jsonl):
  parse.py   running heads -> heads.json (issue no., page-in-issue, year, cover flag)
  fit.py     one non-decreasing (year, issue) label per page -> issues_fit.json
  refine.py  pin each start with printed page numbers and contents covers -> issues.json
  dates.py / dates2.py   Gemini Flash copies the masthead dates as printed -> dates*.json
  assemble.py  this file

Date rule, in order of trust:
  1. Hijri and Gregorian both printed and within 2 days of each other: the printed Gregorian.
  2. Only one printed: that one (Gregorian year taken from the Hijri year when not printed).
  3. Both printed but disagreeing: Hijri only, shown as approximate. One of the two was
     misread (3 of 25 checked pairs were ~10 days apart: a dropped digit), and we cannot
     tell which.
Then the paper's own schedule is enforced: issues came out on the 1st and 15th of the Hijri
month, so a date that does not advance 12-17 days per issue number is dropped, not shown.
"""
import datetime, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.issues import hijri_to_gregorian  # noqa: E402
from hparse import parse as hparse  # noqa: E402
from gparse import parse as gparse  # noqa: E402

BOOK = sys.argv[1] if len(sys.argv) > 1 else "adl0616"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(__file__), "..", "..", "app", "issues", f"{BOOK}.json")


def hijri_month_year(s):
    """Month and year when the day is not printed, for placing a Gregorian day-month."""
    iso = hparse(("15 " + s) if s else None)
    return iso


# Double issues, confirmed on the scan (year 5's last is printed "شماره ۲۳-۲۴", page 1756).
NO_LABEL = {(5, 23): "23–24"} if BOOK == "adl0616" else {}

its = json.load(open("issues.json"))
d1 = json.load(open("dates.json")) if os.path.exists("dates.json") else {}
d2 = json.load(open("dates2.json")) if os.path.exists("dates2.json") else {}
stats = {"printed_gregorian": 0, "hijri_only": 0, "conflict": 0, "undated": 0, "dropped": 0}
rows = []
for it in its:
    k = f'{it["year"]}-{it["no"]}@{it["start"]}'
    a, b = d1.get(k, {}), d2.get(k, {})
    # Prefer whichever pass read a full date. The first pass sometimes returned the founding
    # year printed in the title logo (۱۳۲۹) for issues whose masthead sits after a contents page.
    h_iso = a.get("hijri_iso") or hparse(a.get("hijri")) or hparse(b.get("hijri"))
    h_raw = next((x for x in (a.get("hijri"), b.get("hijri")) if hparse(x)), None) \
        or b.get("hijri") or a.get("hijri")
    g_raw = a.get("gregorian") or b.get("gregorian")
    gp = gparse(g_raw)
    anchor = h_iso or hijri_month_year(h_raw)
    g_calc = hijri_to_gregorian(anchor) if anchor else None
    greg = None
    if gp and g_calc:
        day, mon, yr = gp
        cand = []
        for y in ([yr] if yr else [g_calc.year - 1, g_calc.year, g_calc.year + 1]):
            try:
                cand.append(datetime.date(y, mon, day))
            except ValueError:
                pass
        best = min(cand, key=lambda c: abs((c - g_calc).days)) if cand else None
        if best and (abs((best - g_calc).days) <= 2 or not h_iso):
            greg = best
        elif best:
            stats["conflict"] += 1
    rows.append({"year": it["year"], "no": it["no"],
                 "no_label": NO_LABEL.get((it["year"], it["no"])),
                 "start": it["start"], "end": it["end"],
                 "hijri_printed": h_raw, "hijri_iso": h_iso,
                 "gregorian": greg.isoformat() if greg else None})

# the schedule check
for y in sorted({r["year"] for r in rows}):
    seq = [r for r in rows if r["year"] == y]
    def when(r):
        if r["gregorian"]:
            return datetime.date.fromisoformat(r["gregorian"])
        return hijri_to_gregorian(r["hijri_iso"]) if r["hijri_iso"] else None
    for i, r in enumerate(seq):
        w = when(r)
        if not w:
            continue
        nbrs = [(s, when(s)) for s in seq[max(0, i - 2):i] + seq[i + 1:i + 3] if when(s)]
        ok = sum(1 for s, ws in nbrs
                 if 12 * abs(s["no"] - r["no"]) <= abs((ws - w).days) <= 17 * abs(s["no"] - r["no"]))
        if nbrs and ok == 0:
            r["gregorian"] = None
            r["hijri_iso"] = None
            stats["dropped"] += 1

for r in rows:
    if r["gregorian"]:
        stats["printed_gregorian"] += 1
    elif r["hijri_iso"]:
        stats["hijri_only"] += 1
    else:
        stats["undated"] += 1

years = sorted({r["year"] for r in rows})
doc = {
    "book": BOOK,
    "note": (f"{len(rows)} issues, from years {', '.join(map(str, years))} of the paper"
             + (f"; year {', '.join(map(str, gaps))} is not in this copy. " if (gaps := [y for y in
                range(years[0], years[-1]) if y not in years]) else ". ")
             +
             "Issue boundaries were read by machine from the running heads (year, number, page) "
             "and dates from each masthead, then checked against the scans. A boundary can be a "
             "page out; the scan is the record."),
    "method": "build/issues_lib (parse, fit, refine, dates, assemble)",
    "built": datetime.date.today().isoformat(),
    "stats": stats,
    "issues": rows,
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(stats, "->", OUT)
