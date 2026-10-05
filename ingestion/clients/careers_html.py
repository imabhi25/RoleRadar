"""Small helpers for official, server-rendered employer career sites. No JavaScript execution."""
from datetime import datetime, timezone
import json
import re

from bs4 import BeautifulSoup

from ingestion.http_client import IngestionFetchError
from ingestion.normalizer import STUDENT_ENGINEER_REGEX, TECHNICAL_PROGRAM_REGEX, is_swe_role


def needs_detail(title):
    return bool(is_swe_role(title) or STUDENT_ENGINEER_REGEX.search(title) or TECHNICAL_PROGRAM_REGEX.search(title))


def source_date(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except ValueError:
        for fmt in ("%b %d, %Y", "%a %b %d %H:%M:%S UTC %Y"):
            try:
                return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return None


def phenom_data(html):
    match = re.search(r"phApp\.ddo\s*=\s*", html)
    try:
        return json.JSONDecoder().raw_decode(html[match.end():])[0] if match else None
    except (ValueError, TypeError):
        return None


def shopify_loader(html, route):
    """Decode the public React Router reference table; retain only the requested loader.

    The page also contains hiring-team metadata. Callers must only store public
    posting fields, never the unrelated internal job object or the entire loader.
    Unknown encodings fail closed instead of evaluating scripts or guessing indexes.
    """
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        text = script.string or ""
        match = re.search(r"streamController\.enqueue\(", text)
        if not match:
            continue
        try:
            encoded = json.JSONDecoder().raw_decode(text[match.end():])[0]
            pool = json.loads(encoded)
            if not isinstance(pool, list):
                continue
            cache = {}

            def decode(index):
                if not isinstance(index, int) or isinstance(index, bool):
                    raise ValueError("Invalid reference")
                if index < 0:
                    if index not in (-1, -5, -7):
                        raise ValueError("Unknown sentinel")
                    return None
                if index in cache:
                    return cache[index]
                value = pool[index]
                if isinstance(value, dict):
                    cache[index] = {}
                    for key, ref in value.items():
                        if not re.fullmatch(r"_\d+", key):
                            raise ValueError("Unknown object encoding")
                        cache[index][str(decode(int(key[1:])))] = decode(ref)
                elif isinstance(value, list):
                    cache[index] = []
                    for ref in value:
                        cache[index].append(decode(ref) if isinstance(ref, int) else ref)
                else:
                    cache[index] = value
                return cache[index]

            loader = decode(0).get("loaderData", {}).get(route)
            if isinstance(loader, dict):
                return loader
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
            continue
    raise IngestionFetchError("Shopify public loader missing or encoding changed")
