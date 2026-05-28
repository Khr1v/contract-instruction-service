from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.db.database import Database
from app.db.models import BitrixAppInstallationRecord
from app.db.repository import BitrixAppInstallationRepository
from app.integrations.bitrix_chat_adapter import BitrixAPIError

logger = logging.getLogger(__name__)


class BitrixOAuthClient:
    """REST client for a local Bitrix application installed via OAuth."""

    def __init__(
        self,
        installation: BitrixAppInstallationRecord,
        *,
        settings: Settings | None = None,
        repository: BitrixAppInstallationRepository | None = None,
    ) -> None:
        self.installation = installation
        self.settings = settings or get_settings()
        if repository is None:
            database = Database(self.settings)
            database.init_db()
            repository = BitrixAppInstallationRepository(database)
        self.repository = repository

    @property
    def rest_base_url(self) -> str:
        if self.installation.client_endpoint:
            return self.installation.client_endpoint.rstrip("/")
        return f"https://{self.installation.domain}/rest"

    async def call_method(self, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        payload["auth"] = self.installation.access_token
        data = await self._post_method(method, payload)
        if self._is_expired_token_response(data):
            await self.refresh_tokens()
            payload["auth"] = self.installation.access_token
            data = await self._post_method(method, payload)
        if data.get("error"):
            error = data.get("error")
            description = data.get("error_description") or data.get("error_description_raw") or ""
            raise BitrixAPIError(f"Bitrix method {method} failed: {error}: {description}")
        return data

    async def register_legacy_bot(self, *, event_url: str, bot_code: str, bot_name: str) -> int:
        result = await self.call_method(
            "imbot.register",
            {
                "CODE": bot_code,
                "TYPE": "B",
                "EVENT_HANDLER": event_url,
                "OPENLINE": "N",
                "PROPERTIES": {
                    "NAME": bot_name,
                    "WORK_POSITION": "Генератор инструкций по договорам",
                    "COLOR": "GREEN",
                },
            },
        )
        bot_result = result.get("result")
        if isinstance(bot_result, dict):
            bot_id = bot_result.get("ID") or bot_result.get("id") or bot_result.get("BOT_ID")
        else:
            bot_id = bot_result
        if bot_id is None:
            raise BitrixAPIError(f"Bitrix imbot.register returned no bot id: {result}")
        return int(bot_id)

    async def refresh_tokens(self) -> None:
        if not self.installation.refresh_token:
            raise BitrixAPIError("Bitrix OAuth refresh token is missing")
        if not self.settings.bitrix_client_id or not self.settings.bitrix_client_secret:
            raise BitrixAPIError("BITRIX_CLIENT_ID and BITRIX_CLIENT_SECRET are required to refresh OAuth token")

        params = {
            "grant_type": "refresh_token",
            "client_id": self.settings.bitrix_client_id,
            "client_secret": self.settings.bitrix_client_secret,
            "refresh_token": self.installation.refresh_token,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get("https://oauth.bitrix24.tech/oauth/token/", params=params)
        data = response.json()
        if response.status_code >= 400 or data.get("error"):
            raise BitrixAPIError(
                "Bitrix OAuth refresh failed: "
                f"{data.get('error') or response.status_code}: {data.get('error_description') or response.text[:300]}"
            )

        access_token = str(data["access_token"])
        refresh_token = str(data.get("refresh_token") or self.installation.refresh_token)
        expires_in = _safe_int(data.get("expires_in"))
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in) if expires_in else None
        updated = self.repository.upsert_installation(
            domain=self.installation.domain,
            member_id=self.installation.member_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            application_token=self.installation.application_token,
            client_endpoint=data.get("client_endpoint") or self.installation.client_endpoint,
            server_endpoint=data.get("server_endpoint") or self.installation.server_endpoint,
        )
        self.installation = updated

    async def _post_method(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.rest_base_url}/{method}"
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload)
        try:
            data = response.json()
        except ValueError as exc:
            raise BitrixAPIError(f"Bitrix method {method} returned non-JSON response") from exc
        if response.status_code >= 400:
            if isinstance(data, dict):
                return data
            raise BitrixAPIError(f"Bitrix method {method} HTTP {response.status_code}: {response.text[:300]}")
        return data

    @staticmethod
    def _is_expired_token_response(data: dict[str, Any]) -> bool:
        error = str(data.get("error") or "").lower()
        description = str(data.get("error_description") or "").lower()
        return "expired" in error or "expired" in description


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
