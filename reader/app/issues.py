"""Issue-level index for serials whose running heads name the issue.

A volume like Sirāj al-akhbār is 1,787 scanned pages bound from about a hundred issues, and a
historian asks for "year 2, number 13", not "page 570". The index is built offline
(build/build_issues.py) from the running heads our transcription already carries ("سال دوم ·
شماره ۱۳ · صحیفه ۱") and the masthead date on each issue's first page, then checked against the
scans. It ships as one small JSON file per volume next to this module, so adding it needs no
rebuild of the search index.
"""
import datetime, json, os, threading
from typing import Optional

HERE = os.path.join(os.path.dirname(__file__), "issues")
_lock = threading.Lock()
_cache: dict = {}

HIJRI_MONTHS = ["Muḥarram", "Ṣafar", "Rabīʿ I", "Rabīʿ II", "Jumādá I", "Jumādá II", "Rajab",
                "Shaʿbān", "Ramaḍān", "Shawwāl", "Dhū al-Qaʿdah", "Dhū al-Ḥijjah"]


def for_book(book: str) -> Optional[dict]:
    with _lock:
        if book not in _cache:
            p = os.path.join(HERE, f"{book}.json")
            try:
                _cache[book] = json.load(open(p, encoding="utf-8"))
            except (OSError, ValueError):
                _cache[book] = None
    return _cache[book]


def at(book: str, page: int) -> Optional[dict]:
    """The issue a page belongs to, or None."""
    d = for_book(book)
    if not d:
        return None
    for it in d["issues"]:
        if it["start"] <= page <= it["end"]:
            return it
    return None


def hijri_to_gregorian(iso: str) -> Optional[datetime.date]:
    """Tabular (arithmetic) Islamic calendar. Kabul dated by sighting the moon, so this can be a
    day or two off; callers must present it as approximate."""
    try:
        y, m, d = (int(x) for x in iso.split("-"))
    except (AttributeError, ValueError):
        return None
    jd = d + int(29.5 * (m - 1) + 0.999999) + (y - 1) * 354 + (3 + 11 * y) // 30 + 1948439
    return datetime.date.fromordinal(jd - 1721425)


def hijri_label(iso: Optional[str]) -> str:
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return f"{d} {HIJRI_MONTHS[m - 1]} {y}"
    except (AttributeError, ValueError, IndexError):
        return ""


def label(it: dict) -> str:
    """'Year 2, no. 13 · 15 Rabīʿ I 1331 (≈ 23 Feb 1913)'"""
    s = f"Year {it['year']}, no. {it.get('no_label') or it['no']}"
    h = hijri_label(it.get("hijri_iso"))
    if it.get("gregorian"):
        # Printed in the masthead (and agreeing with the Hijri date where both are printed).
        g = datetime.date.fromisoformat(it["gregorian"])
        s += f" · {g.day} {g.strftime('%b')} {g.year}" + (f" ({h})" if h else "")
    elif h:
        g = hijri_to_gregorian(it["hijri_iso"])
        s += f" · {h}" + (f" (≈ {g.day} {g.strftime('%b')} {g.year})" if g else "")
    return s
