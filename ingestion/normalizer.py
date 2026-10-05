"""
Normalization utilities for RoleRadar.
Provides pure, deterministic functions for SWE role filtering, workplace classification,
and location/country resolution.
"""

from pathlib import Path
import re
import sys
from typing import Dict, Optional, Set, Tuple
import urllib.parse

# Ensure project root is in sys.path to safely import Phase 1 constants/helpers
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import BROAD_REGIONS, CANONICAL_COUNTRY_NAMES, normalize_country
from ingestion.places import canonical_place_label

# 50 US State 2-letter postal abbreviations + DC for resolving US locations
US_STATE_CODES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
    "dc",
}

US_SYNONYMS = {"us", "usa", "u.s.", "u.s.a.", "united states"}
UK_SYNONYMS = {"uk", "u.k.", "united kingdom"}

US_STATE_NAMES: Set[str] = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
}

# Canadian provinces (10) and territories (3)
CANADIAN_PROVINCE_CODES: Set[str] = {
    "ab", "bc", "mb", "nb", "nl", "ns", "nt", "nu", "on", "pe", "qc", "sk", "yt",
}

CANADIAN_PROVINCE_NAMES: Set[str] = {
    "alberta", "british columbia", "manitoba", "new brunswick",
    "newfoundland and labrador", "newfoundland", "northwest territories",
    "nova scotia", "nunavut", "ontario", "prince edward island",
    "quebec", "québec", "saskatchewan", "yukon",
}

# UK Regions and constituent nations
UK_REGIONS: Set[str] = {
    "england", "scotland", "wales", "northern ireland", "uk", "u.k.",
    "united kingdom", "great britain",
}

# Curated bare cities mapping directly to their sovereign countries (Phase 6C.2)
CURATED_CITIES: Dict[str, str] = {
    # United States
    "san francisco": "United States",
    "new york": "United States",
    "new york city": "United States",
    "nyc": "United States",
    "seattle": "United States",
    "boston": "United States",
    "austin": "United States",
    "chicago": "United States",
    "los angeles": "United States",
    "palo alto": "United States",
    "mountain view": "United States",
    "menlo park": "United States",
    "foster city": "United States",
    "atlanta": "United States",
    "pittsburgh": "United States",
    "mclean": "United States",

    # Canada
    "toronto": "Canada",
    "vancouver": "Canada",
    "montreal": "Canada",
    "montréal": "Canada",
    "calgary": "Canada",
    "ottawa": "Canada",
    "waterloo": "Canada",
    "kitchener": "Canada",
    "mississauga": "Canada",

    # United Kingdom
    "london": "United Kingdom",
    "cardiff": "United Kingdom",
    "manchester": "United Kingdom",
    "edinburgh": "United Kingdom",
    "bristol": "United Kingdom",
    "cambridge": "United Kingdom",
    "oxford": "United Kingdom",
}

CANADIAN_CURATED_CITIES: Set[str] = {
    city.lower() for city, country in CURATED_CITIES.items() if country == "Canada"
}


def has_canadian_context(text: Optional[str]) -> bool:
    """
    Evaluates whether a text string contains high-confidence Canadian geographic context:
    - Canadian province abbreviations occurring as actual location segments (e.g. 'Toronto, ON', 'Vancouver, BC')
    - Full Canadian province names (e.g. 'Ontario', 'British Columbia')
    - Canadian curated cities (e.g. 'Toronto', 'Vancouver', 'Montreal')
    - Literal 'canada'

    Do NOT treat ordinary prose containing 'on', 'ab', or 'bc' (e.g. 'Remote on site',
    'Working on platform', 'Engineering on infrastructure') as Canadian province evidence.
    """
    if not text:
        return False
    t_low = text.lower()

    # 1. Structural Canadian province code matching on delimited geographic segments
    # Segment delimiters: commas, semicolons, slashes, pipes, parentheses, or spaced hyphens/dashes
    segments = [s.strip(" ()[]-–—/:,|").lower() for s in re.split(r"[,;/\(\)|]|\s+[-–—]\s+", text) if s.strip()]
    for seg in segments:
        if seg in CANADIAN_PROVINCE_CODES:
            return True
        # Handle province code followed by postal code or extra details, e.g. "ON M5V 2T6" or "ON M5V"
        m = re.match(r"^([a-z]{2})\s+[a-z]\d", seg)
        if m and m.group(1) in CANADIAN_PROVINCE_CODES:
            return True

    # 2. Full Canadian province names (safe with word boundary matching)
    for prov in CANADIAN_PROVINCE_NAMES:
        if re.search(r"\b" + re.escape(prov) + r"\b", t_low):
            return True

    # 3. Curated Canadian cities (safe with word boundary matching)
    for city in CANADIAN_CURATED_CITIES:
        if re.search(r"\b" + re.escape(city) + r"\b", t_low):
            return True

    # 4. Literal 'canada'
    if re.search(r"\bcanada\b", t_low):
        return True

    return False

# Generic location suffixes (e.g. "San Francisco Office", "London HQ")
GENERIC_LOCATION_SUFFIXES = re.compile(
    r"\s+(?:office|hq|headquarters|campus|site)\b",
    re.IGNORECASE,
)

# User-facing eligible countries for RoleRadar feed and analytics
ELIGIBLE_COUNTRIES: Tuple[str, ...] = ("United States", "Canada")

NON_CITY_LOCATION_TERMS: Set[str] = {
    "remote", "remote job", "remote work", "hybrid", "onsite", "on-site",
    "in-office", "unspecified", "unknown", "anywhere", "worldwide", "global",
    "europe", "emea", "apac", "latam", "americas", "north america",
    "timezones", "usa timezones", "us timezones",
}

# Canonical mapping of recognized sovereign countries and their aliases
KNOWN_COUNTRIES: Dict[str, str] = {
    # United States
    "united states": "United States",
    "united states of america": "United States",
    "usa": "United States",
    "us": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
    # United Kingdom
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "northern ireland": "United Kingdom",
    # Canada
    "canada": "Canada",
    # Germany
    "germany": "Germany",
    "deutschland": "Germany",
    "federal republic of germany": "Germany",
    # France
    "france": "France",
    # Other recognized countries
    "australia": "Australia",
    "israel": "Israel",
    "peru": "Peru",
    "netherlands": "Netherlands",
    "spain": "Spain",
    "italy": "Italy",
    "switzerland": "Switzerland",
    "austria": "Austria",
    "sweden": "Sweden",
    "poland": "Poland",
    "ireland": "Ireland",
    "belgium": "Belgium",
    "portugal": "Portugal",
    "denmark": "Denmark",
    "norway": "Norway",
    "finland": "Finland",
    "czech republic": "Czech Republic",
    "czechia": "Czech Republic",
    "romania": "Romania",
    "estonia": "Estonia",
    "ukraine": "Ukraine",
    "singapore": "Singapore",
    "japan": "Japan",
    "india": "India",
    "brazil": "Brazil",
    "mexico": "Mexico",
    "new zealand": "New Zealand",
    "south africa": "South Africa",
    "greece": "Greece",
    "hungary": "Hungary",
    "bulgaria": "Bulgaria",
    "croatia": "Croatia",
    "slovakia": "Slovakia",
    "lithuania": "Lithuania",
    "latvia": "Latvia",
    "luxembourg": "Luxembourg",
    "cyprus": "Cyprus",
    "malta": "Malta",
    "iceland": "Iceland",
    "argentina": "Argentina",
    "chile": "Chile",
    "colombia": "Colombia",
    "uruguay": "Uruguay",
    "philippines": "Philippines",
    "indonesia": "Indonesia",
    "malaysia": "Malaysia",
    "vietnam": "Vietnam",
    "taiwan": "Taiwan",
    "south korea": "South Korea",
    "korea": "South Korea",
    "turkey": "Turkey",
    "türkiye": "Turkey",
    "united arab emirates": "United Arab Emirates",
    "uae": "United Arab Emirates",
    "egypt": "Egypt",
    "nigeria": "Nigeria",
    "kenya": "Kenya",
}

