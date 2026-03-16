"""Persistent credential store and prerequisites parser.

Three-layer credential architecture:
  Layer 1: Persistent store at project root (credentials.env) — accumulates across runs
  Layer 2: System environment variables (os.environ) — developer's existing shell config
  Layer 3: Interactive collection (CLI / Dashboard) — only for what's still missing

Includes an alias table so that GOOGLE_API_KEY, GOOGLE_MAPS_API_KEY, etc.
all resolve to the same underlying credential value.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Credential Validation
# ---------------------------------------------------------------------------

# Format patterns for known key types
_FORMAT_PATTERNS: dict[str, re.Pattern[str]] = {
    "OPENAI_API_KEY": re.compile(r"^sk-"),
    "ANTHROPIC_API_KEY": re.compile(r"^sk-ant-"),
    "GITHUB_TOKEN": re.compile(r"^(ghp_|github_pat_)"),
    "SLACK_BOT_TOKEN": re.compile(r"^xoxb-"),
    "SLACK_SIGNING_SECRET": re.compile(r"^[0-9a-f]{32}$"),
}

# Human-readable format hints
_FORMAT_HINTS: dict[str, str] = {
    "OPENAI_API_KEY": "must start with 'sk-'",
    "ANTHROPIC_API_KEY": "must start with 'sk-ant-'",
    "GITHUB_TOKEN": "must start with 'ghp_' or 'github_pat_'",
    "SLACK_BOT_TOKEN": "must start with 'xoxb-'",
    "SLACK_SIGNING_SECRET": "must be 32 lowercase hex characters",
}


# ---------------------------------------------------------------------------
# Credential Alias Table
# ---------------------------------------------------------------------------
# Maps variant names → canonical name.  When a project requests any variant,
# the system looks up the canonical name in the credential store / env.
# Add new rows as AI-generated names are discovered.

_CANONICAL_ALIASES: dict[str, str] = {
    # -----------------------------------------------------------------------
    # AI / LLM Services
    # -----------------------------------------------------------------------

    # OpenAI
    "OPENAI_KEY": "OPENAI_API_KEY",
    "OPEN_AI_KEY": "OPENAI_API_KEY",
    "OPEN_AI_API_KEY": "OPENAI_API_KEY",
    "OPENAI_SECRET_KEY": "OPENAI_API_KEY",
    "OPENAI_ORG_ID": "OPENAI_ORGANIZATION",
    "OPENAI_ORG": "OPENAI_ORGANIZATION",

    # Anthropic
    "ANTHROPIC_KEY": "ANTHROPIC_API_KEY",
    "CLAUDE_API_KEY": "ANTHROPIC_API_KEY",
    "CLAUDE_KEY": "ANTHROPIC_API_KEY",

    # Google — Gemini / Vertex / Maps / Cloud
    "GOOGLE_API_KEY": "GOOGLE_API_KEY",
    "GOOGLE_MAPS_API_KEY": "GOOGLE_API_KEY",
    "GOOGLE_MAPS_KEY": "GOOGLE_API_KEY",
    "GOOGLE_CLOUD_API_KEY": "GOOGLE_API_KEY",
    "GOOGLE_CLOUD_KEY": "GOOGLE_API_KEY",
    "GOOGLE_GEMINI_API_KEY": "GOOGLE_API_KEY",
    "GEMINI_API_KEY": "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS_JSON": "GOOGLE_APPLICATION_CREDENTIALS",
    "GCP_CREDENTIALS": "GOOGLE_APPLICATION_CREDENTIALS",
    "GCP_SERVICE_ACCOUNT": "GOOGLE_APPLICATION_CREDENTIALS",
    "GCP_PROJECT": "GOOGLE_CLOUD_PROJECT",
    "GCLOUD_PROJECT": "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_PROJECT_ID": "GOOGLE_CLOUD_PROJECT",

    # Azure OpenAI
    "AZURE_OPENAI_KEY": "AZURE_OPENAI_API_KEY",
    "AZURE_API_KEY": "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT_URL": "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_BASE_URL": "AZURE_OPENAI_ENDPOINT",

    # Cohere
    "COHERE_KEY": "COHERE_API_KEY",
    "CO_API_KEY": "COHERE_API_KEY",

    # Mistral
    "MISTRAL_KEY": "MISTRAL_API_KEY",

    # Groq
    "GROQ_KEY": "GROQ_API_KEY",

    # Together AI
    "TOGETHER_KEY": "TOGETHER_API_KEY",
    "TOGETHERAI_API_KEY": "TOGETHER_API_KEY",
    "TOGETHER_AI_KEY": "TOGETHER_API_KEY",

    # Perplexity
    "PERPLEXITY_KEY": "PERPLEXITY_API_KEY",
    "PPLX_API_KEY": "PERPLEXITY_API_KEY",

    # Fireworks AI
    "FIREWORKS_KEY": "FIREWORKS_API_KEY",
    "FIREWORKS_AI_KEY": "FIREWORKS_API_KEY",

    # DeepSeek
    "DEEPSEEK_KEY": "DEEPSEEK_API_KEY",

    # Hugging Face
    "HF_TOKEN": "HUGGINGFACE_API_KEY",
    "HF_API_KEY": "HUGGINGFACE_API_KEY",
    "HUGGINGFACE_TOKEN": "HUGGINGFACE_API_KEY",
    "HUGGING_FACE_API_KEY": "HUGGINGFACE_API_KEY",
    "HF_API_TOKEN": "HUGGINGFACE_API_KEY",

    # Replicate
    "REPLICATE_KEY": "REPLICATE_API_TOKEN",
    "REPLICATE_API_KEY": "REPLICATE_API_TOKEN",
    "REPLICATE_TOKEN": "REPLICATE_API_TOKEN",

    # Stability AI
    "STABILITY_KEY": "STABILITY_API_KEY",
    "STABILITY_AI_KEY": "STABILITY_API_KEY",

    # ElevenLabs
    "ELEVENLABS_KEY": "ELEVENLABS_API_KEY",
    "ELEVEN_LABS_API_KEY": "ELEVENLABS_API_KEY",
    "ELEVEN_LABS_KEY": "ELEVENLABS_API_KEY",

    # Voyage AI (embeddings)
    "VOYAGE_KEY": "VOYAGE_API_KEY",

    # -----------------------------------------------------------------------
    # Vector Databases / Search
    # -----------------------------------------------------------------------

    # Pinecone
    "PINECONE_KEY": "PINECONE_API_KEY",
    "PINECONE_TOKEN": "PINECONE_API_KEY",

    # Weaviate
    "WEAVIATE_KEY": "WEAVIATE_API_KEY",
    "WEAVIATE_TOKEN": "WEAVIATE_API_KEY",

    # Qdrant
    "QDRANT_KEY": "QDRANT_API_KEY",

    # ChromaDB (cloud)
    "CHROMA_KEY": "CHROMA_API_KEY",
    "CHROMA_TOKEN": "CHROMA_API_KEY",

    # Algolia
    "ALGOLIA_KEY": "ALGOLIA_API_KEY",
    "ALGOLIA_APP": "ALGOLIA_APP_ID",
    "ALGOLIA_APPLICATION_ID": "ALGOLIA_APP_ID",

    # -----------------------------------------------------------------------
    # Cloud Platforms
    # -----------------------------------------------------------------------

    # AWS
    "AWS_KEY": "AWS_ACCESS_KEY_ID",
    "AWS_ACCESS_KEY": "AWS_ACCESS_KEY_ID",
    "AWS_SECRET": "AWS_SECRET_ACCESS_KEY",
    "AWS_SECRET_KEY": "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION": "AWS_SESSION_TOKEN",
    "AWS_REGION_NAME": "AWS_DEFAULT_REGION",
    "AWS_REGION": "AWS_DEFAULT_REGION",

    # Azure (general)
    "AZURE_KEY": "AZURE_SUBSCRIPTION_KEY",
    "AZURE_API": "AZURE_SUBSCRIPTION_KEY",
    "AZURE_TENANT": "AZURE_TENANT_ID",
    "AZURE_CLIENT": "AZURE_CLIENT_ID",
    "AZURE_SECRET": "AZURE_CLIENT_SECRET",

    # Cloudflare
    "CF_API_KEY": "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_KEY": "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_TOKEN": "CLOUDFLARE_API_TOKEN",
    "CF_TOKEN": "CLOUDFLARE_API_TOKEN",
    "CF_ACCOUNT_ID": "CLOUDFLARE_ACCOUNT_ID",

    # Vercel
    "VERCEL_KEY": "VERCEL_TOKEN",
    "VERCEL_API_TOKEN": "VERCEL_TOKEN",

    # Netlify
    "NETLIFY_KEY": "NETLIFY_AUTH_TOKEN",
    "NETLIFY_TOKEN": "NETLIFY_AUTH_TOKEN",

    # Railway
    "RAILWAY_KEY": "RAILWAY_TOKEN",
    "RAILWAY_API_TOKEN": "RAILWAY_TOKEN",

    # Fly.io
    "FLY_TOKEN": "FLY_API_TOKEN",
    "FLY_KEY": "FLY_API_TOKEN",

    # -----------------------------------------------------------------------
    # Code / Version Control
    # -----------------------------------------------------------------------

    # GitHub
    "GITHUB_TOKEN": "GITHUB_TOKEN",
    "GITHUB_API_TOKEN": "GITHUB_TOKEN",
    "GITHUB_ACCESS_TOKEN": "GITHUB_TOKEN",
    "GH_TOKEN": "GITHUB_TOKEN",
    "GITHUB_PAT": "GITHUB_TOKEN",

    # GitLab
    "GITLAB_KEY": "GITLAB_TOKEN",
    "GITLAB_API_TOKEN": "GITLAB_TOKEN",
    "GITLAB_ACCESS_TOKEN": "GITLAB_TOKEN",
    "GITLAB_PAT": "GITLAB_TOKEN",

    # Bitbucket
    "BITBUCKET_KEY": "BITBUCKET_TOKEN",
    "BITBUCKET_API_TOKEN": "BITBUCKET_TOKEN",

    # -----------------------------------------------------------------------
    # Databases / BaaS
    # -----------------------------------------------------------------------

    # Supabase
    "SUPABASE_KEY": "SUPABASE_ANON_KEY",
    "SUPABASE_API_KEY": "SUPABASE_ANON_KEY",
    "SUPABASE_SECRET": "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_SERVICE_KEY": "SUPABASE_SERVICE_ROLE_KEY",

    # Firebase
    "FIREBASE_KEY": "FIREBASE_API_KEY",
    "FIREBASE_CONFIG": "FIREBASE_API_KEY",
    "FIREBASE_SERVICE_ACCOUNT_KEY": "FIREBASE_SERVICE_ACCOUNT",
    "FIREBASE_SA": "FIREBASE_SERVICE_ACCOUNT",

    # MongoDB Atlas
    "MONGO_URI": "MONGODB_URI",
    "MONGODB_URL": "MONGODB_URI",
    "MONGO_URL": "MONGODB_URI",
    "MONGO_CONNECTION_STRING": "MONGODB_URI",

    # PostgreSQL
    "POSTGRES_URL": "DATABASE_URL",
    "POSTGRES_URI": "DATABASE_URL",
    "PG_URL": "DATABASE_URL",
    "PG_CONNECTION_STRING": "DATABASE_URL",
    "POSTGRESQL_URL": "DATABASE_URL",

    # Redis
    "REDIS_URI": "REDIS_URL",
    "REDIS_CONNECTION": "REDIS_URL",
    "REDIS_CONNECTION_STRING": "REDIS_URL",

    # PlanetScale
    "PLANETSCALE_URL": "PLANETSCALE_DATABASE_URL",
    "PLANETSCALE_URI": "PLANETSCALE_DATABASE_URL",

    # Neon
    "NEON_URL": "NEON_DATABASE_URL",
    "NEON_URI": "NEON_DATABASE_URL",
    "NEON_CONNECTION_STRING": "NEON_DATABASE_URL",

    # Upstash (Redis / Kafka)
    "UPSTASH_REDIS_KEY": "UPSTASH_REDIS_REST_TOKEN",
    "UPSTASH_TOKEN": "UPSTASH_REDIS_REST_TOKEN",

    # Convex
    "CONVEX_KEY": "CONVEX_DEPLOY_KEY",

    # -----------------------------------------------------------------------
    # Auth / Identity
    # -----------------------------------------------------------------------

    # Auth0
    "AUTH0_KEY": "AUTH0_CLIENT_SECRET",
    "AUTH0_API_KEY": "AUTH0_CLIENT_SECRET",

    # Clerk
    "CLERK_KEY": "CLERK_SECRET_KEY",
    "CLERK_API_KEY": "CLERK_SECRET_KEY",

    # Supabase Auth (uses SUPABASE_ANON_KEY above)

    # NextAuth / Auth.js
    "NEXTAUTH_KEY": "NEXTAUTH_SECRET",
    "AUTH_SECRET": "NEXTAUTH_SECRET",

    # -----------------------------------------------------------------------
    # Payment / Commerce
    # -----------------------------------------------------------------------

    # Stripe
    "STRIPE_API_KEY": "STRIPE_SECRET_KEY",
    "STRIPE_KEY": "STRIPE_SECRET_KEY",
    "STRIPE_PK": "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_PUBLIC_KEY": "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK": "STRIPE_WEBHOOK_SECRET",

    # PayPal
    "PAYPAL_KEY": "PAYPAL_CLIENT_SECRET",
    "PAYPAL_SECRET": "PAYPAL_CLIENT_SECRET",
    "PAYPAL_API_KEY": "PAYPAL_CLIENT_SECRET",

    # Lemon Squeezy
    "LEMONSQUEEZY_KEY": "LEMONSQUEEZY_API_KEY",
    "LEMON_SQUEEZY_KEY": "LEMONSQUEEZY_API_KEY",

    # -----------------------------------------------------------------------
    # Communication / Messaging
    # -----------------------------------------------------------------------

    # Slack
    "SLACK_TOKEN": "SLACK_BOT_TOKEN",
    "SLACK_API_TOKEN": "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN": "SLACK_BOT_TOKEN",
    "SLACK_SIGNING_KEY": "SLACK_SIGNING_SECRET",
    "SLACK_WEBHOOK": "SLACK_WEBHOOK_URL",

    # Discord
    "DISCORD_KEY": "DISCORD_BOT_TOKEN",
    "DISCORD_TOKEN": "DISCORD_BOT_TOKEN",
    "DISCORD_API_KEY": "DISCORD_BOT_TOKEN",
    "DISCORD_SECRET": "DISCORD_CLIENT_SECRET",

    # Twilio
    "TWILIO_KEY": "TWILIO_AUTH_TOKEN",
    "TWILIO_API_KEY": "TWILIO_AUTH_TOKEN",
    "TWILIO_SECRET": "TWILIO_AUTH_TOKEN",

    # SendGrid
    "SENDGRID_KEY": "SENDGRID_API_KEY",
    "SENDGRID_TOKEN": "SENDGRID_API_KEY",

    # Resend
    "RESEND_KEY": "RESEND_API_KEY",
    "RESEND_TOKEN": "RESEND_API_KEY",

    # Postmark
    "POSTMARK_KEY": "POSTMARK_API_TOKEN",
    "POSTMARK_API_KEY": "POSTMARK_API_TOKEN",

    # Mailgun
    "MAILGUN_KEY": "MAILGUN_API_KEY",

    # Telegram
    "TELEGRAM_KEY": "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_TOKEN": "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_API_KEY": "TELEGRAM_BOT_TOKEN",

    # -----------------------------------------------------------------------
    # Notion / Productivity
    # -----------------------------------------------------------------------

    # Notion
    "NOTION_API_KEY": "NOTION_TOKEN",
    "NOTION_KEY": "NOTION_TOKEN",
    "NOTION_INTEGRATION_TOKEN": "NOTION_TOKEN",
    "NOTION_SECRET": "NOTION_TOKEN",

    # Airtable
    "AIRTABLE_KEY": "AIRTABLE_API_KEY",
    "AIRTABLE_TOKEN": "AIRTABLE_API_KEY",
    "AIRTABLE_PAT": "AIRTABLE_API_KEY",

    # Linear
    "LINEAR_TOKEN": "LINEAR_API_KEY",
    "LINEAR_KEY": "LINEAR_API_KEY",

    # -----------------------------------------------------------------------
    # Analytics / Monitoring
    # -----------------------------------------------------------------------

    # Sentry
    "SENTRY_KEY": "SENTRY_DSN",
    "SENTRY_TOKEN": "SENTRY_AUTH_TOKEN",

    # Segment
    "SEGMENT_KEY": "SEGMENT_WRITE_KEY",
    "SEGMENT_API_KEY": "SEGMENT_WRITE_KEY",

    # Mixpanel
    "MIXPANEL_KEY": "MIXPANEL_TOKEN",
    "MIXPANEL_API_KEY": "MIXPANEL_TOKEN",

    # PostHog
    "POSTHOG_KEY": "POSTHOG_API_KEY",
    "POSTHOG_TOKEN": "POSTHOG_API_KEY",

    # Datadog
    "DD_KEY": "DATADOG_API_KEY",
    "DD_API_KEY": "DATADOG_API_KEY",
    "DATADOG_KEY": "DATADOG_API_KEY",

    # -----------------------------------------------------------------------
    # Media / Storage
    # -----------------------------------------------------------------------

    # Cloudinary
    "CLOUDINARY_KEY": "CLOUDINARY_API_KEY",
    "CLOUDINARY_SECRET": "CLOUDINARY_API_SECRET",

    # Uploadthing
    "UPLOADTHING_KEY": "UPLOADTHING_SECRET",
    "UPLOADTHING_TOKEN": "UPLOADTHING_SECRET",

    # AWS S3 (uses AWS_ACCESS_KEY_ID above)
    "S3_BUCKET": "AWS_S3_BUCKET",
    "S3_BUCKET_NAME": "AWS_S3_BUCKET",

    # -----------------------------------------------------------------------
    # Maps / Geolocation
    # -----------------------------------------------------------------------

    # Mapbox
    "MAPBOX_KEY": "MAPBOX_ACCESS_TOKEN",
    "MAPBOX_API_KEY": "MAPBOX_ACCESS_TOKEN",
    "MAPBOX_TOKEN": "MAPBOX_ACCESS_TOKEN",

    # -----------------------------------------------------------------------
    # CMS / Content
    # -----------------------------------------------------------------------

    # Contentful
    "CONTENTFUL_KEY": "CONTENTFUL_ACCESS_TOKEN",
    "CONTENTFUL_TOKEN": "CONTENTFUL_ACCESS_TOKEN",

    # Sanity
    "SANITY_KEY": "SANITY_API_TOKEN",
    "SANITY_TOKEN": "SANITY_API_TOKEN",

    # Strapi
    "STRAPI_KEY": "STRAPI_API_TOKEN",
    "STRAPI_TOKEN": "STRAPI_API_TOKEN",

    # -----------------------------------------------------------------------
    # Web Scraping / Data
    # -----------------------------------------------------------------------

    # Browserless
    "BROWSERLESS_KEY": "BROWSERLESS_API_KEY",
    "BROWSERLESS_TOKEN": "BROWSERLESS_API_KEY",

    # ScrapingBee
    "SCRAPINGBEE_KEY": "SCRAPINGBEE_API_KEY",

    # Serper (Google Search API)
    "SERPER_KEY": "SERPER_API_KEY",

    # SerpAPI
    "SERPAPI_KEY": "SERPAPI_API_KEY",
    "SERP_API_KEY": "SERPAPI_API_KEY",

    # Tavily (AI search)
    "TAVILY_KEY": "TAVILY_API_KEY",

    # -----------------------------------------------------------------------
    # LangChain / AI Frameworks
    # -----------------------------------------------------------------------

    # LangChain / LangSmith
    "LANGCHAIN_KEY": "LANGCHAIN_API_KEY",
    "LANGSMITH_KEY": "LANGCHAIN_API_KEY",
    "LANGSMITH_API_KEY": "LANGCHAIN_API_KEY",

    # Weights & Biases
    "WANDB_TOKEN": "WANDB_API_KEY",
    "WANDB_KEY": "WANDB_API_KEY",

    # -----------------------------------------------------------------------
    # Misc / Utility
    # -----------------------------------------------------------------------

    # OpenWeatherMap
    "OPENWEATHER_KEY": "OPENWEATHERMAP_API_KEY",
    "OPENWEATHERMAP_KEY": "OPENWEATHERMAP_API_KEY",
    "OWM_API_KEY": "OPENWEATHERMAP_API_KEY",

    # Rapid API
    "RAPIDAPI_KEY": "RAPID_API_KEY",
    "X_RAPIDAPI_KEY": "RAPID_API_KEY",

    # Ngrok
    "NGROK_TOKEN": "NGROK_AUTHTOKEN",
    "NGROK_KEY": "NGROK_AUTHTOKEN",
    "NGROK_AUTH": "NGROK_AUTHTOKEN",

    # Docker Hub
    "DOCKER_TOKEN": "DOCKER_HUB_TOKEN",
    "DOCKER_KEY": "DOCKER_HUB_TOKEN",
    "DOCKERHUB_TOKEN": "DOCKER_HUB_TOKEN",

    # NPM
    "NPM_KEY": "NPM_TOKEN",
    "NPM_API_TOKEN": "NPM_TOKEN",

    # Hetzner
    "HETZNER_KEY": "HETZNER_API_TOKEN",
    "HETZNER_TOKEN": "HETZNER_API_TOKEN",

    # DigitalOcean
    "DO_TOKEN": "DIGITALOCEAN_TOKEN",
    "DO_API_TOKEN": "DIGITALOCEAN_TOKEN",
    "DIGITALOCEAN_KEY": "DIGITALOCEAN_TOKEN",
    "DIGITALOCEAN_API_KEY": "DIGITALOCEAN_TOKEN",
}

# Build reverse index: canonical → set of all variant names (including itself)
_CANONICAL_TO_VARIANTS: dict[str, set[str]] = {}
for _variant, _canonical in _CANONICAL_ALIASES.items():
    _CANONICAL_TO_VARIANTS.setdefault(_canonical, set()).add(_variant)
    _CANONICAL_TO_VARIANTS[_canonical].add(_canonical)


# ---------------------------------------------------------------------------
# Environment Library Catalog
# ---------------------------------------------------------------------------
# Organized listing of all canonical env vars the system knows about,
# grouped by service category for display / template generation.

_ENV_LIBRARY_CATEGORIES: dict[str, list[str]] = {
    "AI / LLM Services": sorted({
        "OPENAI_API_KEY", "OPENAI_ORGANIZATION", "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT",
        "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT",
        "COHERE_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY",
        "TOGETHER_API_KEY", "PERPLEXITY_API_KEY", "FIREWORKS_API_KEY",
        "DEEPSEEK_API_KEY", "HUGGINGFACE_API_KEY", "REPLICATE_API_TOKEN",
        "STABILITY_API_KEY", "ELEVENLABS_API_KEY", "VOYAGE_API_KEY",
    }),
    "Vector Databases / Search": sorted({
        "PINECONE_API_KEY", "WEAVIATE_API_KEY", "QDRANT_API_KEY",
        "CHROMA_API_KEY", "ALGOLIA_API_KEY", "ALGOLIA_APP_ID",
    }),
    "Cloud Platforms": sorted({
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
        "AZURE_SUBSCRIPTION_KEY", "AZURE_TENANT_ID", "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID",
        "VERCEL_TOKEN", "NETLIFY_AUTH_TOKEN", "RAILWAY_TOKEN", "FLY_API_TOKEN",
    }),
    "Code / Version Control": sorted({
        "GITHUB_TOKEN", "GITLAB_TOKEN", "BITBUCKET_TOKEN",
    }),
    "Databases / BaaS": sorted({
        "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_URL",
        "FIREBASE_API_KEY", "FIREBASE_SERVICE_ACCOUNT",
        "MONGODB_URI", "DATABASE_URL", "REDIS_URL",
        "PLANETSCALE_DATABASE_URL", "NEON_DATABASE_URL",
        "UPSTASH_REDIS_REST_TOKEN", "CONVEX_DEPLOY_KEY",
    }),
    "Auth / Identity": sorted({
        "AUTH0_CLIENT_SECRET", "AUTH0_CLIENT_ID", "AUTH0_DOMAIN",
        "CLERK_SECRET_KEY", "CLERK_PUBLISHABLE_KEY",
        "NEXTAUTH_SECRET", "NEXTAUTH_URL",
    }),
    "Payment / Commerce": sorted({
        "STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET",
        "PAYPAL_CLIENT_SECRET", "PAYPAL_CLIENT_ID",
        "LEMONSQUEEZY_API_KEY",
    }),
    "Communication / Messaging": sorted({
        "SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_WEBHOOK_URL",
        "DISCORD_BOT_TOKEN", "DISCORD_CLIENT_SECRET",
        "TWILIO_AUTH_TOKEN", "TWILIO_ACCOUNT_SID",
        "SENDGRID_API_KEY", "RESEND_API_KEY",
        "POSTMARK_API_TOKEN", "MAILGUN_API_KEY",
        "TELEGRAM_BOT_TOKEN",
    }),
    "Notion / Productivity": sorted({
        "NOTION_TOKEN", "AIRTABLE_API_KEY", "LINEAR_API_KEY",
    }),
    "Analytics / Monitoring": sorted({
        "SENTRY_DSN", "SENTRY_AUTH_TOKEN",
        "SEGMENT_WRITE_KEY", "MIXPANEL_TOKEN",
        "POSTHOG_API_KEY", "DATADOG_API_KEY",
    }),
    "Media / Storage": sorted({
        "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET",
        "UPLOADTHING_SECRET", "AWS_S3_BUCKET",
    }),
    "Maps / Geolocation": sorted({
        "MAPBOX_ACCESS_TOKEN",
    }),
    "CMS / Content": sorted({
        "CONTENTFUL_ACCESS_TOKEN", "SANITY_API_TOKEN", "STRAPI_API_TOKEN",
    }),
    "Web Scraping / Data": sorted({
        "BROWSERLESS_API_KEY", "SCRAPINGBEE_API_KEY",
        "SERPER_API_KEY", "SERPAPI_API_KEY", "TAVILY_API_KEY",
    }),
    "AI Frameworks / MLOps": sorted({
        "LANGCHAIN_API_KEY", "WANDB_API_KEY",
    }),
    "Misc / Utility": sorted({
        "OPENWEATHERMAP_API_KEY", "RAPID_API_KEY",
        "NGROK_AUTHTOKEN", "DOCKER_HUB_TOKEN", "NPM_TOKEN",
        "HETZNER_API_TOKEN", "DIGITALOCEAN_TOKEN",
    }),
}

# Total count for quick reference
ENV_LIBRARY_SIZE: int = sum(len(v) for v in _ENV_LIBRARY_CATEGORIES.values())


def list_environment_library() -> dict[str, list[str]]:
    """Return the full environment library catalog.

    Returns a dict mapping category name to a sorted list of canonical
    env var names recognized by the credential store.  Each canonical name
    may have multiple aliases (see ``get_aliases_for``).

    Example::

        for category, vars in list_environment_library().items():
            print(f"\\n{category}:")
            for v in vars:
                print(f"  {v}")
    """
    return dict(_ENV_LIBRARY_CATEGORIES)


def get_aliases_for(canonical_name: str) -> set[str]:
    """Return all known alias names for a given canonical env var.

    If the name is unknown, returns an empty set.
    """
    return set(_CANONICAL_TO_VARIANTS.get(canonical_name, set()))


def resolve_credential(
    requested_name: str,
    available: dict[str, str],
) -> str:
    """Look up a credential value, checking all known aliases.

    If ``requested_name`` is not directly in ``available``, checks whether any
    alias of the same canonical key is present.

    Returns the value if found, or empty string.
    """
    # Direct hit
    val = available.get(requested_name, "")
    if val:
        return val

    # Resolve via alias table
    canonical = _CANONICAL_ALIASES.get(requested_name)
    if canonical is None:
        return ""

    # Check canonical name itself
    val = available.get(canonical, "")
    if val:
        return val

    # Check all sibling variants
    for variant in _CANONICAL_TO_VARIANTS.get(canonical, ()):
        val = available.get(variant, "")
        if val:
            return val

    return ""


def _format_check(env_var: str, value: str) -> str | None:
    """Return error message if format is wrong, None if OK."""
    pattern = _FORMAT_PATTERNS.get(env_var)
    if pattern is None:
        return None  # No known format — skip
    if not pattern.match(value):
        hint = _FORMAT_HINTS.get(env_var, "invalid format")
        return f"Format error: {hint}"
    return None


def _do_ping(env_var: str, value: str) -> str | None:
    """Synchronous ping check. Returns error message or None on success.

    Called via run_in_executor to avoid blocking the event loop.
    """
    try:
        if env_var == "OPENAI_API_KEY":
            req = urllib.request.Request(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {value}"},
            )
            urllib.request.urlopen(req, timeout=4)
            return None

        elif env_var == "ANTHROPIC_API_KEY":
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": value,
                    "anthropic-version": "2023-06-01",
                },
            )
            urllib.request.urlopen(req, timeout=4)
            return None

        elif env_var == "GITHUB_TOKEN":
            req = urllib.request.Request(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {value}",
                    "Accept": "application/vnd.github+json",
                },
            )
            urllib.request.urlopen(req, timeout=4)
            return None

        elif env_var == "SLACK_BOT_TOKEN":
            data = urllib.parse.urlencode({"token": value}).encode()
            req = urllib.request.Request(
                "https://slack.com/api/auth.test",
                data=data,
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=4)
            body = json.loads(resp.read())
            if not body.get("ok"):
                return f"Slack API error: {body.get('error', 'unknown')}"
            return None

        else:
            return None  # No ping for this key type

    except urllib.error.HTTPError as e:
        status = e.code
        if status == 401:
            return "Authentication failed: invalid or expired key"
        elif status == 403:
            return "Authorization failed: key lacks required permissions"
        else:
            return f"API returned HTTP {status}"
    except urllib.error.URLError:
        logger.debug("Network error pinging %s endpoint — skipping ping check", env_var)
        return None  # Cannot reach server, do not penalise the key
    except Exception:
        logger.debug("Unexpected ping error for %s", env_var, exc_info=True)
        return None  # Don't penalise the key on unexpected errors


# Keys that support network ping validation
_PINGABLE_KEYS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "SLACK_BOT_TOKEN"}


async def validate_credential(env_var: str, value: str) -> dict:
    """Validate a single credential.

    Returns:
        {
            "valid": bool,
            "error": str | None,     # human-readable error on failure
            "warning": str | None,   # non-blocking warning
            "skipped": bool,         # True if no validator exists for this key type
        }
    """
    result = {"valid": True, "error": None, "warning": None, "skipped": False}

    # Check if we have any validator for this key
    has_format = env_var in _FORMAT_PATTERNS
    has_ping = env_var in _PINGABLE_KEYS

    if not has_format and not has_ping:
        result["skipped"] = True
        return result

    # Step 1: Format check (instant)
    fmt_error = _format_check(env_var, value)
    if fmt_error:
        result["valid"] = False
        result["error"] = fmt_error
        return result

    # Step 2: Network ping (if available)
    if has_ping:
        loop = asyncio.get_running_loop()
        try:
            ping_error = await asyncio.wait_for(
                loop.run_in_executor(None, _do_ping, env_var, value),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            result["warning"] = "Validation timed out (5s) — accepted anyway"
            return result

        if ping_error:
            result["valid"] = False
            result["error"] = ping_error
            return result

    return result


def load_persistent(path: Path) -> dict[str, str]:
    """Load KEY=VALUE pairs from persistent credentials.env.

    Skips blank lines and comments (lines starting with #).
    Returns empty dict if file does not exist.
    """
    if not path.exists():
        return {}

    creds: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes (KEY="value" or KEY='value')
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key:
                creds[key] = value
    return creds


def load_all_credentials(
    persistent_path: Path,
    needed_vars: set[str] | None = None,
) -> dict[str, str]:
    """Load credentials from persistent store + alias resolution + system environment.

    Lookup order for each needed var (first non-empty value wins):
      1. Persistent store (credentials.env) — exact name
      2. Persistent store — alias variants (e.g. GOOGLE_MAPS_API_KEY → GOOGLE_API_KEY)
      3. System environment — exact name
      4. System environment — alias variants

    Args:
        persistent_path: Path to persistent credentials.env file.
        needed_vars: If provided, check aliases and os.environ for these variable names.
            When None, only returns persistent store values (no env scan / alias resolution).

    Returns:
        Merged dict of credential name → value.
        Keys are the *requested* names (not canonical), so downstream code
        sees the exact variable name it asked for.
    """
    creds = load_persistent(persistent_path)

    if needed_vars is None:
        return creds

    for var in needed_vars:
        if var in creds and creds[var]:
            continue

        # Try alias resolution against persistent store
        value = resolve_credential(var, creds)
        if value:
            logger.info("Credential %s: resolved via alias from persistent store", var)
            creds[var] = value
            continue

        # Try exact name in system environment
        env_value = os.environ.get(var, "")
        if env_value:
            logger.info("Credential %s: found in system environment", var)
            creds[var] = env_value
            continue

        # Try alias resolution against system environment
        env_value = resolve_credential(var, dict(os.environ))
        if env_value:
            canonical = _CANONICAL_ALIASES.get(var, var)
            logger.info("Credential %s: resolved via alias from system environment (canonical: %s)", var, canonical)
            creds[var] = env_value

    return creds


def save_persistent(path: Path, new_creds: dict[str, str]) -> None:
    """Append new credentials to the persistent store.

    Only appends keys that don't already exist in the file.
    Creates the file if it doesn't exist.
    """
    existing = load_persistent(path)
    to_add = {k: v for k, v in new_creds.items() if k not in existing and v}

    if not to_add:
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    is_new_file = not path.exists() or path.stat().st_size == 0

    with path.open("a", encoding="utf-8") as f:
        if is_new_file:
            f.write("# Persistent credential store (auto-managed by ConfigGate)\n")
        for key, value in sorted(to_add.items()):
            f.write(f"{key}={value}\n")

    logger.info("Saved %d new credentials to persistent store", len(to_add))


def parse_prerequisites(technical_md: str) -> dict:
    """Extract Prerequisites Checklist from technical.md content.

    Parses the structured markdown format produced by the Technical Architect Agent.

    Returns:
        {
            "carrier": [{"name": "SLACK_BOT_TOKEN", "description": "...", "obtain": "..."}],
            "functional": [{"name": "OPENAI_API_KEY", "description": "...", "skip_module": "..."}],
            "dev": [{"name": "ngrok", "description": "..."}],
        }
    """
    result: dict[str, list[dict]] = {"carrier": [], "functional": [], "dev": []}

    # Find the Prerequisites Checklist section
    checklist_match = re.search(
        r"##\s*Prerequisites\s+Checklist(.*?)(?=\n##\s[^#]|\Z)",
        technical_md,
        re.DOTALL | re.IGNORECASE,
    )
    if not checklist_match:
        return result

    checklist_text = checklist_match.group(1)

    # Split into subsections by ### headers
    sections = re.split(r"###\s+", checklist_text)

    for section in sections:
        if not section.strip():
            continue

        # Determine category from section header
        header_lower = section.split("\n", 1)[0].lower()
        if "carrier" in header_lower:
            category = "carrier"
        elif "functional" in header_lower:
            category = "functional"
        elif "development" in header_lower or "dev" in header_lower:
            category = "dev"
        else:
            continue

        # Parse individual items: lines starting with "- [ ]" or "- [x]"
        items = re.findall(
            r"-\s*\[[ x]\]\s*\*\*(.+?)\*\*:\s*(.+?)(?=\n-\s*\[|\n###|\Z)",
            section,
            re.DOTALL,
        )

        for item_name, item_body in items:
            dep: dict[str, str] = {
                "name": item_name.strip(),
                "description": item_body.strip().split("\n")[0].strip(),
            }

            # Extract env var name from `VARIABLE_NAME` pattern
            env_match = re.search(r"Env\s*var:\s*`([^`]+)`", item_body)
            if env_match:
                dep["env_var"] = env_match.group(1).strip()

            # Extract obtain/install instructions
            obtain_match = re.search(r"Obtain:\s*(.+?)(?:\n|$)", item_body)
            if obtain_match:
                dep["obtain"] = obtain_match.group(1).strip()

            install_match = re.search(r"Install:\s*(.+?)(?:\n|$)", item_body)
            if install_match:
                dep["obtain"] = install_match.group(1).strip()

            # Extract skip info for functional deps
            skip_match = re.search(r"If\s+missing:\s*(.+?)(?:\n|$)", item_body)
            if skip_match:
                dep["skip_module"] = skip_match.group(1).strip()

            result[category].append(dep)

    return result


def diff_credentials(
    needed: dict[str, list[dict]], have: dict[str, str]
) -> dict:
    """Compare needed deps against what we have.

    Args:
        needed: Output from parse_prerequisites()
        have: Dict of env var name -> value from persistent store

    Returns:
        {
            "satisfied": [{"name": ..., "env_var": ..., "category": ...}],
            "missing_carrier": [{"name": ..., "env_var": ..., ...}],
            "missing_functional": [{"name": ..., "env_var": ..., ...}],
        }
    """
    result: dict[str, list[dict]] = {
        "satisfied": [],
        "missing_carrier": [],
        "missing_functional": [],
    }

    for category in ("carrier", "functional"):
        for dep in needed.get(category, []):
            env_var = dep.get("env_var", "")

            if not env_var:
                # No env var extracted — can't check or collect.
                # Carrier deps without env_var are still blockers (parser couldn't
                # extract the variable name, so we can't satisfy it).
                if category == "carrier":
                    logger.warning(
                        "Carrier dep '%s' has no env_var — treating as missing",
                        dep.get("name", "unknown"),
                    )
                    result["missing_carrier"].append(dep)
                # Functional deps without env_var are silently skipped (no way to
                # collect them, and they're optional anyway).
                continue

            # Check with alias resolution (e.g. GOOGLE_MAPS_API_KEY → GOOGLE_API_KEY)
            value = resolve_credential(env_var, have)
            if value:
                result["satisfied"].append({**dep, "category": category})
            elif category == "carrier":
                result["missing_carrier"].append(dep)
            else:
                result["missing_functional"].append(dep)

    return result


def generate_env_plan(
    slug: str,
    diff_result: dict,
    blocked: bool = False,
) -> str:
    """Generate environment-plan.md content from diff results.

    Args:
        slug: Project slug
        diff_result: Output from diff_credentials()
        blocked: Whether the project is blocked due to missing carrier deps

    Returns:
        Markdown content for environment-plan.md
    """
    lines = [
        f"# Environment Plan: {slug}",
        "",
    ]

    if blocked:
        lines.append("**Status: BLOCKED** — missing required carrier dependencies")
        lines.append("")

    # Satisfied credentials
    if diff_result["satisfied"]:
        lines.append("## Satisfied Dependencies")
        lines.append("")
        for dep in diff_result["satisfied"]:
            lines.append(
                f"- ✅ `{dep.get('env_var', 'N/A')}` — {dep['name']} ({dep['category']})"
            )
        lines.append("")

    # Missing carrier (blockers)
    if diff_result["missing_carrier"]:
        lines.append("## Missing Carrier Dependencies (REQUIRED)")
        lines.append("")
        for dep in diff_result["missing_carrier"]:
            status = "❌" if blocked else "✅"
            lines.append(
                f"- {status} `{dep.get('env_var', 'N/A')}` — {dep['name']}"
            )
            if dep.get("obtain"):
                lines.append(f"  - Obtain: {dep['obtain']}")
        lines.append("")

    # Missing functional (skippable)
    if diff_result["missing_functional"]:
        lines.append("## Missing Functional Dependencies (skipped)")
        lines.append("")
        for dep in diff_result["missing_functional"]:
            lines.append(
                f"- ⏭️ `{dep.get('env_var', 'N/A')}` — {dep['name']}"
            )
            if dep.get("skip_module"):
                lines.append(f"  - Skipped module: {dep['skip_module']}")
        lines.append("")

    return "\n".join(lines)
