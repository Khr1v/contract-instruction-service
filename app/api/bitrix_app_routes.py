from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.db.database import Database
from app.db.repository import BitrixAppInstallationRepository
from app.integrations.bitrix_oauth_client import BitrixOAuthClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bitrix/app", tags=["bitrix-app"])


@router.get("/handler")
@router.post("/handler")
async def bitrix_app_handler() -> dict[str, str]:
    return {"status": "ok", "adapter": "bitrix_local_app"}


@router.get("/install")
@router.post("/install")
async def bitrix_app_install(request: Request) -> dict[str, Any]:
    payload = await _read_payload(request)
    install_data = _extract_install_data(payload)
    if not install_data["domain"] or not install_data["access_token"]:
        raise HTTPException(status_code=400, detail="Bitrix install payload does not contain domain/access token")

    settings = get_settings()
    database = Database(settings)
    database.init_db()
    repository = BitrixAppInstallationRepository(database)
    installation = repository.upsert_installation(
        domain=install_data["domain"],
        member_id=install_data["member_id"],
        access_token=install_data["access_token"],
        refresh_token=install_data["refresh_token"],
        expires_at=install_data["expires_at"],
        application_token=install_data["application_token"],
        client_endpoint=install_data["client_endpoint"],
        server_endpoint=install_data["server_endpoint"],
    )

    event_url = settings.bitrix_bot_event_url
    if not event_url:
        if not settings.public_base_url:
            raise HTTPException(status_code=500, detail="Set PUBLIC_BASE_URL or BITRIX_BOT_EVENT_URL")
        event_url = f"{settings.public_base_url.rstrip('/')}/api/bitrix/bot/events"

    client = BitrixOAuthClient(installation, settings=settings, repository=repository)
    bot_id = await client.register_legacy_bot(
        event_url=event_url,
        bot_code=settings.bitrix_bot_code,
        bot_name=settings.bitrix_bot_name,
    )
    repository.save_bot_state(
        installation_id=installation.id,
        bot_id=bot_id,
        bot_code=settings.bitrix_bot_code,
        bot_client_id=None,
    )
    logger.info("Bitrix local app installed domain=%s bot_id=%s", install_data["domain"], bot_id)
    return {
        "status": "installed",
        "domain": install_data["domain"],
        "member_id": install_data["member_id"],
        "bot_id": bot_id,
        "bot_code": settings.bitrix_bot_code,
        "event_url": event_url,
    }


async def _read_payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
        result = payload if isinstance(payload, dict) else {"payload": payload}
    else:
        body = await request.body()
        parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
        result = {}
        for raw_key, values in parsed.items():
            _insert_nested_form_value(result, raw_key, values[-1] if values else "")
    for raw_key, value in request.query_params.multi_items():
        if raw_key not in result:
            _insert_nested_form_value(result, raw_key, value)
    return result


def _extract_install_data(payload: dict[str, Any]) -> dict[str, Any]:
    auth = _get_dict(payload, "auth")
    access_token = (
        _get_str(auth, "access_token")
        or _get_str(payload, "access_token")
        or _get_str(payload, "AUTH_ID")
        or _get_str(payload, "AUTH_ID".lower())
    )
    refresh_token = (
        _get_str(auth, "refresh_token")
        or _get_str(payload, "refresh_token")
        or _get_str(payload, "REFRESH_ID")
        or _get_str(payload, "REFRESH_ID".lower())
    )
    client_endpoint = _get_str(auth, "client_endpoint") or _get_str(payload, "client_endpoint")
    domain = (
        _get_str(auth, "domain")
        or _get_str(payload, "DOMAIN")
        or _get_str(payload, "domain")
        or _domain_from_endpoint(client_endpoint)
    )
    expires_in = _safe_int(
        _get_str(auth, "expires_in")
        or _get_str(payload, "expires_in")
        or _get_str(payload, "AUTH_EXPIRES")
        or _get_str(payload, "AUTH_EXPIRES".lower())
    )
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in) if expires_in else None
    return {
        "domain": domain,
        "member_id": _get_str(auth, "member_id") or _get_str(payload, "member_id"),
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "application_token": (
            _get_str(auth, "application_token")
            or _get_str(payload, "application_token")
            or _get_str(payload, "APP_SID")
        ),
        "client_endpoint": client_endpoint,
        "server_endpoint": _get_str(auth, "server_endpoint") or _get_str(payload, "server_endpoint"),
    }


def _insert_nested_form_value(target: dict[str, Any], raw_key: str, value: Any) -> None:
    parts = _split_form_key(raw_key)
    cursor: dict[str, Any] = target
    for part in parts[:-1]:
        next_value = cursor.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            cursor[part] = next_value
        cursor = next_value
    cursor[parts[-1]] = value


def _split_form_key(key: str) -> list[str]:
    parts: list[str] = []
    buffer = ""
    index = 0
    while index < len(key):
        char = key[index]
        if char == "[":
            if buffer:
                parts.append(buffer)
                buffer = ""
            index += 1
            inner = ""
            while index < len(key) and key[index] != "]":
                inner += key[index]
                index += 1
            if inner:
                parts.append(inner)
        else:
            buffer += char
        index += 1
    if buffer:
        parts.append(buffer)
    return parts or [key]


def _get_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    for variant in _key_variants(key):
        value = payload.get(variant)
        if isinstance(value, dict):
            return value
    return {}


def _get_str(payload: dict[str, Any], key: str) -> str | None:
    for variant in _key_variants(key):
        value = payload.get(variant)
        if value is not None:
            text = str(value).strip()
            return text or None
    return None


def _key_variants(key: str) -> list[str]:
    variants = [key, key.upper(), key.lower()]
    snake = ""
    for index, char in enumerate(key):
        if char.isupper() and index > 0:
            snake += "_"
        snake += char.upper()
    if snake not in variants:
        variants.append(snake)
    return variants


def _domain_from_endpoint(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    parsed = urlsplit(endpoint)
    return parsed.netloc or None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