NON_COUNTRY_TERMS: Set[str] = BROAD_REGIONS | {
    "anywhere",
    "remote",
    "remote job",
    "remote work",
    "work from anywhere",
    "wfh",
    "hybrid",
    "onsite",
    "on-site",
    "in-office",
    "office",
    "unspecified",
    "unknown",
    "worldwide",
    "global",
    "international",
}

# Obvious non-SWE role patterns to exclude immediately
EXCLUDED_ROLE_PATTERNS = [
    re.compile(r"\b(?:sales|account\s+executive|business\s+development|bdr|sdr)\b", re.IGNORECASE),
    re.compile(r"\b(?:recruiter|recruiting|talent\s+acquisition|sourcer)\b", re.IGNORECASE),
    re.compile(r"\b(?:accountant|accounting|finance|payroll|tax|controller)\b", re.IGNORECASE),
    re.compile(r"\b(?:product|project|program)\s+manager\b|\b[tp]pm\b", re.IGNORECASE),
    re.compile(r"\b(?:account\s+manager|technical\s+account\s+manager|tam)\b", re.IGNORECASE),
    re.compile(r"\b(?:design\s+engineer)\b", re.IGNORECASE),
    re.compile(r"\b(?:solutions?\s+engineer)\b", re.IGNORECASE),
    re.compile(r"\b(?:sales\s+engineer)\b", re.IGNORECASE),
    re.compile(r"\b(?:support\s+engineer|technical\s+support\s+engineer|customer\s+support\s+engineer)\b", re.IGNORECASE),
    re.compile(r"\b(?:customer\s+support|customer\s+success|technical\s+support|help\s+desk|tier\s+[123])\b", re.IGNORECASE),
    re.compile(r"\b(?:marketing|copywriter|content\s+writer|seo|social\s+media)\b", re.IGNORECASE),
    re.compile(r"\b(?:legal|counsel|attorney|paralegal|compliance\s+officer)\b", re.IGNORECASE),
    re.compile(r"\b(?:operations\s+manager|office\s+manager|administrative|receptionist)\b", re.IGNORECASE),
    re.compile(r"\b(?:business\s+systems|support\s+systems|enterprise\s+systems|corporate\s+systems|financial\s+systems)\b", re.IGNORECASE),
    # Standalone designer roles (exclude unless combined with engineer/developer)
    re.compile(r"\b(?:graphic\s+designer|product\s+designer|ux\s+designer|ui\s+designer|visual\s+designer)\b", re.IGNORECASE),
]

# Positive indicators for Software Engineering & Technical roles
SWE_ROLE_PATTERNS = [
    # Standalone common SWE acronyms (e.g. "Senior SWE", "SRE", "Staff MLE", "DevOps", "MLOps")
    re.compile(r"\b(?:swe|sre|mle|devops|mlops)\b", re.IGNORECASE),
    # General software engineering & development
    re.compile(r"\b(?:software\s+engineer(?:ing)?|software\s+developer)\b", re.IGNORECASE),
    # Core specializations (allows intervening keywords like "Frontend UI/UX Engineer")
    re.compile(r"\b(?:backend|front[\s\-]?end|full[\s\-]?stack)\b.*\b(?:engineer|developer|architect|lead)\b", re.IGNORECASE),
    # Product engineering (e.g. "Product Engineer", "Senior / Staff Product Engineer", "Product Engineer, AI")
    re.compile(r"\bproduct\s+(?:software\s+)?(?:engineer|developer)\b", re.IGNORECASE),
    # Infrastructure, SRE, DevOps, Platform, Cloud
    re.compile(r"\b(?:site\s+reliability|platform|infrastructure|cloud|systems)\s+(?:engineer|architect|lead)\b", re.IGNORECASE),
    # Data & ML/AI / Analytics / Research
    re.compile(r"\b(?:data|machine\s+learning|ml|ai|artificial\s+intelligence|analytics|research)\s+(?:engineer|scientist|architect)\b", re.IGNORECASE),
    re.compile(r"\bapplied\s+(?:ai|machine\s+learning|ml)\s+(?:engineer|scientist|architect|researcher)\b", re.IGNORECASE),
    re.compile(r"\b(?:data|ml|ai)\s+platform\s+engineer\b", re.IGNORECASE),
    # Mobile & Embedded
    re.compile(r"\b(?:mobile|ios|android|embedded|firmware)\s+(?:engineer|developer|architect)\b", re.IGNORECASE),
    # Systems & Distributed Systems
    re.compile(r"\b(?:distributed\s+systems|kernel|compiler)\s+(?:engineer|developer)\b", re.IGNORECASE),
    # Early career technical roles (Intern, Co-op, New Grad, Entry-Level)
    re.compile(r"\b(?:swe|software\s+engineer(?:ing)?|software\s+developer|developer)\s+(?:intern(?:ship)?|co[\s\-]op)\b", re.IGNORECASE),
    re.compile(r"\b(?:new\s+grad(?:uate)?|graduate|entry[\s\-]level|early\s+career)\s+(?:swe|software\s+engineer(?:ing)?|software\s+developer|developer)\b", re.IGNORECASE),
    re.compile(r"\b(?:co[\s\-]op|intern)\s+(?:software\s+engineer(?:ing)?|developer|swe)\b", re.IGNORECASE),
    re.compile(r"\bsoftware\s+(?:intern(?:ship)?|co[\s\-]?op)\b", re.IGNORECASE),
    # Amazon-style titles ("Software Development Engineer", "SDE", "SDET")
    re.compile(r"\b(?:software|systems?)\s+dev(?:elopment)?\s+(?:engineer|intern(?:ship)?|co[\s\-]?op)\b|\b(?:sde|sdet)\b", re.IGNORECASE),
    # Student wording that names software/development explicitly (Student Developer, Developer Student, ...)
    re.compile(r"\bstudent\b.*\b(?:software|developer|programmer)\b|\b(?:software|developer|programmer)\b.*\bstudent\b", re.IGNORECASE),
    # Bank/enterprise developer titles (Application Developer, API Engineer, ...)
    re.compile(r"\b(?:application|applications|api|integration|mainframe|\.net|etl|salesforce)\s+(?:engineer|developer|architect)\b", re.IGNORECASE),
    # General fallback for tech roles ending in engineer/developer (including language-specific roles)
    re.compile(r"\b(?:cloud|infra|security|qa|test|automation|database|web|python|java|javascript|typescript|golang|go|rust|c\+\+|ruby|php|node)\s+(?:engineer|developer|architect)\b", re.IGNORECASE),
]


