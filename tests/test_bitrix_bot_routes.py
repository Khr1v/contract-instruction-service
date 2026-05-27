from __future__ import annotations

from pathlib import Path

import pytest

from app.api.bitrix_bot_routes import (
    _build_bitrix_adapter,
    _extract_dialog_id,
    _extract_event_auth,
    _extract_files,
    _get_str,
    _insert_nested_form_value,
)
from app.config import Settings
from app.integrations.bitrix_chat_adapter import BitrixChatAdapter


def test_bitrix_form_payload_extracts_chat_file() -> None:
    payload: dict[str, object] = {}
    for key, value in {
        "event": "ONIMBOTV2MESSAGEADD",
        "data[message][id]": "789",
        "data[message][chatId]": "5",
        "data[message][params][files][0][id]": "138",
        "data[message][params][files][0][name]": "contract.docx",
        "data[chat][id]": "5",
    }.items():
        _insert_nested_form_value(payload, key, value)

    data = payload["data"]
    assert isinstance(data, dict)
    message = data["message"]
    chat = data["chat"]
    assert isinstance(message, dict)
    assert isinstance(chat, dict)

    assert _extract_dialog_id(message, chat) == "chat5"
    assert _extract_files(message) == [{"id": "138", "name": "contract.docx"}]


def test_legacy_bitrix_payload_extracts_dialog_and_message() -> None:
    payload: dict[str, object] = {}
    for key, value in {
        "event": "ONIMBOTMESSAGEADD",
        "data[PARAMS][MESSAGE]": "/help",
        "data[PARAMS][DIALOG_ID]": "1812",
        "data[PARAMS][MESSAGE_ID]": "42",
        "data[USER][ID]": "1763",
    }.items():
        _insert_nested_form_value(payload, key, value)

    data = payload["data"]
    assert isinstance(data, dict)
    params = data["PARAMS"]
    assert isinstance(params, dict)

    assert _extract_dialog_id(params, {}) == "1812"
    assert _get_str(params, "message") == "/help"
    assert _get_str(params, "messageId") == "42"


def test_legacy_bitrix_payload_extracts_bot_event_auth() -> None:
    payload: dict[str, object] = {}
    for key, value in {
        "event": "ONIMBOTMESSAGEADD",
        "data[BOT][1812][AUTH][access_token]": "event-token",
        "data[BOT][1812][AUTH][client_endpoint]": "https://b24.example.ru/rest/",
    }.items():
        _insert_nested_form_value(payload, key, value)

    auth = _extract_event_auth(payload)

    assert auth["access_token"] == "event-token"
    assert auth["client_endpoint"] == "https://b24.example.ru/rest/"


def test_bitrix_adapter_uses_event_oauth_endpoint() -> None:
    adapter = _build_bitrix_adapter(
        {
            "data": {
                "BOT": {
                    "1812": {
                        "AUTH": {
                            "access_token": "event-token",
                            "client_endpoint": "https://b24.example.ru/rest/",
                        }
                    }
                }
            }
        }
    )

    assert adapter._rest_base_url == "https://b24.example.ru/rest"


def test_bitrix_adapter_builds_absolute_portal_url() -> None:
    adapter = BitrixChatAdapter(
        Settings(
            BITRIX_WEBHOOK_URL="https://b24.example.ru/rest/1763/token",
            BITRIX_BOT_ID=1812,
            BITRIX_BOT_TOKEN="client",
        )
    )

    assert adapter._rest_user_id() == "1763"
    assert adapter._absolute_portal_url("/company/personal/user/1763/disk/file/1/") == (
        "https://b24.example.ru/company/personal/user/1763/disk/file/1/"
    )


class FakeBitrixChatAdapter(BitrixChatAdapter):
    def __init__(self) -> None:
        super().__init__(
            Settings(
                BITRIX_WEBHOOK_URL="https://b24.example.ru/rest/1763/token",
                BITRIX_BOT_ID=1812,
                BITRIX_BOT_TOKEN="client",
            )
        )
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_method(self, method: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append((method, payload))
        if method == "im.disk.folder.get":
            return {"result": {"ID": 5153}}
        if method == "disk.folder.uploadfile":
            return {
                "result": {
                    "ID": 777,
                    "DETAIL_URL": "/company/personal/user/1763/disk/file/777/",
                }
            }
        if method == "im.disk.file.commit":
            return {"result": {"MESSAGE_ID": 888}}
        raise AssertionError(f"Unexpected method: {method}")


@pytest.mark.asyncio
async def test_upload_file_via_disk_attaches_to_chat_folder(tmp_path: Path) -> None:
    file_path = tmp_path / "instruction.docx"
    file_path.write_bytes(b"docx")
    adapter = FakeBitrixChatAdapter()

    result = await adapter.upload_file_via_disk("1763", file_path, "Готово")

    assert [method for method, _ in adapter.calls] == [
        "im.disk.folder.get",
        "disk.folder.uploadfile",
        "im.disk.file.commit",
    ]
    assert adapter.calls[0][1] == {"DIALOG_ID": "1763"}
    assert adapter.calls[1][1]["id"] == 5153
    assert adapter.calls[2][1]["FILE_ID"] == [777]
    assert result["result"]["chat_folder_id"] == 5153
