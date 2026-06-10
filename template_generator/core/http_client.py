"""
http_client.py — Client HTTP singleton partagé entre TOUS les modules.

Un seul client httpx pour toute l'application :
  - Connection pooling optimisé
  - HTTP/2 activé
  - Timeouts configurés depuis settings

Usage :
    from core.http_client import get_http_client
    client = await get_http_client()
"""
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_client: httpx.AsyncClient | None = None


async def get_http_client() -> httpx.AsyncClient:
    """Retourne le client HTTP singleton, en le créant si nécessaire."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(
                settings.HTTP_TIMEOUT_TOTAL,
                connect=settings.HTTP_TIMEOUT_CONNECT,
            ),
            headers=_DEFAULT_HEADERS,
            limits=httpx.Limits(
                max_connections=settings.HTTP_MAX_CONNECTIONS,
                max_keepalive_connections=settings.HTTP_MAX_KEEPALIVE,
            ),
            follow_redirects=True,
        )
        logger.debug("✅ Client HTTP partagé créé (HTTP/2, pool=%d).", settings.HTTP_MAX_CONNECTIONS)
    return _client


async def close_http_client() -> None:
    """Ferme le client HTTP proprement. À appeler au shutdown."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
        logger.debug("🔌 Client HTTP partagé fermé.")
