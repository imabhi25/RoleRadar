"""
Workday-specific location normalization.

Workday tenants publish locations in tenant-specific shapes:

    "US, CA, Santa Clara"          NVIDIA     country, state, city
    "US, TX"                       NVIDIA     country, state
    "US, CA, Remote"               NVIDIA     country, state, remote
    "16 YORK ST:TORONTO"           Sun Life   street address : CITY
    "745 THURLOW ST:VANCOUVER"     RBC        street address : CITY
    "Sun Life Toronto One York"    Sun Life   internal building name containing a city
    "AMER - Canada - Ontario - Toronto - University Ave"
    "TORONTO, Ontario, Canada"

`normalize_workday_location` turns those into one canonical label, or returns None when it cannot do so with
confidence (the caller then keeps the source label exactly as before). Nothing is guessed:

* a country, state/province or city is only used when it is in the tables below or unambiguous from context;
* a Canadian province is only added to a city when the city is in CA_CITY_PROVINCE;
* street addresses and building names are dropped only when a reliable city or region remains;
* "CA" is Canada or California only when the surrounding tokens say which, otherwise the label is left alone.

Canonical shapes:
    Canada:         "Toronto, Ontario, Canada" / "Ontario, Canada" / "Canada"
    United States:  "Santa Clara, CA, United States" / "Texas, United States"
    Remote:         "Remote - California, United States" / "Remote - Ontario, Canada"

Workplace words other than Remote (Hybrid, On-site) are dropped from the location: the workplace type is carried
by its own field. Only Workday postings use this module.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ingestion.normalizer import CURATED_CITIES

from ingestion.places import CA_CITY_PROVINCE, CA_PROVINCES, US_STATES  # noqa: E402  (shared tables)

_US_NAME_TO_CODE = {name.lower(): code for code, name in US_STATES.items()}
_CA_NAME_TO_CODE = {name.lower(): code for code, name in CA_PROVINCES.items()}
_CA_NAME_TO_CODE["québec"] = "QC"
_CA_NAME_TO_CODE["newfoundland"] = "NL"

_US_COUNTRY = {"us", "usa", "u.s.", "u.s.a.", "united states", "united states of america"}
_CA_COUNTRY = {"canada", "can"}
_REGION_PREFIX = re.compile(r"^(?:AMER|NAMER|NA|APAC|EMEA|LATAM)\s*[-–—:]\s*", re.I)
_WORKPLACE_WORDS = {"hybrid", "on-site", "onsite", "on site", "in-office"}
# Autodesk writes remote employees' location as "AMER - Canada - Ontario - Offsite/Home": the last part is a way of working,
# not a place. It is dropped (the raw label is kept) and never becomes a "Home, Ontario" city.
_HOME_WORDS = {"offsite", "off-site", "home", "offsite/home", "off-site/home", "home office", "work from home", "wfh"}
_STREET_SUFFIX = (
    r"(?:st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|way|lane|ln|hwy|highway|sq|square|pl|place|cres|"
    r"crescent|ct|court|pkwy|parkway|terrace|trail)"
)
_STREET_WITH_NUMBER = re.compile(rf"^\d+[A-Za-z]?(?:-\d+)?\s+.+$")
_STREET_NO_NUMBER = re.compile(rf"^(?:[\w.'’-]+\s+){{0,4}}{_STREET_SUFFIX}\.?(?:\s+(?:n|s|e|w|ne|nw|se|sw)\.?)?$", re.I)
_LOWER_CITY_WORDS = {"of", "de", "la", "le", "du", "des", "and", "the", "on", "upon"}


def canonical_country_name(name: Optional[str]) -> str:
    """Workday's own spelling ("United States of America") and the short forms map to one country name."""
    low = (name or "").strip().lower().rstrip(".")
    if low in _US_COUNTRY:
        return "United States"
    if low in _CA_COUNTRY:
        return "Canada"
    return (name or "").strip()


def is_home_word(label: Optional[str]) -> bool:
    return (label or "").strip().lower() in _HOME_WORDS


def _title_place(text: str) -> str:
    """'VANCOUVER' -> 'Vancouver', 'SANTA CLARA' -> 'Santa Clara'; mixed-case input is left as written."""
    text = text.strip()
    if text != text.upper() and text != text.lower():
        return text
    words = text.lower().split()
    out = []
    for i, word in enumerate(words):
        if i > 0 and word in _LOWER_CITY_WORDS:
            out.append(word)
        else:
            out.append(re.sub(r"(^|['’-])([a-zà-ÿ])", lambda m: m.group(1) + m.group(2).upper(), word))
    return " ".join(out)


def _is_street(part: str) -> bool:
    return bool(_STREET_WITH_NUMBER.match(part) or _STREET_NO_NUMBER.match(part))


def _split_parts(label: str) -> List[str]:
    return [p.strip(" ()") for p in re.split(r"\s*[:,]\s*|\s+[-–—]\s+", label) if p.strip(" ()")]


def _city_inside(text: str) -> Optional[Tuple[str, str]]:
    """A curated Canadian city appearing as whole words inside an internal name ('Sun Life Toronto One York').

    Refused when the text names another place too ("New York and Toronto Hub") or joins alternatives.
    """
    lowered = text.lower()
    if re.search(r"\s(?:and|or|&)\s|[/&|;]", lowered):
        return None
    places = [key for key in list(CA_CITY_PROVINCE) + list(CURATED_CITIES) if re.search(rf"\b{re.escape(key)}\b", lowered)]
    canadian = sorted({key for key in places if key in CA_CITY_PROVINCE})
    if len(set(places)) != 1 or len(canadian) != 1:
        return None
    return CA_CITY_PROVINCE[canadian[0]]


