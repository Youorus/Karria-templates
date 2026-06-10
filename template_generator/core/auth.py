"""
auth.py — OAuth2Manager générique.

Utilisé par France Travail ET Karria sans duplication.
Gère le cache token, le renouvellement automatique et le refresh forcé.
"""
import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_EXPIRY_MARGIN = 60


def _default_token_extractor(data: dict[str, Any]) -> str:
    return data["access_token"]


def _default_expires_extractor(data: dict[str, Any]) -> int:
    return int(data["expires_in"])


class OAuth2Manager:
    def __init__(
        self,
        *,
        token_url: str,
        payload: dict[str, Any],
        name: str = "OAuth2",
        token_extractor: Callable[[dict], str] = _default_token_extractor,
        expires_extractor: Callable[[dict], int] = _default_expires_extractor,
        expiry_margin: int = _DEFAULT_EXPIRY_MARGIN,
        use_json: bool = False,
    ) -> None:
        self._token_url = token_url
        self._payload = payload
        self._name = name
        self._token_extractor = token_extractor
        self._expires_extractor = expires_extractor
        self._expiry_margin = expiry_margin
        self._use_json = use_json
        self._access_token: str | None = None
        self._expire_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def is_valid(self) -> bool:
        return (
            self._access_token is not None
            and time.monotonic() < self._expire_at
        )

    async def get_token(self, http_client: httpx.AsyncClient) -> str:
        async with self._lock:
            if self.is_valid:
                return self._access_token  # type: ignore[return-value]
            return await self._fetch_token(http_client)

    async def force_refresh(self, http_client: httpx.AsyncClient) -> str:
        async with self._lock:
            self._access_token = None
            self._expire_at = 0.0
            return await self._fetch_token(http_client)

    async def _fetch_token(self, http_client: httpx.AsyncClient) -> str:
        logger.info("🔑 [%s] Renouvellement du token OAuth2...", self._name)
        kwargs: dict[str, Any] = (
            {"json": self._payload} if self._use_json
            else {
                "data": self._payload,
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            }
        )
        resp = await http_client.post(self._token_url, **kwargs)
        if resp.is_error:
            logger.error("❌ [%s] Erreur token HTTP %s — %s", self._name, resp.status_code, resp.text)
        resp.raise_for_status()
        data = resp.json()
        self._access_token = self._token_extractor(data)
        expires_in = self._expires_extractor(data)
        self._expire_at = time.monotonic() + expires_in - self._expiry_margin
        logger.info("✅ [%s] Token obtenu (valide ~%ds).", self._name, max(expires_in - self._expiry_margin, 0))
        return self._access_token  # type: ignore[return-value]
