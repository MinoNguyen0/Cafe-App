# places.py
# helpers for the map and the cafe links:
#   find_address()  - turns "Katherine Pl, CBD" into map coordinates
#   clean_website() / clean_handle() - tidy up what people type into the link boxes

import json
import math
import re
import unicodedata
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

# OpenStreetMap's free address search ("geocoding").
# their rules: max 1 request per second, and say who you are in the
# User-Agent. we only call it when someone presses "find on map" or adds a
# cafe without placing the pin, so we're nowhere near the limit.
# NOTE: if this site ever gets lots of users, you'd want a paid geocoder.
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "OshiCollective/0.1 (student project)"

# a box around greater Melbourne. results inside it are preferred, so
# "Katherine Pl" finds the CBD one and not the one in Mount Evelyn
MELBOURNE_BOX = "144.55,-37.55,145.45,-38.10"


def find_address(text):
    """Returns (lat, lng) for an address, or None if it can't be found."""
    query = urllib.parse.urlencode({
        "q": f"{text}, Melbourne",
        "format": "json",
        "limit": 1,
        "countrycodes": "au",
        "viewbox": MELBOURNE_BOX,
    })
    req = urllib.request.Request(f"{NOMINATIM}?{query}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=8) as res:
            results = json.load(res)
    except Exception:
        # no internet, site down, etc. - not worth crashing the page over
        return None

    if not results:
        return None
    return float(results[0]["lat"]), float(results[0]["lon"])


def clean_website(url):
    """
    "nanasgreentea.com.au" -> "https://nanasgreentea.com.au"
    returns "" for anything that isn't a normal http(s) link.

    NOTE (security): this matters! the link ends up in <a href="...">.
    if we let someone save "javascript:stealCookies()" as a website, clicking
    it would run their code. so only http:// and https:// are allowed.
    """
    url = (url or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or "." not in parsed.netloc:
        return ""
    return url


def clean_handle(text):
    """
    people paste instagram/tiktok in all sorts of ways - turn them all into
    just the handle:
      "@nanas.melb"                               -> "nanas.melb"
      "https://www.instagram.com/nanas.melb/"     -> "nanas.melb"
      "https://www.tiktok.com/@nanas.melb?lang=en" -> "nanas.melb"
    """
    text = (text or "").strip()
    if "/" in text:
        # it's a link - take the first bit of the path after the domain
        path = urllib.parse.urlparse(text if "://" in text else "https://" + text).path
        text = path.strip("/").split("/")[0]
    text = text.lstrip("@")
    # handles are only letters, numbers, dots and underscores
    return text if re.fullmatch(r"[A-Za-z0-9._]{1,30}", text) else ""


# ---- duplicate cafe check ----
# used when someone adds a cafe, to ask "is it one of these?" first

# words that don't help tell cafes apart ("The Butter Room Cafe" vs "Butter Room")
FILLER_WORDS = {"the", "cafe", "coffee", "bar", "restaurant", "shop", "house", "melbourne", "and"}


def simplify_name(name):
    """
    "The Butter Room Café!" -> "butterroom"
    lowercase, accents removed (é -> e), filler words and symbols dropped
    """
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z0-9]+", text)
    kept = [w for w in words if w not in FILLER_WORDS] or words  # don't end up with nothing
    return "".join(kept)


def names_match(a, b):
    """True if two cafe names are probably the same place."""
    a, b = simplify_name(a), simplify_name(b)
    if not a or not b:
        return False
    if a == b:
        return True
    # one inside the other: "nanas" vs "nanasgreentea" (only if it's not tiny)
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        return True
    # typos: SequenceMatcher gives 0-1 for how alike two strings are
    return SequenceMatcher(None, a, b).ratio() >= 0.8


def metres_apart(lat1, lng1, lat2, lng2):
    """
    Distance between two map points in metres ("haversine" formula -
    the maths for distances on a ball, since the earth isn't flat).
    """
    r = 6_371_000  # earth's radius in metres
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