def normalize_workday_location(label: str) -> Optional[Dict[str, str]]:
    """Returns {'location', 'country'} for a Workday location label, or None when it should be kept as written."""
    if not label or not label.strip():
        return None
    squashed = re.sub(r"\s+", " ", label).strip()
    hierarchical = bool(_REGION_PREFIX.match(squashed)) and " - " in squashed   # "AMER - Country - Region - City - Site"
    text = _REGION_PREFIX.sub("", squashed)
    parts = _split_parts(text)
    if not parts:
        return None
    # "Washington, District of Columbia" is the city of Washington, not the state of Washington plus another region.
    merged: List[str] = []
    for index, part in enumerate(parts):
        if merged and merged[-1] == "\0dc-city":
            continue
        if part.lower() == "washington" and index + 1 < len(parts) and parts[index + 1].lower().rstrip(".") in ("district of columbia", "dc", "d.c"):
            merged.append("\0dc-city")
            continue
        merged.append(part)
    parts = merged

    remote = False
    country: Optional[str] = None
    region_code: Optional[str] = None
    city: Optional[str] = None
    leftovers: List[str] = []
    saw_ca_token = False
    us_state_hits: List[str] = []          # tokens that named a US state (name or code), in order

    for part in parts:
        low = part.lower().rstrip(".")
        if part == "\0dc-city":
            city, region_code = "Washington", "DC"
            country = country or "United States"
            us_state_hits.append("DC")
        elif low == "remote":
            remote = True
        elif low in _WORKPLACE_WORDS or low in _HOME_WORDS:
            continue
        elif low in _US_COUNTRY:
            country = country or "United States"
        elif low in _CA_COUNTRY:
            country = country or "Canada"
        elif low == "ca":
            saw_ca_token = True          # Canada or California: decided once the other tokens are known
        elif low in _CA_NAME_TO_CODE or (len(part) == 2 and part.upper() in CA_PROVINCES):
            if country == "United States" or region_code is not None:
                return None
            region_code = _CA_NAME_TO_CODE.get(low, part.upper())
            country = "Canada"
        elif low in _US_NAME_TO_CODE or (len(part) == 2 and part.upper() in US_STATES):
            code = _US_NAME_TO_CODE.get(low, part.upper())
            if country == "Canada":
                return None
            if region_code not in (None, code):
                return None
            region_code = code
            country = "United States"
            us_state_hits.append(part)
        elif low in CA_CITY_PROVINCE and city is None:
            city = CA_CITY_PROVINCE[low][0]
        elif _is_street(part):
            continue
        else:
            leftovers.append(part)

    if saw_ca_token:
        if country == "United States":
            if region_code is not None and region_code != "CA":
                return None
            region_code = "CA"           # "US, CA, Santa Clara": CA is California
            us_state_hits.append("CA")
        elif country == "Canada" or city is not None:
            country = "Canada"           # "CA, ON, Toronto": CA is Canada
        else:
            return None                  # a bare "CA": Canada or California, unknowable

    # "New York, NY": the state named twice means the first is the city.
    if country == "United States" and city is None and len(us_state_hits) >= 2:
        names = [h for h in us_state_hits if len(h) > 2]
        if names and not leftovers:
            city = _title_place(names[0])

    # A curated Canadian city names its own province and country.
    if city and country in (None, "Canada") and city.lower() in CA_CITY_PROVINCE:
        country = "Canada"
        region_code = region_code or CA_CITY_PROVINCE[city.lower()][1]

    # Free text left over: an internal building name containing a curated city, or one plain city name.
    if city is None and leftovers:
        plain = [x for x in leftovers if not _is_street(x)]
        if not plain or (len(plain) != 1 and not hierarchical):
            return None
        # Hierarchical labels read Country - Region - City - Site: the first free text is the city, the rest is a site name.
        candidate = plain[0]
        inner = _city_inside(candidate)
        if inner and (country in (None, "Canada")):
            city, country, region_code = inner[0], "Canada", region_code or inner[1]
        elif (region_code or country) and not re.search(r"\d", candidate) and len(candidate.split()) <= 4:
            city = _title_place(candidate)
        else:
            return None

    if country is None:
        return None
    if country == "Canada":
        pieces = [x for x in (city, CA_PROVINCES.get(region_code or "")) if x]
    elif city:
        pieces = [city, region_code] if region_code else [city]
    else:
        pieces = [US_STATES[region_code]] if region_code else []

    if remote:
        # Region-level remote spells the state out ("Remote - California, United States").
        if country == "United States" and city is None and region_code:
            pieces = [US_STATES[region_code]]
        return {"location": "Remote - " + ", ".join(pieces + [country]), "country": country}
    return {"location": ", ".join(pieces + [country]), "country": country}


def repair_stored_workday_entries(entries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Today's Workday rules applied to entries stored by an older ingestion (backfill; the adapter does the same for new data).

    The label an entry was published under is ``raw_location``, else ``source_location``, else the stored label. A bare
    "Offsite"/"Home" entry is dropped. A rewrite is only made when the parsed country agrees with the country already stored
    for the entry (or none is stored), exactly as the adapter checks against Workday's own country.
    """
    repaired: List[Dict[str, str]] = []
    for entry in entries:
        raw = str(entry.get("raw_location") or entry.get("source_location") or entry.get("location") or "").strip()
        if not raw or is_home_word(raw):
            continue
        canonical = normalize_workday_location(raw)
        stored_country = canonical_country_name(entry.get("country"))
        if canonical and canonical["location"] != raw and stored_country in ("", "Unknown", canonical["country"]):
            repaired.append({"location": canonical["location"], "country": canonical["country"], "raw_location": raw})
        else:
            repaired.append({k: v for k, v in entry.items() if k != "source_location"} | {"location": raw})
    return repaired
