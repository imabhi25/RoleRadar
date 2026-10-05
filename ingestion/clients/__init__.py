"""
ATS Client Adapters and Factory for RoleRadar.
Provides GreenhouseClient, LeverClient, AshbyClient, and get_ats_client factory.
"""

from typing import Any, Dict, Optional, Union

from ingestion.base import BaseATSClient
from ingestion.clients.amazon import AmazonClient
from ingestion.clients.arbeitnow import ArbeitnowClient
from ingestion.clients.ashby import AshbyClient
from ingestion.clients.greenhouse import GreenhouseClient
from ingestion.clients.jobicy import JobicyClient
from ingestion.clients.lever import LeverClient
from ingestion.clients.remotive import RemotiveClient
from ingestion.clients.workday import WorkdayClient
from ingestion.clients.google import GoogleClient
from ingestion.clients.shopify import ShopifyClient
from ingestion.clients.phenom import PhenomClient
from ingestion.clients.successfactors import SuccessFactorsClient
from ingestion.http_client import HardenedHttpClient

CLIENT_REGISTRY = {
    "greenhouse": GreenhouseClient,
    "lever": LeverClient,
    "ashby": AshbyClient,
    "workday": WorkdayClient,
    "amazon": AmazonClient,
    "google": GoogleClient,
    "shopify": ShopifyClient,
    "phenom": PhenomClient,
    "successfactors": SuccessFactorsClient,
    "jobicy": JobicyClient,
    "remotive": RemotiveClient,
    "arbeitnow": ArbeitnowClient,
}

BROAD_SOURCES = {"jobicy", "remotive", "arbeitnow"}


def get_ats_client(
    ats_source: Union[Dict[str, Any], str],
    http_client: Optional[HardenedHttpClient] = None,
) -> BaseATSClient:
    """
    Factory function returning the appropriate ATS or broad job source client instance.

    Args:
        ats_source: Either a dictionary containing an 'ats' or 'source' key
                    or a direct string name ('greenhouse', 'lever', 'ashby', 'jobicy').
        http_client: Optional shared HardenedHttpClient instance.

    Returns:
        An instance of BaseATSClient corresponding to the requested provider.

    Raises:
        ValueError: If the provider is unrecognized or unsupported.
    """
    if isinstance(ats_source, dict):
        ats_key = (ats_source.get("ats") or ats_source.get("source") or "").strip().lower()
    else:
        ats_key = str(ats_source).strip().lower()

    client_cls = CLIENT_REGISTRY.get(ats_key)
    if not client_cls:
        supported = ", ".join(sorted(CLIENT_REGISTRY.keys()))
        raise ValueError(
            f"Unsupported provider '{ats_key}'. Supported providers are: {supported}"
        )

    return client_cls(http_client=http_client)


def get_broad_source_client(
    source_name: str,
    http_client: Optional[HardenedHttpClient] = None,
) -> BaseATSClient:
    """
    Factory helper returning a broad job source client instance (jobicy, remotive, arbeitnow).
    """
    key = str(source_name).strip().lower()
    if key not in BROAD_SOURCES:
        supported = ", ".join(sorted(BROAD_SOURCES))
        raise ValueError(f"Unsupported broad source '{source_name}'. Supported sources: {supported}")
    return get_ats_client(key, http_client=http_client)


__all__ = [
    "BaseATSClient",
    "GreenhouseClient",
    "LeverClient",
    "AshbyClient",
    "WorkdayClient",
    "AmazonClient",
    "JobicyClient",
    "RemotiveClient",
    "ArbeitnowClient",
    "get_ats_client",
    "get_broad_source_client",
    "CLIENT_REGISTRY",
    "BROAD_SOURCES",
]
