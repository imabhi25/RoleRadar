"""Canonical place labels shared by every source adapter.

A label that is exactly a well-known city, optionally followed by its own region and/or country, is rewritten to one
shape per country, so the same place reads the same wherever it was posted:

    Canada         "Toronto, Ontario, Canada"       from  Toronto | Toronto, ON | Toronto, ON, CA | Toronto, Canada
    United States  "San Francisco, CA, United States"  from  San Francisco | San Francisco, California | San Francisco, CA, USA

Nothing is guessed. Any extra word ("HQ", "Office", "Hybrid -", a second city) or any region/country that does not belong
to the city leaves the label exactly as published. The caller keeps the published label as ``raw_location``.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

US_STATES: Dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

CA_PROVINCES: Dict[str, str] = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories", "NU": "Nunavut",
    "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec", "SK": "Saskatchewan", "YT": "Yukon",
}

# Cities whose province is unambiguous enough to fill in. (Display name, province code.)
CA_CITY_PROVINCE: Dict[str, Tuple[str, str]] = {
    "toronto": ("Toronto", "ON"), "ottawa": ("Ottawa", "ON"), "mississauga": ("Mississauga", "ON"),
    "waterloo": ("Waterloo", "ON"), "kitchener": ("Kitchener", "ON"), "markham": ("Markham", "ON"),
    "brampton": ("Brampton", "ON"), "oakville": ("Oakville", "ON"), "burlington": ("Burlington", "ON"),
    "hamilton": ("Hamilton", "ON"), "guelph": ("Guelph", "ON"), "richmond hill": ("Richmond Hill", "ON"),
    "vancouver": ("Vancouver", "BC"), "burnaby": ("Burnaby", "BC"), "richmond": ("Richmond", "BC"),
    "montreal": ("Montreal", "QC"), "montréal": ("Montréal", "QC"), "quebec city": ("Quebec City", "QC"),
    "laval": ("Laval", "QC"), "calgary": ("Calgary", "AB"), "edmonton": ("Edmonton", "AB"),
    "winnipeg": ("Winnipeg", "MB"), "halifax": ("Halifax", "NS"), "saskatoon": ("Saskatoon", "SK"),
    "regina": ("Regina", "SK"),
}


# Well-known US metros. A bare "New York" is the city here for the same reason it is everywhere else in the product.
US_CITY_STATE: Dict[str, Tuple[str, str]] = {
    "san francisco": ("San Francisco", "CA"), "new york": ("New York", "NY"), "new york city": ("New York", "NY"),
    "seattle": ("Seattle", "WA"), "boston": ("Boston", "MA"), "austin": ("Austin", "TX"), "chicago": ("Chicago", "IL"),
    "los angeles": ("Los Angeles", "CA"), "atlanta": ("Atlanta", "GA"), "pittsburgh": ("Pittsburgh", "PA"),
    "palo alto": ("Palo Alto", "CA"), "mountain view": ("Mountain View", "CA"), "menlo park": ("Menlo Park", "CA"),
    "foster city": ("Foster City", "CA"), "sunnyvale": ("Sunnyvale", "CA"), "santa clara": ("Santa Clara", "CA"),
    "mclean": ("McLean", "VA"), "denver": ("Denver", "CO"),
}
# Canadian cities that share a name with a place elsewhere are only rewritten when the country is already known to be Canada.
_AMBIGUOUS_CA = {"richmond", "hamilton", "burlington", "waterloo", "regina", "london"}

_US_NAME_TO_CODE = {name.lower(): code for code, name in US_STATES.items()}
_CA_NAME_TO_CODE = {name.lower(): code for code, name in CA_PROVINCES.items()}
_CA_NAME_TO_CODE["québec"] = "QC"
_US_COUNTRY_ALIASES = {"us", "usa", "u.s.", "u.s.a.", "united states", "united states of america"}
_CA_COUNTRY_ALIASES = {"ca", "can", "canada"}


def canonical_place_label(label: str, country: Optional[str] = None) -> Optional[str]:
    """The canonical label for a plain city label, or None when the label is anything else (leave it as published)."""
    tokens = [t.strip() for t in (label or "").split(",")]
    if not 1 <= len(tokens) <= 3 or not all(tokens):
        return None
    city_key = tokens[0].lower()
    if city_key in US_CITY_STATE:
        name, code = US_CITY_STATE[city_key]
        home = "United States"
        region_codes, region_names, country_aliases = {code}, {US_STATES[code].lower()}, _US_COUNTRY_ALIASES
    elif city_key in CA_CITY_PROVINCE:
        name, code = CA_CITY_PROVINCE[city_key]
        home = "Canada"
        if city_key in _AMBIGUOUS_CA and country != "Canada":
            return None
        region_codes, region_names, country_aliases = {code}, {CA_PROVINCES[code].lower()}, _CA_COUNTRY_ALIASES
        if city_key == "montréal":
            name = "Montréal"
    else:
        return None
    if country not in (None, "", "Unknown", home):
        return None
    saw_region = saw_country = False
    for token in tokens[1:]:
        low = token.lower().rstrip(".")
        if not saw_region and not saw_country and (low.upper() in region_codes or low in region_names):
            saw_region = True
        elif not saw_country and low in country_aliases:
            saw_country = True
        else:
            return None
    if home == "Canada":
        return f"{name}, {CA_PROVINCES[code]}, Canada"
    return f"{name}, {code}, United States"


# ----------------------------------------------------------------------------------------------------------------------
# Does a pay qualifier ("for candidates based in the United States", "in the Toronto area") describe this job's locations?
# ----------------------------------------------------------------------------------------------------------------------
_COUNTRY_WORDS = {
    "united states of america": "United States", "united states": "United States", "u.s.a.": "United States", "u.s.": "United States",
    "usa": "United States", "us": "United States", "american": "United States",
    "canada": "Canada", "canadian": "Canada",
}
_US_ONLY_REGION_WORDS = {"bay area": ("city", "san francisco"), "greater toronto": ("city", "toronto"), "gta": ("city", "toronto"),
                         "nyc": ("city", "new york"), "new york city": ("city", "new york"), "d.c.": ("state", "DC"), "washington d.c.": ("state", "DC"),
                         "washington dc": ("state", "DC"), "district of columbia": ("state", "DC")}
_CITY_KEYS = sorted(set(US_CITY_STATE) | set(CA_CITY_PROVINCE) | {"vancouver", "montreal"}, key=len, reverse=True)
_STATE_NAMES = sorted(({n.lower(): c for c, n in US_STATES.items()} | {n.lower(): c for c, n in CA_PROVINCES.items()}).items(), key=lambda kv: -len(kv[0]))


def place_tokens(text: str) -> set:
    """Known places named in a text, as (kind, name) pairs: country, state/province code, city. Unknown words are ignored."""
    low = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    found: set = set()
    for word, canon in _US_ONLY_REGION_WORDS.items():
        if re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", low):
            found.add(canon)
            low = low.replace(word, " ")
    for word, country in _COUNTRY_WORDS.items():
        if re.search(rf"(?<![\w.]){re.escape(word)}(?![\w])", low):
            found.add(("country", country))
    for name, code in _STATE_NAMES:
        if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", low) and not (name == "washington" and ("washington d" in low or "district of columbia" in low)):
            found.add(("state", code))
    for key in _CITY_KEYS:
        if re.search(rf"(?<![\w]){re.escape(key)}(?![\w])", low):
            found.add(("city", US_CITY_STATE[key][0].lower() if key in US_CITY_STATE else CA_CITY_PROVINCE.get(key, (key.title(), ""))[0].lower()))
    # "City, ST" postal codes: only after a comma, so "CA" in "Canada, CA" or "in CA" prose is not mistaken for a state.
    for code in re.findall(r",\s*([A-Z]{2})\b", text or ""):
        if code in US_STATES or code in CA_PROVINCES:
            found.add(("state", code))
    return found


def _with_implied(tokens: set) -> set:
    implied = set(tokens)
    for kind, name in tokens:
        if kind == "city":
            for table in (US_CITY_STATE, CA_CITY_PROVINCE):
                for key, (display, code) in table.items():
                    if display.lower() == name:
                        implied.add(("state", code))
                        implied.add(("country", "United States" if table is US_CITY_STATE else "Canada"))
        if kind == "state":
            implied.add(("country", "Canada" if name in CA_PROVINCES else "United States"))
    return implied


def qualifier_scope(qualifier: Optional[str], locations: List[Dict[str, str]]) -> Optional[str]:
    """How far a place-qualifier reaches over a job's locations: 'all', 'some', 'none', or 'unclear' (the qualifier names no
    known place, so nothing can be said). None when there is no qualifier. Nothing about where the job may be worked from is guessed:
    this only compares the words the employer wrote with the labels the job carries."""
    if not qualifier:
        return None
    wanted = place_tokens(qualifier)
    if not wanted:
        return "unclear"
    # A qualifier that names only a country matches any location in that country; a city or state must be named by the location.
    matches = []
    for entry in locations or []:
        label = str(entry.get("location") or "")
        have = _with_implied(place_tokens(label) | ({("country", entry["country"])} if entry.get("country") in ("United States", "Canada") else set()))
        specific = {t for t in wanted if t[0] != "country"}
        if specific:
            # A qualifier naming a place must match a place the location names (a country alone is not enough).
            matches.append(bool(specific & have) and not any(t[0] == "country" and t not in have for t in wanted))
        else:
            matches.append(bool(wanted & have))
    if not matches:
        return "unclear"
    return "all" if all(matches) else "some" if any(matches) else "none"