STUDENT_ENGINEER_REGEX = re.compile(r"\b(?:engineering\s+student|student\s+engineer(?:ing)?)\b", re.IGNORECASE)
TECHNICAL_PROGRAM_REGEX = re.compile(
    r"\b(?:intern(?:ship)?|graduate)\s+program\b.*\b(?:technology|networks|software|ai|data\s+solutions)\b",
    re.IGNORECASE,
)
_SOFTWARE_EVIDENCE_TERMS = (
    "software", "programming", "coding", "python", "java", "javascript", "typescript",
    "c++", "algorithms", "data structures", "backend", "back-end", "frontend", "front-end",
    "full-stack", "full stack", "web development", "apis", "git",
)


def has_software_evidence(description: Optional[str], minimum: int = 3) -> bool:
    """True when a description names at least `minimum` distinct software/programming terms."""
    if not description:
        return False
    low = description.lower()
    hits = sum(1 for term in _SOFTWARE_EVIDENCE_TERMS if re.search(r"(?<![\w])" + re.escape(term) + r"(?![\w])", low))
    return hits >= minimum


def is_swe_role(title: Optional[str], description: Optional[str] = None) -> bool:
    """
    Evaluates whether a job title belongs to a Software Engineering / Technical discipline.
    High-confidence positive engineering signals (e.g. 'Software Engineer', 'Backend Developer')
    take precedence over domain/department keywords (e.g. 'Finance', 'Legal').
    Conservative: returns False for ambiguous or non-engineering roles.
    """
    if not title or not title.strip():
        return False

    cleaned_title = title.strip()

    # If title explicitly mentions designer without engineer, exclude
    if re.search(r"\bdesigner\b", cleaned_title, re.IGNORECASE) and not re.search(r"\b(?:engineer|developer)\b", cleaned_title, re.IGNORECASE):
        return False

    # Domain words can describe engineering teams, but occupational exclusions
    # (recruiter, counsel, support, sales, business systems) still take priority.
    domain_only = re.compile(r"\b(?:finance|payroll|tax|accounting|legal)\b", re.I)
    occupational_title = domain_only.sub("", cleaned_title)
    if any(pattern.search(occupational_title) for pattern in EXCLUDED_ROLE_PATTERNS):
        return False
    if any(pattern.search(cleaned_title) for pattern in SWE_ROLE_PATTERNS):
        return True
    # "Engineering Student" alone is ambiguous (mechanical? civil?): require strong
    # software evidence from the description before accepting it.
    if description and (STUDENT_ENGINEER_REGEX.search(cleaned_title) or TECHNICAL_PROGRAM_REGEX.search(cleaned_title)):
        return has_software_evidence(description)
    return False


