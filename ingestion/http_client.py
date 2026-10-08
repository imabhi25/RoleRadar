"""
Hardened HTTP Client for RoleRadar ATS Ingestion.
Provides reliable HTTP request handling with retry policies, timeouts, and error abstraction.
"""

import logging
import time
from typing import Any, Dict, Optional, Tuple
import urllib.parse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

logger = logging.getLogger("ingestion.http_client")

DEFAULT_USER_AGENT = "RoleRadar/1.0 (+https://github.com/imabhi25/Jobber)"
DEFAULT_TIMEOUT: Tuple[float, float] = (10.0, 30.0)  # (connect_timeout, read_timeout)
RETRY_STATUSES = [429, 500, 502, 503, 504]
MAX_RETRIES = 3
BACKOFF_FACTOR = 1.0


class IngestionFetchError(Exception):
    """Raised when an external ATS fetch fails due to network, HTTP, or parsing errors."""
    pass


def sanitize_url_for_logging(url: str) -> str:
    """
    Redacts sensitive parameters (tokens, keys, secrets) from URLs for safe logging.
    """
    try:
        parsed = urllib.parse.urlsplit(url)
        if not parsed.query:
            return url
        params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        sanitized_params = []
        for key, val in params:
            lower_key = key.lower()
            if any(term in lower_key for term in ["key", "token", "secret", "auth", "pwd", "password"]):
                sanitized_params.append((key, "[REDACTED]"))
            else:
                sanitized_params.append((key, val))
        new_query = urllib.parse.urlencode(sanitized_params, safe="[]")
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
        )
    except Exception:
        return "[INVALID_URL]"


class HardenedHttpClient:
    """
    Robust HTTP client with connection pooling, retries with backoff, and error handling.
    """

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent

        if session is not None:
            self.session = session
        else:
            self.session = requests.Session()
            retry_kwargs = {
                "total": MAX_RETRIES,
                "backoff_factor": BACKOFF_FACTOR,
                "status_forcelist": RETRY_STATUSES,
                "respect_retry_after_header": True,
                "raise_on_status": False,
            }
            if hasattr(Retry, "DEFAULT_ALLOWED_METHODS"):
                retry_kwargs["allowed_methods"] = frozenset(["GET", "HEAD"])
            else:
                retry_kwargs["method_whitelist"] = frozenset(["GET", "HEAD"])
            retry_strategy = Retry(**retry_kwargs)
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)

        self.session.headers.update({"User-Agent": self.user_agent})

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[Tuple[float, float]] = None,
    ) -> requests.Response:
        """
        Executes a GET request with configured retries, timeouts, and error wrapping.

        Raises:
            IngestionFetchError: If the request fails or returns an unrecoverable HTTP status.
        """
        effective_timeout = timeout or self.timeout
        safe_url = sanitize_url_for_logging(url)

        try:
            logger.info("Fetching URL: %s", safe_url)
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=effective_timeout,
            )
        except requests.exceptions.RequestException as err:
            logger.error("Network error while requesting %s: %s", safe_url, err)
            raise IngestionFetchError(f"Network error fetching {safe_url}: {err}") from err

        if response.status_code != 200:
            logger.error(
                "HTTP %d error returned from %s", response.status_code, safe_url
            )
            preview = response.text[:200].replace("\n", " ").strip() if response.text else "No content"
            raise IngestionFetchError(
                f"HTTP {response.status_code} error from {safe_url}: {preview}"
            )

        return response

    def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[Tuple[float, float]] = None,
    ) -> Any:
        """
        Executes a GET request and parses the JSON response body.

        Raises:
            IngestionFetchError: If HTTP fails or response is not valid JSON.
        """
        response = self.get(url, params=params, headers=headers, timeout=timeout)
        safe_url = sanitize_url_for_logging(url)
        try:
            return response.json()
        except ValueError as err:
            logger.error("Failed to parse JSON response from %s: %s", safe_url, err)
            raise IngestionFetchError(
                f"Invalid JSON returned from {safe_url}: {err}"
            ) from err

    def post_json(
        self,
        url: str,
        body: Any,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[Tuple[float, float]] = None,
        attempts: int = 3,
    ) -> Any:
        """
        POSTs a JSON body and parses the JSON response. Used only for read-only search
        endpoints (e.g. Workday CXS). Retries transient failures (429/5xx/network) since
        the session-level retry policy is limited to GET/HEAD.

        Raises:
            IngestionFetchError: on network failure, non-200 status, or invalid JSON.
        """
        effective_timeout = timeout or self.timeout
        safe_url = sanitize_url_for_logging(url)
        last_error: Optional[str] = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                response = self.session.post(
                    url, json=body, headers=headers, timeout=effective_timeout
                )
            except requests.exceptions.RequestException as err:
                last_error = f"Network error posting to {safe_url}: {err}"
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as err:
                        raise IngestionFetchError(f"Invalid JSON returned from {safe_url}: {err}") from err
                preview = response.text[:200].replace("\n", " ").strip() if response.text else "No content"
                last_error = f"HTTP {response.status_code} error from {safe_url}: {preview}"
                if response.status_code not in RETRY_STATUSES:
                    break
            if attempt < attempts:
                time.sleep(BACKOFF_FACTOR * attempt)
        logger.error("%s", last_error)
        raise IngestionFetchError(last_error or f"POST failed for {safe_url}")

    def close(self) -> None:
        """Closes the underlying requests session."""
        self.session.close()

    def __enter__(self) -> "HardenedHttpClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
