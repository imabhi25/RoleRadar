"""
Centralized Company Branding and Logo Resolution Service for RoleRadar.

Provides company-level logo and branding persistence, durable local asset caching,
ATS employer branding discovery, and verified domain mapping.
Ensures no fake, generated, or imitation marks are used, and flags unverified
companies as 'unresolved' for manual review.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests

logger = logging.getLogger("ingestion.company_resolver")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGOS_DIR = PROJECT_ROOT / "frontend" / "public" / "logos"

# Curated catalog of verified company branding
# Each entry maps normalized company name -> verified assets and provenance.
VERIFIED_COMPANY_CATALOG: Dict[str, Dict[str, Any]] = {
    "google": {
        "name": "Google",
        "logo_url": "/logos/google.png",
        "logo_source_url": "https://www.gstatic.com/hiring/CportalUi/google_logo_dark.png",
        "website_url": "https://www.google.com",
        "domain": "google.com",
        "logo_status": "verified"
    },
    "shopify": {
        "name": "Shopify",
        "logo_url": "/logos/shopify.svg",
        "logo_source_url": "https://cdn.shopify.com/b/shopify-brochure2-assets/300e9fa74de3ba3d5f0eb67d6face405.svg",
        "website_url": "https://www.shopify.com",
        "domain": "shopify.com",
        "logo_status": "verified"
    },
    "bell": {
        "name": "Bell",
        "logo_url": "/logos/bell.png",
        "logo_source_url": "https://cdn.phenompeople.com/CareerConnectResources/BECACA/en_ca/desktop/assets/images/h/apple-touch-icon.png",
        "website_url": "https://www.bell.ca",
        "domain": "bell.ca",
        "logo_status": "verified"
    },
    "rogers": {
        "name": "Rogers",
        "logo_url": "/logos/rogers.png",
        "logo_source_url": "https://rmkcdn.successfactors.com/e6281b02/a7ba73fe-81ee-4171-8c66-e.png",
        "website_url": "https://www.rogers.com",
        "domain": "rogers.com",
        "logo_status": "verified"
    },
    "scotiabank": {
        "name": "Scotiabank",
        "logo_url": "/logos/scotiabank.png",
        "logo_source_url": "https://rmkcdn.successfactors.com/c37ab1bb/9fe76e4f-e61e-4096-89f7-5.png",
        "website_url": "https://www.scotiabank.com",
        "domain": "scotiabank.com",
        "logo_status": "verified"
    },
    "telus": {
        "name": "TELUS",
        "logo_url": "/logos/telus.jpg",
        "logo_source_url": "https://rmkcdn.successfactors.com/bf2f6462/cafe4c5c-9d69-4b61-a43c-8.png",
        "website_url": "https://www.telus.com",
        "domain": "telus.com",
        "logo_status": "verified"
    },
    "clio": {
        "name": "Clio",
        "logo_url": "/logos/clio.png",
        "logo_source_url": "https://clio.wd3.myworkdayjobs.com/en-US/ClioCareerSite/assets/logo",
        "website_url": "https://www.clio.com",
        "domain": "clio.com",
        "logo_status": "verified"
    },
    "eq bank": {
        "name": "EQ Bank",
        "logo_url": "/logos/eq-bank.svg",
        "logo_source_url": "https://images.ctfassets.net/ymwa45h4u77x/4oX5L57Tc4Xrv2iKG72VPN/481fb11b7a59027ebd4316579313fe3d/eqbank-logo.svg",
        "website_url": "https://www.eqbank.ca",
        "domain": "eqbank.ca",
        "logo_status": "verified"
    },
    "figma": {
        "name": "Figma",
        "domain": "figma.com",
        "website_url": "https://figma.com",
        "logo_url": "/logos/figma.svg",
        "logo_source_url": "https://upload.wikimedia.org/wikipedia/commons/3/33/Figma-logo.svg",
        "logo_status": "verified",
    },
    "cloudflare": {
        "name": "Cloudflare",
        "domain": "cloudflare.com",
        "website_url": "https://cloudflare.com",
        "logo_url": "/logos/cloudflare.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "datadog": {
        "name": "Datadog",
        "domain": "datadoghq.com",
        "website_url": "https://datadoghq.com",
        "logo_url": "/logos/datadog.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "gitlab": {
        "name": "GitLab",
        "domain": "gitlab.com",
        "website_url": "https://gitlab.com",
        "logo_url": "/logos/gitlab.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "spotify": {
        "name": "Spotify",
        "domain": "spotify.com",
        "website_url": "https://spotify.com",
        "logo_url": "/logos/spotify.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "palantir": {
        "name": "Palantir",
        "domain": "palantir.com",
        "website_url": "https://palantir.com",
        "logo_url": "/logos/palantir.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "neon": {
        "name": "Neon",
        "domain": "neon.tech",
        "website_url": "https://neon.tech",
        "logo_url": "/logos/neon.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "metabase": {
        "name": "Metabase",
        "domain": "metabase.com",
        "website_url": "https://metabase.com",
        "logo_url": "/logos/metabase.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "linear": {
        "name": "Linear",
        "domain": "linear.app",
        "website_url": "https://linear.app",
        "logo_url": "/logos/linear.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "ramp": {
        "name": "Ramp",
        "domain": "ramp.com",
        "website_url": "https://ramp.com",
        "logo_url": "/logos/ramp.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "supabase": {
        "name": "Supabase",
        "domain": "supabase.com",
        "website_url": "https://supabase.com",
        "logo_url": "/logos/supabase.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "anthropic": {
        "name": "Anthropic",
        "domain": "anthropic.com",
        "website_url": "https://anthropic.com",
        "logo_url": "/logos/anthropic.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "openai": {
        "name": "OpenAI",
        "domain": "openai.com",
        "website_url": "https://openai.com",
        "logo_url": "/logos/openai.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "stripe": {
        "name": "Stripe",
        "domain": "stripe.com",
        "website_url": "https://stripe.com",
        "logo_url": "/logos/stripe.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "spacex": {
        "name": "SpaceX",
        "domain": "spacex.com",
        "website_url": "https://www.spacex.com",
        "logo_url": "/logos/spacex.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "databricks": {
        "name": "Databricks",
        "domain": "databricks.com",
        "website_url": "https://databricks.com",
        "logo_url": "/logos/databricks.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "robinhood": {
        "name": "Robinhood",
        "domain": "robinhood.com",
        "website_url": "https://robinhood.com",
        "logo_url": "/logos/robinhood.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "scale ai": {
        "name": "Scale AI",
        "domain": "scale.com",
        "website_url": "https://scale.com",
        "logo_url": "/logos/scaleai.svg",
        "logo_source_url": "https://scale.com/favicon.svg",
        "logo_status": "verified",
    },
    "scale": {
        "name": "Scale AI",
        "domain": "scale.com",
        "website_url": "https://scale.com",
        "logo_url": "/logos/scaleai.svg",
        "logo_source_url": "https://scale.com/favicon.svg",
        "logo_status": "verified",
    },
    "reddit": {
        "name": "Reddit",
        "domain": "reddit.com",
        "website_url": "https://reddit.com",
        "logo_url": "/logos/reddit.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "coinbase": {
        "name": "Coinbase",
        "domain": "coinbase.com",
        "website_url": "https://coinbase.com",
        "logo_url": "/logos/coinbase.svg",
        "logo_source_url": "https://coinbase.com",
        "logo_status": "verified",
    },
    "pinterest": {
        "name": "Pinterest",
        "domain": "pinterest.com",
        "website_url": "https://pinterest.com",
        "logo_url": "/logos/pinterest.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "brex": {
        "name": "Brex",
        "domain": "brex.com",
        "website_url": "https://brex.com",
        "logo_url": "/logos/brex.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "chime": {
        "name": "Chime",
        "domain": "chime.com",
        "website_url": "https://chime.com",
        "logo_url": "/logos/chime.png",
        "logo_source_url": "https://chime.com",
        "logo_status": "verified",
    },
    "duolingo": {
        "name": "Duolingo",
        "domain": "duolingo.com",
        "website_url": "https://duolingo.com",
        "logo_url": "/logos/duolingo.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "faire": {
        "name": "Faire",
        "domain": "faire.com",
        "website_url": "https://faire.com",
        "logo_url": "/logos/faire.png",
        "logo_source_url": "https://www.faire.com/apple-touch-icon.png",
        "logo_status": "verified",
    },
    "waabi": {
        "name": "Waabi",
        "domain": "waabi.ai",
        "website_url": "https://waabi.ai",
        "logo_url": "/logos/waabi.png",
        "logo_source_url": "https://lever-client-logos.s3.us-west-2.amazonaws.com/99d3bf4f-9035-4cb6-9d7c-51c8ad9412a8-1757943910265.png",
        "logo_status": "verified",
    },
    "rubrik": {
        "name": "Rubrik",
        "domain": "rubrik.com",
        "website_url": "https://rubrik.com",
        "logo_url": "/logos/rubrik.png",
        "logo_source_url": "https://boards.greenhouse.io/rubrik",
        "logo_status": "verified",
    },
    "flexport": {
        "name": "Flexport",
        "domain": "flexport.com",
        "website_url": "https://flexport.com",
        "logo_url": "/logos/flexport.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "samsara": {
        "name": "Samsara",
        "domain": "samsara.com",
        "website_url": "https://samsara.com",
        "logo_url": "/logos/samsara.png",
        "logo_source_url": "https://samsara.com",
        "logo_status": "verified",
    },
    "toast": {
        "name": "Toast",
        "domain": "toasttab.com",
        "website_url": "https://toasttab.com",
        "logo_url": "/logos/toast.png",
        "logo_source_url": "https://toasttab.com",
        "logo_status": "verified",
    },
    "notion": {
        "name": "Notion",
        "domain": "notion.so",
        "website_url": "https://notion.so",
        "logo_url": "/logos/notion.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "plaid": {
        "name": "Plaid",
        "domain": "plaid.com",
        "website_url": "https://plaid.com",
        "logo_url": "/logos/plaid.png",
        "logo_source_url": "https://plaid.com/assets/img/favicons/apple-touch-icon.png",
        "logo_status": "verified",
    },
    "cohere": {
        "name": "Cohere",
        "domain": "cohere.com",
        "website_url": "https://cohere.com",
        "logo_url": "/logos/cohere.png",
        "logo_source_url": "https://cohere.com",
        "logo_status": "verified",
    },
    "wealthsimple": {
        "name": "Wealthsimple",
        "domain": "wealthsimple.com",
        "website_url": "https://wealthsimple.com",
        "logo_url": "/logos/wealthsimple.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "pointclickcare": {
        "name": "PointClickCare",
        "domain": "pointclickcare.com",
        "website_url": "https://pointclickcare.com",
        "logo_url": "/logos/pointclickcare.png",
        "logo_source_url": "https://lever-client-logos.s3.us-west-2.amazonaws.com/458c92e4-e8e4-4bcb-b79a-4d9663eaf4b8-1760615686801.png",
        "logo_status": "verified",
    },
    "stackadapt": {
        "name": "StackAdapt",
        "domain": "stackadapt.com",
        "website_url": "https://stackadapt.com",
        "logo_url": "/logos/stackadapt.png",
        "logo_source_url": "https://stackadapt.com",
        "logo_status": "verified",
    },
    "vercel": {
        "name": "Vercel",
        "domain": "vercel.com",
        "website_url": "https://vercel.com",
        "logo_url": "/logos/vercel.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "1password": {
        "name": "1Password",
        "domain": "1password.com",
        "website_url": "https://1password.com",
        "logo_url": "/logos/1password.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "sentry": {
        "name": "Sentry",
        "domain": "sentry.io",
        "website_url": "https://sentry.io",
        "logo_url": "/logos/sentry.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "sourcegraph": {
        "name": "Sourcegraph",
        "domain": "sourcegraph.com",
        "website_url": "https://sourcegraph.com",
        "logo_url": "/logos/sourcegraph.png",
        "logo_source_url": "https://sourcegraph.com",
        "logo_status": "verified",
    },
    "replit": {
        "name": "Replit",
        "domain": "replit.com",
        "website_url": "https://replit.com",
        "logo_url": "/logos/replit.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "render": {
        "name": "Render",
        "domain": "render.com",
        "website_url": "https://render.com",
        "logo_url": "/logos/render.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "planetscale": {
        "name": "PlanetScale",
        "domain": "planetscale.com",
        "website_url": "https://planetscale.com",
        "logo_url": "/logos/planetscale.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "webflow": {
        "name": "Webflow",
        "domain": "webflow.com",
        "website_url": "https://webflow.com",
        "logo_url": "/logos/webflow.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "grafana labs": {
        "name": "Grafana Labs",
        "domain": "grafana.com",
        "website_url": "https://grafana.com",
        "logo_url": "/logos/grafana.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "grafana": {
        "name": "Grafana Labs",
        "domain": "grafana.com",
        "website_url": "https://grafana.com",
        "logo_url": "/logos/grafana.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "mistral ai": {
        "name": "Mistral AI",
        "domain": "mistral.ai",
        "website_url": "https://mistral.ai",
        "logo_url": "/logos/mistralai.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "mistral": {
        "name": "Mistral AI",
        "domain": "mistral.ai",
        "website_url": "https://mistral.ai",
        "logo_url": "/logos/mistralai.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "runway": {
        "name": "Runway",
        "domain": "runwayml.com",
        "website_url": "https://runwayml.com",
        "logo_url": "/logos/runway.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "runwayml": {
        "name": "Runway",
        "domain": "runwayml.com",
        "website_url": "https://runwayml.com",
        "logo_url": "/logos/runway.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "anyscale": {
        "name": "Anyscale",
        "domain": "anyscale.com",
        "website_url": "https://anyscale.com",
        "logo_url": "/logos/anyscale.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "stability ai": {
        "name": "Stability AI",
        "domain": "stability.ai",
        "website_url": "https://stability.ai",
        "logo_url": "/logos/stabilityai.png",
        "logo_source_url": "https://images.squarespace-cdn.com/content/v1/6213c340453c3f502425776e/a3485d53-7e65-42b5-bc62-e2e55f8409b9/stability-ai-white-dot-desktop.png",
        "logo_status": "verified",
    },
    "stability": {
        "name": "Stability AI",
        "domain": "stability.ai",
        "website_url": "https://stability.ai",
        "logo_url": "/logos/stabilityai.png",
        "logo_source_url": "https://images.squarespace-cdn.com/content/v1/6213c340453c3f502425776e/a3485d53-7e65-42b5-bc62-e2e55f8409b9/stability-ai-white-dot-desktop.png",
        "logo_status": "verified",
    },
    "monzo": {
        "name": "Monzo",
        "domain": "monzo.com",
        "website_url": "https://monzo.com",
        "logo_url": "/logos/monzo.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "carta": {
        "name": "Carta",
        "domain": "carta.com",
        "website_url": "https://carta.com",
        "logo_url": "/logos/carta.png",
        "logo_source_url": "https://s3-recruiting.cdn.greenhouse.io/external_greenhouse_job_boards/logos/400/110/100/original/CartaLogo_Black_(1).png",
        "logo_status": "verified",
    },
    "mercury": {
        "name": "Mercury",
        "domain": "mercury.com",
        "website_url": "https://mercury.com",
        "logo_url": "/logos/mercury.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "amazon": {
        "name": "Amazon",
        "domain": "amazon.com",
        "website_url": "https://amazon.com",
        "logo_url": "/logos/amazon.svg",
        "logo_source_url": "https://commons.wikimedia.org/wiki/File:Amazon_logo.svg",
        "logo_status": "verified",
    },
    "okta": {
        "name": "Okta",
        "domain": "okta.com",
        "website_url": "https://www.okta.com",
        "logo_url": "/logos/okta.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "lyft": {
        "name": "Lyft",
        "domain": "lyft.com",
        "website_url": "https://www.lyft.com",
        "logo_url": "/logos/lyft.svg",
        "logo_source_url": "https://simpleicons.org/",
        "logo_status": "verified",
    },
    "rbc": {
        "name": "RBC",
        "domain": "rbc.com",
        "website_url": "https://rbc.com",
        "logo_url": "/logos/rbc.svg",
        "logo_source_url": "https://www.rbc.com/dvl/v1.0/assets/images/logos/rbc-logo-shield-blue.svg",
        "logo_status": "verified",
    },
    "td": {
        "name": "TD",
        "domain": "td.com",
        "website_url": "https://td.com",
        "logo_url": "/logos/td.svg",
        "logo_source_url": "https://commons.wikimedia.org/wiki/File:Toronto-Dominion_Bank_logo.svg",
        "logo_status": "verified",
    },
    "bmo": {
        "name": "BMO",
        "domain": "bmo.com",
        "website_url": "https://bmo.com",
        "logo_url": "/logos/bmo.svg",
        "logo_source_url": "https://commons.wikimedia.org/wiki/File:BMO_Logo.svg",
        "logo_status": "verified",
    },
    "cibc": {
        "name": "CIBC",
        "domain": "cibc.com",
        "website_url": "https://cibc.com",
        "logo_url": "/logos/cibc.png",
        "logo_source_url": "https://www.cibc.com/content/dam/global-assets/logos/partner-logos/apple/apple-touch-icon.png",
        "logo_status": "verified",
    },
    "manulife": {
        "name": "Manulife",
        "domain": "manulife.com",
        "website_url": "https://manulife.com",
        "logo_url": "/logos/manulife.svg",
        "logo_source_url": "https://commons.wikimedia.org/wiki/File:Manulife_logo_(2018).svg",
        "logo_status": "verified",
    },
    "sun life": {
        "name": "Sun Life",
        "domain": "sunlife.com",
        "website_url": "https://sunlife.com",
        "logo_url": "/logos/sunlife.png",
        "logo_source_url": "https://www.sunlife.com/content/dam/sunlife/global/logos/sun-life/current/logo-yellowbkgrd-bluelogo-1200x1200.jpg",
        "logo_status": "verified",
    },
    "ontario teachers pension plan": {
        "name": "Ontario Teachers' Pension Plan",
        "domain": "otpp.com",
        "website_url": "https://otpp.com",
        "logo_url": "/logos/otpp.png",
        "logo_source_url": "https://www.otpp.com/etc.clientlibs/otpp/clientlibs/clientlib-site/resources/images/favicon/apple-touch-icon.png",
        "logo_status": "verified",
    },
    "thomson reuters": {
        "name": "Thomson Reuters",
        "domain": "thomsonreuters.com",
        "website_url": "https://thomsonreuters.com",
        "logo_url": "/logos/thomsonreuters.png",
        "logo_source_url": "https://www.thomsonreuters.com/apple-touch-icon.png",
        "logo_status": "verified",
    },
    "autodesk": {
        "name": "Autodesk",
        "domain": "autodesk.com",
        "website_url": "https://autodesk.com",
        "logo_url": "/logos/autodesk.svg",
        "logo_source_url": "https://commons.wikimedia.org/wiki/File:Autodesk_symbol.svg",
        "logo_status": "verified",
    },
    "nvidia": {
        "name": "NVIDIA",
        "domain": "nvidia.com",
        "website_url": "https://nvidia.com",
        "logo_url": "/logos/nvidia.svg",
        "logo_source_url": "https://commons.wikimedia.org/wiki/File:NVIDIA_logo.svg",
        "logo_status": "verified",
    },
    "arctic wolf": {
        "name": "Arctic Wolf",
        "domain": "arcticwolf.com",
        "website_url": "https://arcticwolf.com",
        "logo_url": "/logos/arcticwolf.png",
        "logo_source_url": "https://arcticwolf.com/wp-content/uploads/2019/11/aw-favicon-rebrand.png",
        "logo_status": "verified",
    },
    "geotab": {
        "name": "Geotab",
        "domain": "geotab.com",
        "website_url": "https://geotab.com",
        "logo_url": "/logos/geotab.png",
        "logo_source_url": "https://boards.greenhouse.io/geotab",
        "logo_status": "verified",
    },
    "d2l": {
        "name": "D2L",
        "domain": "d2l.com",
        "website_url": "https://d2l.com",
        "logo_url": "/logos/d2l.svg",
        "logo_source_url": "https://commons.wikimedia.org/wiki/File:D2L_logo.svg",
        "logo_status": "verified",
    },
    "hootsuite": {
        "name": "Hootsuite",
        "domain": "hootsuite.com",
        "website_url": "https://hootsuite.com",
        "logo_url": "/logos/hootsuite.png",
        "logo_source_url": "https://www.hootsuite.com/images/apple-touch-icon.png",
        "logo_status": "verified",
    },
    "doordash": {
        "name": "DoorDash",
        "domain": "doordash.com",
        "website_url": "https://doordash.com",
        "logo_url": "/logos/doordash.svg",
        "logo_source_url": "https://commons.wikimedia.org/wiki/File:DoorDash_Logo.svg",
        "logo_status": "verified",
    },
}


# The former Braze SVG was Delivery Hero artwork, despite its misleading <title>.
# Keep its fingerprint so migrations and repeatable branding audits can retire copied bytes
# without deleting a separately verified replacement logo.
REJECTED_COMPANY_LOGOS = {
    "braze": {
        "url": "/logos/braze.svg",
        "sha256": "d0178d0bc26a47349a9307646a8716593126fbb794e1aa175b66aff02ba54484",
        "website_url": "https://www.braze.com",
    },
}


# Employers whose logo is discovered from their ATS board (so no catalog entry carries a website) still need their official
# website. Used to fill a missing website only; a stored website is never replaced.
COMPANY_WEBSITES = {
    "braze": "https://www.braze.com",
}


def known_company_website(company_name: str) -> Optional[str]:
    """The curated official website for a company, from the verified catalog or COMPANY_WEBSITES; None when not curated."""
    normalized = normalize_company_name(company_name)
    entry = VERIFIED_COMPANY_CATALOG.get(normalized)
    return (entry or {}).get("website_url") or COMPANY_WEBSITES.get(normalized) or REJECTED_COMPANY_LOGOS.get(normalized, {}).get("website_url")


def normalize_company_name(name: str) -> str:
    """Normalizes company name for dictionary lookup."""
    if not name:
        return ""
    clean = name.lower().strip()
    clean = re.sub(r"\s*\([^)]*\)", "", clean)
    clean = re.sub(
        r"[,.]?\s+(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|technologies|tech|labs|pbc)\b",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"[^\w\s-]", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def resolve_company_branding(
    company_name: str,
    ats_type: Optional[str] = None,
    identifier: Optional[str] = None,
    cur=None,
) -> Dict[str, Any]:
    """
    Resolves authentic company branding with strict fallback hierarchy:
    1. Check existing verified record in database companies table.
    2. Check curated VERIFIED_COMPANY_CATALOG of official vector and transparent assets.
    3. If ATS metadata is present, attempt verified employer asset discovery.
    4. If no authentic logo can be verified, return unresolved status and None for logo_url.
       NEVER invent or fabricate an imitation logo.
    """
    normalized = normalize_company_name(company_name)
    stored_website = None

    # 1. Check existing database record if cursor provided
    if cur:
        cur.execute(
            """
            SELECT id, name, logo_url, logo_source_url, logo_status, website_url
            FROM companies
            WHERE LOWER(name) = LOWER(%s);
            """,
            (company_name,),
        )
        row = cur.fetchone()
        if row:
            stored_website = row[5]
        rejected = REJECTED_COMPANY_LOGOS.get(normalized, {})
        if row and row[4] == "verified" and row[2] and row[2] != rejected.get("url"):
            return {
                "name": row[1],
                "logo_url": row[2],
                "logo_source_url": row[3],
                "logo_status": row[4],
                "website_url": row[5],
            }

    # 2. Check verified catalog
    if normalized in VERIFIED_COMPANY_CATALOG:
        entry = VERIFIED_COMPANY_CATALOG[normalized]
        # Verify local file exists
        local_rel = entry["logo_url"].lstrip("/")
        local_path = PROJECT_ROOT / "frontend" / "public" / local_rel
        if local_path.is_file():
            return {
                "name": entry["name"],
                "logo_url": entry["logo_url"],
                "logo_source_url": entry["logo_source_url"],
                "logo_status": entry["logo_status"],
                "website_url": entry["website_url"],
            }

    # 3. Dynamic ATS discovery if ATS coordinates provided
    if ats_type and identifier:
        discovered = _discover_ats_branding(company_name, ats_type, identifier)
        if discovered:
            if not discovered.get("website_url"):
                discovered["website_url"] = stored_website or known_company_website(company_name)
            return discovered

    # 4. Honest unverified fallback
    logger.info("Company '%s' has no verified authentic logo asset. Marking unresolved.", company_name)
    return {
        "name": company_name,
        "logo_url": None,
        "logo_source_url": None,
        "logo_status": "unresolved",
        "website_url": REJECTED_COMPANY_LOGOS.get(normalized, {}).get("website_url") or stored_website,
    }


def _discover_ats_branding(
    company_name: str, ats_type: str, identifier: str
) -> Optional[Dict[str, Any]]:
    """
    Safely attempts to discover and durably cache authentic employer branding
    from public ATS endpoints without crashing or blocking ingestion.
    """
    slug = re.sub(r"[^\w-]", "", normalize_company_name(company_name).replace(" ", "-"))
    try:
        if ats_type == "lever":
            # Lever board inspection
            url = f"https://jobs.lever.co/{identifier}"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            if resp.status_code == 200:
                match = re.search(
                    r'(https://lever-client-logos\.s3[^\"]+?\.(?:png|jpg|svg|webp))',
                    resp.text,
                    re.IGNORECASE,
                )
                if match:
                    remote_url = match.group(1)
                    ext = remote_url.split(".")[-1].split("?")[0].lower()
                    cached_filename = f"{slug}.{ext}"
                    dest = LOGOS_DIR / cached_filename
                    img_resp = requests.get(remote_url, timeout=5)
                    if img_resp.status_code == 200 and len(img_resp.content) > 100:
                        with open(dest, "wb") as f:
                            f.write(img_resp.content)
                        return {
                            "name": company_name,
                            "logo_url": f"/logos/{cached_filename}",
                            "logo_source_url": remote_url,
                            "logo_status": "verified",
                            "website_url": None,
                        }
        elif ats_type == "greenhouse":
            # Greenhouse board inspection
            url = f"https://boards.greenhouse.io/{identifier}"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            if resp.status_code == 200:
                match = re.search(
                    r'(https://[^\"]*?greenhouse\.io/[^\"]*?logos/[^\"]+?\.(?:png|jpg|svg|webp)[^\"]*)',
                    resp.text,
                    re.IGNORECASE,
                )
                if match:
                    remote_url = match.group(1)
                    clean_url = remote_url.split("?")[0]
                    ext = clean_url.split(".")[-1].lower()
                    cached_filename = f"{slug}.{ext}"
                    dest = LOGOS_DIR / cached_filename
                    img_resp = requests.get(remote_url, timeout=5)
                    if img_resp.status_code == 200 and len(img_resp.content) > 100:
                        with open(dest, "wb") as f:
                            f.write(img_resp.content)
                        return {
                            "name": company_name,
                            "logo_url": f"/logos/{cached_filename}",
                            "logo_source_url": remote_url,
                            "logo_status": "verified",
                            "website_url": None,
                        }
        elif ats_type == "ashby":
            # Ashby job board inspection
            url = f"https://jobs.ashbyhq.com/{identifier}"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            if resp.status_code == 200:
                match = re.search(
                    r'(https://app\.ashbyhq\.com/api/images/org-theme-(?:logo|wordmark|social)/[^\"]+?\.(?:png|jpg|svg|webp))',
                    resp.text,
                    re.IGNORECASE,
                )
                if not match:
                    match = re.search(
                        r'<meta[^>]+(?:property=[\"\']og:image[\"\']|name=[\"\']twitter:image[\"\'])[^>]+content=[\"\'](https://[^\"]+?\.(?:png|jpg|svg|webp))[\"\']',
                        resp.text,
                        re.IGNORECASE,
                    )
                if match:
                    remote_url = match.group(1)
                    clean_url = remote_url.split("?")[0]
                    ext = clean_url.split(".")[-1].lower()
                    cached_filename = f"{slug}.{ext}"
                    dest = LOGOS_DIR / cached_filename
                    img_resp = requests.get(remote_url, timeout=5)
                    if img_resp.status_code == 200 and len(img_resp.content) > 100:
                        with open(dest, "wb") as f:
                            f.write(img_resp.content)
                        return {
                            "name": company_name,
                            "logo_url": f"/logos/{cached_filename}",
                            "logo_source_url": remote_url,
                            "logo_status": "verified",
                            "website_url": None,
                        }
    except Exception as err:
        logger.debug("Dynamic ATS branding discovery failed for %s (%s): %s", company_name, identifier, err)

    return None


def get_or_create_company_with_branding(
    cur,
    company_name: str,
    ats_type: Optional[str] = None,
    identifier: Optional[str] = None,
) -> Tuple[int, bool]:
    """
    Retrieves existing company ID or creates a new one with verified branding.
    Preserves exact query sequence and single fetchone() on cache hit for test compatibility.
    """
    cur.execute("SELECT id FROM companies WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s));", (company_name,))
    row = cur.fetchone()

    if row:
        return row[0], False

    # Create new company record with verified branding
    branding = resolve_company_branding(company_name, ats_type=ats_type, identifier=identifier)
    cur.execute(
        """
        INSERT INTO companies (name, logo_url, logo_source_url, logo_status, website_url, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT DO NOTHING RETURNING id;
        """,
        (
            company_name,
            branding["logo_url"],
            branding["logo_source_url"],
            branding["logo_status"],
            branding["website_url"],
        ),
    )
    inserted = cur.fetchone()
    if not inserted:
        cur.execute("SELECT id FROM companies WHERE lower(trim(name))=lower(trim(%s))", (company_name,))
        return cur.fetchone()[0], False
    new_id = inserted[0]
    persist_logo_asset(cur, new_id, branding)
    return new_id, True


def sync_canonical_company_names(conn_or_cur) -> int:
    """Give each configured company its configured spelling (case-only differences).

    Migration 012 merged case-variant duplicates and kept the first by id, which could be a mangled variant such as
    "Openai". The stored name is what every card, header and aria-label shows, so the config spelling wins.
    """
    config_path = PROJECT_ROOT / "config" / "target_companies.json"
    with open(config_path, "r", encoding="utf-8") as fp:
        names = [t["name"] for t in json.load(fp) if t.get("name")]
    def run(cur) -> int:
        renamed = 0
        for name in names:
            cur.execute(
                "UPDATE companies SET name = %s, updated_at = NOW() "
                "WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s)) AND name <> %s RETURNING id;",
                (name, name, name),
            )
            renamed += len(cur.fetchall())
        return renamed
    if hasattr(conn_or_cur, "cursor"):
        with conn_or_cur.cursor() as cur:
            count = run(cur)
        conn_or_cur.commit()
        return count
    return run(conn_or_cur)


def seed_and_audit_all_target_companies(conn_or_cur) -> Dict[str, Any]:
    """
    Audits all companies currently in the database and pre-seeds all target
    companies from config/target_companies.json with verified branding.
    Accepts either a connection or cursor.
    """
    if hasattr(conn_or_cur, "cursor"):
        with conn_or_cur.cursor() as cur:
            res = _seed_and_audit(cur)
        conn_or_cur.commit()
        return res
    return _seed_and_audit(conn_or_cur)


def _seed_and_audit(cur) -> Dict[str, Any]:
    results = {
        "audited_count": 0,
        "verified_count": 0,
        "unresolved_companies": [],
    }

    # 1. Audit companies currently in the database
    cur.execute("SELECT id, name, logo_url, logo_status, logo_data FROM companies ORDER BY id;")
    db_companies = cur.fetchall()

    for cid, cname, current_logo, current_status, current_data in db_companies:
        results["audited_count"] += 1
        if invalidate_rejected_logo(cur, cid, cname, current_logo, current_data):
            current_logo, current_status, current_data = None, "unresolved", None
        # A company with a verified logo but no website (Braze) gets its curated official website; an existing one is kept.
        website = known_company_website(cname)
        if website:
            cur.execute("UPDATE companies SET website_url = %s, updated_at = NOW() WHERE id = %s AND website_url IS NULL;", (website, cid))
        # Keep verified DB-backed assets even if a later runtime lacks the local file, but refresh
        # them when the catalog now ships a corrected file (e.g. a re-issued logo).
        if current_status == "verified" and current_logo and current_logo.startswith("/api/company-logos/"):
            refresh_persisted_logo_if_stale(cur, cid, cname, current_data)
            results["verified_count"] += 1
            continue
        branding = resolve_company_branding(cname, cur=None)
        if branding["logo_status"] != "verified" and current_status == "verified":
            results["verified_count"] += 1
            continue
        cur.execute(
            """
            UPDATE companies
            SET logo_url = %s,
                logo_source_url = %s,
                logo_status = %s,
                website_url = COALESCE(%s, website_url),
                updated_at = NOW()
            WHERE id = %s;
            """,
            (
                branding["logo_url"],
                branding["logo_source_url"],
                branding["logo_status"],
                branding["website_url"],
                cid,
            ),
        )
        persist_logo_asset(cur, cid, branding)
        if branding["logo_status"] == "verified":
            results["verified_count"] += 1
        else:
            results["unresolved_companies"].append(cname)

    # 2. Seed all target companies from config/target_companies.json
    config_path = PROJECT_ROOT / "config" / "target_companies.json"
    if config_path.is_file():
        with open(config_path) as fp:
            targets = json.load(fp)

        for target in targets:
            name = target["name"]
            ats = target.get("ats")
            ident = target.get("identifier")
            cid, created = get_or_create_company_with_branding(cur, name, ats_type=ats, identifier=ident)
            if created:
                results["audited_count"] += 1

    if hasattr(cur, "connection") and cur.connection:
        cur.connection.commit()

    return results


def invalidate_rejected_logo(cur, company_id: int, company_name: str, url: Optional[str], stored: Optional[bytes]) -> bool:
    """Retire a proven incorrect asset while preserving unrelated verified branding."""
    rejected = REJECTED_COMPANY_LOGOS.get(normalize_company_name(company_name))
    if not rejected:
        return False
    bad_bytes = stored is not None and hashlib.sha256(bytes(stored)).hexdigest() == rejected["sha256"]
    if url != rejected["url"] and not bad_bytes:
        return False
    cur.execute(
        """UPDATE companies SET logo_url = NULL, logo_source_url = NULL, logo_status = 'unresolved',
           logo_data = NULL, logo_content_type = NULL, website_url = COALESCE(website_url, %s),
           updated_at = NOW() WHERE id = %s""",
        (rejected["website_url"], company_id),
    )
    return True


def refresh_persisted_logo_if_stale(cur, company_id: int, company_name: str, stored: Optional[bytes]) -> bool:
    """
    Re-persists a company's logo bytes when the curated catalog file differs from what the database
    holds (or the database holds nothing). Returns True if the stored logo was replaced.
    Only catalog-backed local files are considered; companies without one are left alone.
    """
    branding = resolve_company_branding(company_name)
    url = branding.get("logo_url") or ""
    if branding.get("logo_status") != "verified" or not url.startswith("/logos/"):
        return False
    asset = (LOGOS_DIR / url.removeprefix("/logos/")).resolve()
    if not asset.is_relative_to(LOGOS_DIR.resolve()) or not asset.is_file():
        return False
    if stored is not None and bytes(stored) == asset.read_bytes():
        return False
    cur.execute(
        "UPDATE companies SET logo_source_url = %s, logo_status = 'verified', website_url = COALESCE(%s, website_url), updated_at = NOW() WHERE id = %s",
        (branding.get("logo_source_url"), branding.get("website_url"), company_id),
    )
    persist_logo_asset(cur, company_id, branding)
    return True


def persist_logo_asset(cur, company_id: int, branding: dict) -> None:
    """Copy verified local bytes to PostgreSQL; worker disks are not durable hosting."""
    url = branding.get("logo_url") or ""
    if branding.get("logo_status") != "verified" or not url.startswith("/logos/"):
        return
    asset = (LOGOS_DIR / url.removeprefix("/logos/")).resolve()
    if not asset.is_relative_to(LOGOS_DIR.resolve()) or not asset.is_file():
        return
    mime = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(asset.suffix.lower())
    data = asset.read_bytes()
    if not mime or not data or len(data) > 2_000_000:
        return
    cur.execute(
        "UPDATE companies SET logo_data = %s, logo_content_type = %s, logo_url = %s WHERE id = %s",
        (data, mime, f"/api/company-logos/{company_id}", company_id),
    )