def classify_workplace(
    location_text: Optional[str] = None,
    workplace_type_raw: Optional[str] = None,
    is_remote: Optional[bool] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """
    Classifies the workplace type into strictly one of:
    'onsite', 'remote', 'hybrid', or 'unspecified'.

    Order of precedence:
    1. Provider structured workplace fields (workplace_type_raw, is_remote)
    2. Explicit clues in location and title
    3. Explicit workplace statements in description (e.g. 'Workplace: Remote', 'Role is 100% remote')
    4. Fallback: 'unspecified' (never guesses from city alone).
    """
    # 1. Explicit structured ATS workplace classification first
    raw_clean = workplace_type_raw.lower().strip() if workplace_type_raw else ""
    if raw_clean:
        if "hybrid" in raw_clean:
            return "hybrid"
        if any(term in raw_clean for term in ["remote", "work from home", "wfh", "telecommute", "virtual"]):
            return "remote"
        if any(term in raw_clean for term in ["onsite", "on-site", "in-office", "in office", "office"]):
            return "onsite"

    # Structured provider is_remote flag (when workplace_type_raw is absent or ambiguous)
    if is_remote is True:
        return "remote"

    # 2. Explicit clues in location and title
    tokens = []
    if location_text:
        tokens.append(location_text.lower().strip())
    if title:
        tokens.append(title.lower().strip())

    combined_loc_title = " ".join(tokens)

    # Check for hybrid first (takes priority over remote mentions in hybrid context like 'hybrid remote/onsite')
    if re.search(r"\bhybrid\b", combined_loc_title):
        return "hybrid"

    # Check for explicit remote in location or title
    if re.search(r"\b(?:remote|work\s+from\s+home|wfh|telecommute|virtual)\b", combined_loc_title):
        return "remote"

    # Check for explicit onsite / in-office in location or title
    if re.search(r"\b(?:onsite|on-site|in-office|in\s+office)\b", combined_loc_title):
        return "onsite"

    # 3. Explicit high-confidence description clues
    if description:
        desc_lower = description.lower()
        m_hybrid = re.search(r"\b(?:workplace(?:\s+type)?|work\s+model|work(?:ing)?\s+arrangement):?\s*hybrid\b", desc_lower)
        if m_hybrid or re.search(
            r"\b(?:hybrid\s+work\s+model|hybrid\s+schedule|hybrid\s+model:\s*\d|"
            r"this\s+(?:is\s+a\s+)?hybrid\s+(?:position|role|job|opportunity)|for\s+this\s+hybrid\s+(?:position|role|job)|"
            r"this\s+(?:position|role|job)\s+is\s+hybrid|"
            r"(?:operates|operate|work|works|working)\s+(?:in\s+)?a\s+hybrid\s+(?:work\s+)?(?:style|model|environment|arrangement|schedule)|"
            r"(?:[1-4]|one|two|three|four)\s+days?\s+(?:per|a|each)\s+week\s+in(?:\s+the)?\s+office)\b",
            desc_lower,
        ):
            return "hybrid"

        m_remote = re.search(r"\b(?:workplace(?:\s+type)?|work\s+model|work(?:ing)?\s+arrangement):?\s*remote\b", desc_lower)
        if m_remote or re.search(r"\b(?:100%\s+remote|fully\s+remote|position\s+is\s+(?:100%\s+)?remote|this\s+is\s+a\s+remote\s+(?:position|role|job))\b", desc_lower):
            return "remote"

        m_onsite = re.search(r"\b(?:workplace(?:\s+type)?|work\s+model|work(?:ing)?\s+arrangement):?\s*(?:onsite|on-site|in-office)\b", desc_lower)
        if m_onsite or re.search(
            r"\b(?:100%\s+on[\s\-]site|fully\s+on[\s\-]site|this\s+is\s+an\s+on[\s\-]site\s+(?:position|role)|"
            r"(?:work|working)\s+(?:full[\s\-]time,?\s+)?on[\s\-]site\s+(?:five|5)\s+days|"
            r"expect\s+to\s+work\s+(?:in[\s\-]office|on[\s\-]site),?\s+(?:monday|five\s+days|5\s+days))\b",
            desc_lower,
        ):
            return "onsite"

        # Recruiter-applied ATS tags (#LI-Hybrid, #LI-Remote, #LI-Onsite) describe this role, but only when they agree:
        # a posting carrying several different ones is open to more than one arrangement and stays unspecified.
        tagged = {
            {"onsite": "onsite", "on-site": "onsite"}.get(tag, tag)
            for tag in re.findall(r"#li-(hybrid|remote|onsite|on-site)\b", desc_lower)
        }
        if len(tagged) == 1:
            return next(iter(tagged))

    # 4. Fallback: information is absent or ambiguous (never guess from city alone)
    return "unspecified"


def resolve_token_country(token: str, context: Optional[str] = None) -> Optional[str]:
    """
    Attempts to resolve a single geographic token (country, state, province, UK region,
    or curated bare city) to its sovereign country.
    Disambiguates 'ca' based on optional surrounding context (Canadian cities/provinces -> Canada,
    otherwise California -> United States).
    Returns canonical country name if recognized, else None.
    """
    if not token or not isinstance(token, str):
        return None
    tok = token.strip().lower()
    tok_stripped = re.sub(r"\s+(?:office|hq|headquarters|campus|site)\b", "", tok, flags=re.IGNORECASE).strip()

    # Disambiguate 'ca': ISO-3166 Canada vs US California postal abbreviation
    if tok == "ca" or tok_stripped == "ca":
        if context and has_canadian_context(context):
            return "Canada"
        return "United States"

    if tok in KNOWN_COUNTRIES:
        return KNOWN_COUNTRIES[tok]
    if tok_stripped in KNOWN_COUNTRIES:
        return KNOWN_COUNTRIES[tok_stripped]
    if tok in US_STATE_CODES or tok in US_STATE_NAMES or tok_stripped in US_STATE_NAMES:
        return "United States"
    if tok in CANADIAN_PROVINCE_CODES or tok in CANADIAN_PROVINCE_NAMES or tok_stripped in CANADIAN_PROVINCE_NAMES:
        return "Canada"
    if tok in UK_REGIONS or tok_stripped in UK_REGIONS:
        return "United Kingdom"
    if tok in CURATED_CITIES:
        return CURATED_CITIES[tok]
    if tok_stripped in CURATED_CITIES:
        return CURATED_CITIES[tok_stripped]
    return None


def normalize_location_and_country(raw_location: Optional[str]) -> Tuple[str, str]:
    """
    Extracts and normalizes the display location and country from a raw location string.
    Strictly verifies sovereign countries and recognizes curated bare cities, US states,
    Canadian provinces, and UK regions.
    
    Returns (normalized_location, normalized_country).
    """
    if not raw_location or not raw_location.strip():
        return ("Unknown", "Unknown")

    cleaned = raw_location.strip()
    lower = cleaned.lower()

    # 1. Handle broad / non-country terms
    if lower in NON_COUNTRY_TERMS:
        if lower in ("remote", "remote job", "remote work"):
            return ("Remote", "Unknown")
        if lower == "hybrid":
            return ("Hybrid", "Unknown")
        if lower in ("onsite", "on-site", "in-office"):
            return ("Onsite", "Unknown")
        return (cleaned, "Unknown")

    # 2. Single-token exact country match
    if lower in KNOWN_COUNTRIES:
        c = KNOWN_COUNTRIES[lower]
        return (c, c)

    # 3. Explicit Germany country signals (e.g. "Munich (DE)", "Home Office Deutschland")
    if re.search(r"\(\s*de\s*\)", cleaned, re.IGNORECASE) or re.search(r"\bdeutschland\b", cleaned, re.IGNORECASE):
        return (cleaned, "Germany")

    # 4. Curated bare city match on whole string (with or without generic suffix like Office/HQ)
    # e.g. "San Francisco", "San Francisco Office", "Toronto", "Toronto Office", "London", "London HQ"
    city_candidate = re.sub(r"\s+(?:office|hq|headquarters|campus|site)\b", "", lower, flags=re.IGNORECASE).strip()
    if city_candidate in CURATED_CITIES:
        return (cleaned, CURATED_CITIES[city_candidate])

    # 5. Pure remote strings without specific cities
    # (Matches only when location is solely remote + country/region, e.g. "Remote - US", "Canada Remote")
    trailing_remote_match = re.match(r"^(.*?)\s+remote$", cleaned, re.IGNORECASE)
    if trailing_remote_match:
        base = trailing_remote_match.group(1).strip()
        base_low = base.lower()
        if base_low in NON_COUNTRY_TERMS:
            return (base, "Unknown")
        if base_low in KNOWN_COUNTRIES:
            c = KNOWN_COUNTRIES[base_low]
            return (c, c)
        c_base = resolve_token_country(base)
        if c_base:
            return ("Remote", c_base)

    leading_remote_match = re.match(r"^remote\s+(.+)$", cleaned, re.IGNORECASE)
    if leading_remote_match:
        base = leading_remote_match.group(1).strip()
        base_low = base.lower()
        if base_low in NON_COUNTRY_TERMS:
            return (cleaned, "Unknown")
        if base_low in KNOWN_COUNTRIES:
            c = KNOWN_COUNTRIES[base_low]
            return ("Remote", c)
        c_base = resolve_token_country(base)
        if c_base:
            return ("Remote", c_base)

    # Pure remote with separator e.g. "Remote: United States", "Remote - US", "Remote (Canada)", "U.S. Remote"
    pure_remote_match = re.match(
        r"^(?:remote\s*[-–—(/:]\s*([a-zA-Z\s.]+)\)?|(?:u\.s\.|us|canada|uk|u\.k\.|united kingdom|united states)\s*[-–—(]\s*remote\)?)$",
        cleaned,
        re.IGNORECASE,
    )
    if pure_remote_match:
        reg_token = pure_remote_match.group(1)
        if reg_token:
            reg_lower = reg_token.strip().lower()
            if reg_lower in NON_COUNTRY_TERMS:
                return (cleaned, "Unknown")
            c_reg = resolve_token_country(reg_lower)
            if c_reg:
                return ("Remote", c_reg)
        for syn in US_SYNONYMS:
            if syn in lower:
                return ("Remote", "United States")
        if "canada" in lower:
            return ("Remote", "Canada")
        for syn in UK_SYNONYMS:
            if syn in lower:
                return ("Remote", "United Kingdom")

    # 6. Specific city + remote or multi-location strings
    # Check comma / semicolon separated parts
    parts = [p.strip() for p in re.split(r"[,;]", cleaned) if p.strip()]
    if parts:
        # Check redundant country synonyms (e.g. "USA, United States")
        if len(parts) >= 2:
            if all(p.lower() in KNOWN_COUNTRIES and KNOWN_COUNTRIES[p.lower()] == KNOWN_COUNTRIES[parts[0].lower()] for p in parts):
                canon = KNOWN_COUNTRIES[parts[0].lower()]
                return (canon, canon)
            if len(parts) >= 3 and parts[-1].lower() in KNOWN_COUNTRIES and parts[-2].lower() in KNOWN_COUNTRIES:
                if KNOWN_COUNTRIES[parts[-1].lower()] == KNOWN_COUNTRIES[parts[-2].lower()]:
                    parts = parts[:-1]
                    cleaned = ", ".join(parts)

        # Check last segment with preceding context
        c_last = resolve_token_country(parts[-1], context=", ".join(parts[:-1]))
        if c_last:
            return (cleaned, c_last)

        # Check second-to-last segment if last is postal code or extra detail
        if len(parts) >= 2:
            c_second = resolve_token_country(parts[-2], context=", ".join(parts[:-2]))
            if c_second:
                return (cleaned, c_second)

        # Check first segment if it contains a curated city
        c_first = resolve_token_country(parts[0], context=", ".join(parts[1:]))
        if c_first and len(parts) >= 2:
            return (cleaned, c_first)

    # 7. Check slash, pipe, or "or" separated multi-locations (e.g. "Cardiff, London or Remote (UK)", "Los Angeles, CA or Remote (United States)")
    alt_parts = [p.strip() for p in re.split(r"[/|]|\bor\b", cleaned, flags=re.IGNORECASE) if p.strip()]
    if len(alt_parts) > 1:
        for ap in alt_parts:
            sub_parts = [sp.strip() for sp in re.split(r"[,;]", ap) if sp.strip()]
            if sub_parts:
                c_sub = (
                    resolve_token_country(sub_parts[-1], context=", ".join(sub_parts[:-1]))
                    or (resolve_token_country(sub_parts[-2], context=", ".join(sub_parts[:-2])) if len(sub_parts) >= 2 else None)
                    or resolve_token_country(sub_parts[0], context=", ".join(sub_parts[1:]))
                )
                if c_sub:
                    return (cleaned, c_sub)

    # 8. Check if entire string mentions country / state / curated city in complex phrases
    if any(re.search(r"\b" + re.escape(uk_term) + r"\b", lower) for uk_term in ["uk", "u.k.", "united kingdom", "great britain", "england", "scotland", "wales"]):
        return (cleaned, "United Kingdom")

    # Specific curated cities take precedence over generic country mentions
    for city, mapped_country in CURATED_CITIES.items():
        if re.search(r"\b" + re.escape(city) + r"\b", lower):
            return (cleaned, mapped_country)

    if has_canadian_context(lower):
        return (cleaned, "Canada")

    if any(re.search(r"\b" + re.escape(us_term) + r"\b", lower) for us_term in ["united states", "usa", "u.s.a."]):
        return (cleaned, "United States")

    if re.search(r"\bcanada\b", lower):
        return (cleaned, "Canada")

    for country_token, canonical in KNOWN_COUNTRIES.items():
        if re.search(r"\b" + re.escape(country_token) + r"$", lower):
            return (cleaned, canonical)

    return (cleaned, "Unknown")


VALID_ROLE_TYPES = {"internship", "co_op", "new_grad", "entry_level", "full_time", "unknown"}
EARLY_CAREER_ROLE_TYPES = ("internship", "co_op", "new_grad", "entry_level")

CO_OP_REGEX = re.compile(
    r"\b(?:co[\s\-]?op|cooperative\s+education)\b",
    re.IGNORECASE,
)

INTERNSHIP_REGEX = re.compile(
    r"\b(?:intern(?:ship)?s?|trainee)\b",
    re.IGNORECASE,
)

# Student roles (Student Developer, Student, Software Engineering, Engineering Student, ...)
STUDENT_ROLE_REGEX = re.compile(
    r"\bstudent\b.*\b(?:developer|engineer(?:ing)?|software|programmer)\b"
    r"|\b(?:developer|engineer(?:ing)?|software|programmer)\b.*\bstudent\b",
    re.IGNORECASE,
)

NEW_GRAD_REGEX = re.compile(
    r"\b(?:new\s+grad(?:uate)?s?|recent\s+grad(?:uate)?s?|early\s+career|university\s+grad(?:uate)?s?|college\s+grad(?:uate)?s?|campus\s+hire|graduate\s+(?:software\s+)?(?:engineer|developer|associate|analyst|program))\b",
    re.IGNORECASE,
)

ENTRY_LEVEL_REGEX = re.compile(r"\b(?:entry[\s\-]level|junior)\b", re.IGNORECASE)

FULL_TIME_EXPLICIT_REGEX = re.compile(
    r"\b(?:senior|sr\.?|staff|principal|lead|head|architect|distinguished|director|manager)\b",
    re.IGNORECASE,
)


def classify_role_type(
    title: Optional[str],
    description: Optional[str] = None,
    raw_job_type: Optional[str] = None,
) -> str:
    """
    Classifies a job posting into one of:
    'internship', 'co_op', 'new_grad', 'entry_level', 'full_time', or 'unknown'.

    Evaluates primarily based on high-signal title evidence, using structured
    raw_job_type only when the title is silent. Description text is never used to
    promote a role to early-career (full-time postings routinely mention internships).
    """
    if not title or not title.strip():
        return "unknown"

    title_clean = title.strip()
    raw_jt_lower = raw_job_type.lower() if raw_job_type else ""

    # 1. Co-op (e.g. "Software Developer Co-op", "4 month co-op")
    if CO_OP_REGEX.search(title_clean):
        return "co_op"

    # 2. Internship / student roles. Word boundary prevents "internal", "international".
    if INTERNSHIP_REGEX.search(title_clean) or STUDENT_ROLE_REGEX.search(title_clean):
        return "internship"

    # 3. New grad / campus hire / early career
    if NEW_GRAD_REGEX.search(title_clean):
        return "new_grad"

    # 4. Entry level / junior
    if ENTRY_LEVEL_REGEX.search(title_clean):
        return "entry_level"

    # 5. Senior / Staff / Principal / Architect explicitly indicates full-time professional career role
    if FULL_TIME_EXPLICIT_REGEX.search(title_clean):
        return "full_time"

    # 6. Structured provider job type (e.g. Lever commitment "Intern", Jobicy "Full-Time")
    if raw_jt_lower:
        if re.search(r"\bco[\s\-]?op\b", raw_jt_lower):
            return "co_op"
        if re.search(r"\bintern(?:ship)?\b", raw_jt_lower):
            return "internship"
        if any(term in raw_jt_lower for term in ["full-time", "full time", "permanent"]):
            return "full_time"
        if any(term in raw_jt_lower for term in ["part-time", "part time", "contract", "freelance", "temporary"]):
            return "unknown"

    # 7. Standard SWE roles are regular full-time engineering positions.
    if is_swe_role(title_clean, description):
        return "full_time"

    return "unknown"


# =============================================================================
# Academic term extraction (Winter/Summer/Fall YYYY)
# =============================================================================

_SEASON_ALIASES = {"winter": "winter", "summer": "summer", "fall": "fall", "autumn": "fall", "spring": "spring"}
_SEASON_WORDS = r"(?:winter|summer|fall|autumn|spring)"
_TERM_SEASON_YEAR = re.compile(
    rf"\b({_SEASON_WORDS})\s*(?:(?:work\s+)?term|semester|intake|intern(?:ship)?|co[\s\-]?op|student)?\s*[,\-–—]?\s*(?:['’](\d{{2}})\b|(20[2-4]\d)\b)",
    re.IGNORECASE,
)
_TERM_YEAR_SEASON = re.compile(rf"\b(20[2-4]\d)\s*[,\-–—]?\s*({_SEASON_WORDS})\b", re.IGNORECASE)
# "Fall/Winter 2027", "Summer & Fall 2027" name several terms: not one reliable term.
_TERM_COMBINED = re.compile(rf"\b{_SEASON_WORDS}\s*(?:/|&|,|and|or|-|–)\s*{_SEASON_WORDS}\b", re.IGNORECASE)
SUPPORTED_TERM_SEASONS = ("winter", "summer", "fall")


def _terms_in_text(text: str) -> Optional[Set[Tuple[str, int]]]:
    """All distinct (season, year) mentions in text; None if the text is ambiguous."""
    if not text:
        return set()
    if _TERM_COMBINED.search(text):
        return None
    found: Set[Tuple[str, int]] = set()
    for m in _TERM_SEASON_YEAR.finditer(text):
        year = int(m.group(3)) if m.group(3) else 2000 + int(m.group(2))
        found.add((_SEASON_ALIASES[m.group(1).lower()], year))
    for m in _TERM_YEAR_SEASON.finditer(text):
        found.add((_SEASON_ALIASES[m.group(2).lower()], int(m.group(1))))
    return found


def extract_academic_term(
    title: Optional[str],
    structured_terms: Optional[list] = None,
    description: Optional[str] = None,
    role_type: Optional[str] = None,
) -> Optional[Dict[str, object]]:
    """
    Extracts an explicit academic term such as {'season': 'summer', 'year': 2027, 'label': 'Summer 2027'}.

    Priority: structured ATS/source fields, then title, then (early-career roles only)
    description. A source is used only when it names exactly one term; conflicting or
    combined terms (e.g. 'Fall/Winter 2027') and unsupported seasons (spring) yield None.
    Never infers a season or year that the text does not state.
    """
    sources = []
    if structured_terms:
        sources.append(" | ".join(str(t) for t in structured_terms if t))
    sources.append(title or "")
    if description and role_type in ("internship", "co_op"):
        sources.append(description[:4000])

    for text in sources:
        terms = _terms_in_text(text)
        if terms is None:
            return None
        if len(terms) == 1:
            season, year = next(iter(terms))
            if season not in SUPPORTED_TERM_SEASONS:
                return None
            return {"season": season, "year": year, "label": f"{season.title()} {year}"}
        if len(terms) > 1:
            return None
    return None


def _location_patterns(country: str):
    """Shared Python/PostgreSQL patterns: explicit country/region or known city."""
    regions = (US_STATE_CODES | US_STATE_NAMES | US_SYNONYMS | {"united states of america", "d.c.", "district of columbia"}
               if country == "United States" else
               CANADIAN_PROVINCE_CODES | CANADIAN_PROVINCE_NAMES | {"canada"})
    alternatives = "(?:" + "|".join(re.escape(x) for x in sorted(regions)) + ")"
    cities = "(?:" + "|".join(re.escape(x) for x, c in CURATED_CITIES.items() if c == country) + ")"
    mode = r"(?:remote(?:\s+(?:job|work|in))?|hybrid|onsite|on-site|in-office)"
    sep = r"[\s()\[\],:/|–—-]*"
    return (
        rf"^{sep}(?:{mode}{sep})?{alternatives}(?:{sep}{mode})?{sep}$",
        rf"\b{cities}\b",
        rf"\b[A-Za-z][A-Za-z .'-]+,\s*{alternatives}(?=\W|$)",
    )


_LOCATION_REJECT = r"\b(?:unknown|unspecified|anywhere|worldwide|global|latam|apac|emea|europe|timezones|north america|americas)\b"


def is_user_facing_location_eligible(location: Optional[str], country: Optional[str] = None) -> bool:
    """Accept explicit US/Canada locations, including country-wide and remote.

    Country is job-location evidence, never inferred from the employer's address.
    Unknown/global locations remain ineligible. Uses the same rules as feed SQL.
    """
    if not location or not location.strip():
        return False
    location = location.strip()
    country = country or normalize_location_and_country(location)[1]
    if country not in ELIGIBLE_COUNTRIES or re.search(_LOCATION_REJECT, location, re.I):
        return False
    if location.lower() in {"remote", "remote job", "remote work"}:
        return True
    return any(re.search(pattern, location, re.I) for pattern in _location_patterns(country))


def get_user_facing_geography_sql_predicate(location_alias: str = "l") -> str:
    """SQL equivalent of is_user_facing_location_eligible."""
    def sql_pattern(pattern):
        return pattern.replace(r"\b", r"\y").replace("'", "''")
    clauses = []
    for country in ELIGIBLE_COUNTRIES:
        patterns = " OR ".join(
            f"{location_alias}.location ~* '{sql_pattern(p)}'" for p in _location_patterns(country)
        )
        clauses.append(f"({location_alias}.country = '{country}' AND ({patterns}))")
    return f"""(
        {location_alias}.country IN ('United States', 'Canada')
        AND {location_alias}.location IS NOT NULL
        AND {location_alias}.location !~* '{sql_pattern(_LOCATION_REJECT)}'
        AND (LOWER(TRIM({location_alias}.location)) IN ('remote', 'remote job', 'remote work')
             OR {" OR ".join(clauses)})
    )"""


# =============================================================================
# Job Application URL Classification & Priority Routing
# =============================================================================

def is_valid_http_url(url: Optional[str]) -> bool:
    """Checks if a string is a valid HTTP or HTTPS URL."""
    if not url or not isinstance(url, str):
        return False
    trimmed = url.strip()
    if not trimmed or len(trimmed) < 10:
        return False
    if any(ws in trimmed for ws in (" ", "\n", "\r", "\t")):
        return False
    try:
        parsed = urllib.parse.urlsplit(trimmed)
        if parsed.scheme.lower() not in ("http", "https"):
            return False
        if not parsed.netloc or "." not in parsed.netloc:
            return False
        return True
    except Exception:
        return False


def is_linkedin_job_url(url: Optional[str]) -> bool:
    """
    Checks if a URL is a specific job posting on LinkedIn.
    Excludes generic company pages, search queries, user profiles, and feed pages.
    """
    if not is_valid_http_url(url):
        return False
    parsed = urllib.parse.urlsplit(url.strip())
    netloc = parsed.netloc.lower()
    if "linkedin.com" not in netloc:
        return False
    path = parsed.path.lower()
    if "/company/" in path or "/school/" in path or "/feed" in path or "/in/" in path:
        return False
    return "/jobs/" in path or "/job/" in path


def is_simplify_job_url(url: Optional[str]) -> bool:
    """
    Checks if a URL is a specific job listing on Simplify.
    """
    if not is_valid_http_url(url):
        return False
    parsed = urllib.parse.urlsplit(url.strip())
    netloc = parsed.netloc.lower()
    if "simplify.jobs" not in netloc:
        return False
    path = parsed.path.lower()
    return "/p/" in path or "/c/" in path or "/job/" in path or "/jobs/" in path


def is_indeed_url(url: Optional[str]) -> bool:
    """
    Checks if a URL is from Indeed.
    Indeed URLs are strictly excluded from display per business requirements.
    """
    if not url or not isinstance(url, str):
        return False
    return "indeed.com" in url.lower()


def canonicalize_apply_url(url: Optional[str]) -> str:
    """
    Normalizes a job URL for equality checking and duplicate suppression:
    - Strips fragments (#...)
    - Strips marketing/tracking query parameters (utm_*, ref, gh_src, trk, etc.)
    - Normalizes trailing slashes and lowercases scheme/hostname.
    """
    if not url or not isinstance(url, str):
        return ""
    trimmed = url.strip()
    if not trimmed:
        return ""
    try:
        parsed = urllib.parse.urlsplit(trimmed)
        scheme = parsed.scheme.lower() or "https"
        netloc = parsed.netloc.lower().rstrip(":")
        path = parsed.path.rstrip("/")
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        tracking_keys = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "ref", "source", "gh_src", "lever-source", "fbclid", "gclid", "_ga", "_gl",
            "trk", "trackingid", "tracking_id", "position", "pageNum",
        }
        filtered_query = [
            (k, v) for k, v in query_pairs if k.lower() not in tracking_keys
        ]
        query_str = urllib.parse.urlencode(filtered_query)
        canon = f"{scheme}://{netloc}{path}"
        if query_str:
            canon += f"?{query_str}"
        return canon
    except Exception:
        return trimmed.lower().rstrip("/")


def classify_application_urls(
    source_url: Optional[str],
    company_apply_url: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    simplify_url: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """
    Categorizes, validates, and routes application URLs:
    1. Official company/ATS application URL (primary destination)
    2. LinkedIn listing URL (if available and distinct)
    3. Simplify listing URL (if available and distinct)
    4. Original discovery/source URL

    Ensures no duplicate routes and excludes forbidden sources (Indeed).
    """
    res_company = company_apply_url.strip() if is_valid_http_url(company_apply_url) else None
    res_linkedin = linkedin_url.strip() if is_valid_http_url(linkedin_url) else None
    res_simplify = simplify_url.strip() if is_valid_http_url(simplify_url) else None
    res_source = source_url.strip() if is_valid_http_url(source_url) else None

    # Never allow Indeed URLs as application targets
    if res_company and is_indeed_url(res_company):
        res_company = None
    if res_linkedin and is_indeed_url(res_linkedin):
        res_linkedin = None
    if res_simplify and is_indeed_url(res_simplify):
        res_simplify = None
    if res_source and is_indeed_url(res_source):
        res_source = None

    # Validate specific secondary routes
    if res_linkedin and not is_linkedin_job_url(res_linkedin):
        res_linkedin = None
    if res_simplify and not is_simplify_job_url(res_simplify):
        res_simplify = None

    # Derive missing URLs from source_url if appropriate
    if res_source:
        if is_linkedin_job_url(res_source):
            if not res_linkedin:
                res_linkedin = res_source
        elif is_simplify_job_url(res_source):
            if not res_simplify:
                res_simplify = res_source
        elif not res_company:
            # Source URL is an official company or ATS URL (Greenhouse, Lever, Ashby, company domain, etc.)
            res_company = res_source

    # If company_apply_url is still None, but we have an official URL in source
    if not res_company and res_source and not is_linkedin_job_url(res_source) and not is_simplify_job_url(res_source):
        res_company = res_source

    # Deduplicate secondary routes against primary/official company URL
    primary_canon = canonicalize_apply_url(res_company or res_source or "")
    if res_linkedin and canonicalize_apply_url(res_linkedin) == primary_canon:
        res_linkedin = None
    if res_simplify and canonicalize_apply_url(res_simplify) == primary_canon:
        res_simplify = None
    if res_simplify and res_linkedin and canonicalize_apply_url(res_simplify) == canonicalize_apply_url(res_linkedin):
        res_simplify = None

    return {
        "company_apply_url": res_company,
        "linkedin_url": res_linkedin,
        "simplify_url": res_simplify,
        "source_url": res_source,
    }


def resolve_primary_apply_url(
    company_apply_url: Optional[str],
    source_url: Optional[str],
    linkedin_url: Optional[str] = None,
    simplify_url: Optional[str] = None,
) -> Optional[str]:
    """
    Deterministically resolves the primary Apply destination:
    Priority: Official company/ATS URL -> source_url (if official) -> linkedin_url -> simplify_url -> source_url.
    Strictly suppresses Indeed.
    """
    urls = [company_apply_url]
    if source_url and not is_linkedin_job_url(source_url) and not is_simplify_job_url(source_url):
        urls.append(source_url)
    urls.extend([linkedin_url, simplify_url, source_url])

    for u in urls:
        if is_valid_http_url(u) and not is_indeed_url(u):
            return u.strip()
    return None



def tidy_location_label(label: str) -> str:
    """Repair separator debris in a stored or source label: "Remote - , Canada" -> "Remote - Canada".

    Older normalizer versions left the comma of "Remote, Canada" behind when rebuilding it as "Remote - Canada". The
    repair job re-normalizes stored labels, so the cleanup has to live here rather than only in the producer.
    """
    cleaned = re.sub(r"(?i)\b(remote)\s*-\s*,\s*", r"\1 - ", label)
    cleaned = re.sub(r"\s*,\s*,+", ",", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


# A way of working or a travel note written where a location belongs ("Remote-Friendly (Travel Required)", "Offsite/Home").
# It is not a place: it must never become a location of its own, nor turn the real locations beside it into "Remote".
_NOT_A_PLACE = re.compile(r"^\(?\s*(?:remote\s*[-–]?\s*friendly\b.*|travel[- ]required\)?|offsite(?:/home)?|off-site|home|work from home)\s*\)?$", re.I)


def normalize_job_locations(raw_location: str, structured: Optional[list] = None) -> list[dict]:
    """Keep alternative locations on one requisition; never pick the last country.

    Split explicit alternative delimiters only. Commas remain city/region separators.
    Structured country fields override ambiguous labels such as London or Remote.
    """
    entries = structured or [{"location": raw_location or ""}]
    # Even a structured location label can contain multiple alternative countries.
    expanded = []
    for entry in entries:
        label = str(entry.get("location") or entry.get("name") or "").strip()
        labels = re.split(r";|\s*[|]\s*|\s*/\s*|\s+or\s+", label)
        # Split explicit country alternatives; '&' in a street/company name is not a delimiter.
        remote_countries = re.fullmatch(r"remote\s*[-(: ]*\s*(us|usa|united states|canada)\s*(?:&|and)\s*(us|usa|united states|canada)\s*[)]*", label, re.I)
        if remote_countries:
            labels = [f"Remote - {part}" for part in remote_countries.groups()]
        # Country-only alternatives must not collapse into the last country.
        countries = re.sub(r"(?i)^remote\s*[-( ]*", "", label).strip(" ()")
        country_parts = [part.strip() for part in countries.split(",")]
        if len(country_parts) > 1 and all(part.lower() in KNOWN_COUNTRIES for part in country_parts):
            labels = country_parts
        # Split comma-separated complete cities/countries, never City, State.
        split_cities = "|".join(re.escape(c) for c in CURATED_CITIES)
        labels = [part for value in labels for part in re.split(rf",\s*(?=(?:{split_cities})(?:,|$))", value, flags=re.I)]
        real = [value for value in labels if not _NOT_A_PLACE.match(value.strip())]
        dropped_notes = bool(real) and len(real) != len(labels)
        if dropped_notes:
            labels, label = real, " | ".join(real)
        if len(labels) > 1:
            # "Remote (US | Canada)" / "Remote or Toronto": a LEADING remote applies to every alternative.
            # A semicolon separates independent locations. Otherwise remote belongs only to the alternative that says it, so
            # "Toronto, ON; Seattle, WA; Remote - Canada" keeps the two cities as on-site locations.
            leading_remote = ";" not in label and bool(re.match(r"\s*\(?\s*remote\b", label, re.I))
            for value in labels:
                value = value.strip(" ()")
                remote = leading_remote or bool(re.search(r"\bremote\b", value, re.I))
                if remote:
                    value = re.sub(r"(?i)^remote\s*[( ,:-]*", "", value).strip(" (),:-")
                    value = f"Remote - {value}" if value else "Remote"
                # Country on a composite label may belong to just the primary location.
                expanded.append({"location": value})
        else:
            expanded.append({**entry, "location": labels[0].strip(" ()")} if dropped_notes else entry)
    entries = expanded
    result = []
    iso = {"US": "United States", "USA": "United States", "CA": "Canada", "CAN": "Canada", "GB": "United Kingdom", "DE": "Germany", "FR": "France"}
    for entry in entries:
        label = tidy_location_label(str(entry.get("location") or entry.get("name") or "").strip())
        address = entry.get("address") or {}
        if not isinstance(address, dict):
            address = {}
        address = address.get("postalAddress", address)
        if not isinstance(address, dict):
            address = {}
        explicit = str(address.get("addressCountry") or entry.get("country") or "").strip()
        published_label = label
        location, country = normalize_location_and_country(label)
        # One canonical shape for a plain well-known city ("Toronto, ON" and "Toronto, Canada" -> "Toronto, Ontario, Canada").
        canonical = canonical_place_label(label, KNOWN_COUNTRIES.get(explicit.lower(), explicit) if explicit else country)
        if canonical:
            label = canonical
        if explicit:
            country = iso.get(explicit.upper(), KNOWN_COUNTRIES.get(explicit.lower(), explicit))
        if location == "Unknown" and explicit:
            location = country
        # Keep source location restrictions (e.g. Remote - California), not just Remote.
        item = {"location": label or location, "country": country}
        if explicit and country in ELIGIBLE_COUNTRIES and not is_user_facing_location_eligible(item["location"], country):
            locality = str(address.get("addressLocality") or "").strip()
            region = str(address.get("addressRegion") or "").strip()
            item["location"] = ", ".join(x for x in [locality, region, country] if x)
            item["source_location"] = label
        # A source-specific normalizer may have rewritten the label; keep what the source published.
        carried = [x for x in (entry.get("also_published") or []) if isinstance(x, str)]
        raw = str(entry.get("raw_location") or "").strip() or (published_label if canonical and published_label != item["location"] else "")
        if raw and raw != item["location"]:
            item["raw_location"] = raw
        if carried:
            item["also_published"] = carried
        # Two source labels that normalize to the same place are one location. The first raw label stays as raw_location; any other
        # published spelling is kept in also_published, so no published label is lost by merging.
        strip = lambda r: {k: v for k, v in r.items() if k not in ("raw_location", "also_published", "source_location")}
        twin = next((r for r in result if strip(r) == strip(item)), None)
        if twin is None:
            result.append(item)
        else:
            seen = {twin.get("raw_location"), twin["location"], *(twin.get("also_published") or [])}
            for published in (item.get("raw_location"), published_label, *(item.get("also_published") or [])):
                if published and published not in seen:
                    twin.setdefault("also_published", []).append(published)
                    seen.add(published)
    # A bare "Offsite" / "Home" entry is a way of working, not a location (kept in the posting text and the raw label).
    places = [r for r in result if not _NOT_A_PLACE.match(r["location"].strip())]
    return places or result or [{"location": "Unknown", "country": "Unknown"}]


# =============================================================================
# Official sources and Canada helpers
# =============================================================================

# Sources whose feeds are the employer's own careers system. Only these are public.
OFFICIAL_SOURCES: Tuple[str, ...] = ("greenhouse", "lever", "ashby", "workday", "amazon", "google", "shopify", "phenom", "successfactors")


def official_sources_sql() -> str:
    """SQL tuple literal of OFFICIAL_SOURCES, e.g. ('greenhouse', 'lever', ...)."""
    return "(" + ", ".join(f"'{name}'" for name in OFFICIAL_SOURCES) + ")"


def job_has_canada_location(locations: Optional[list], primary_country: Optional[str] = None) -> bool:
    """True when ANY of a job's locations (or its primary country) is Canadian."""
    if primary_country == "Canada":
        return True
    return any(isinstance(loc, dict) and loc.get("country") == "Canada" for loc in (locations or []))
