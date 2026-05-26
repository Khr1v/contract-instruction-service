from __future__ import annotations

from app.api.bitrix_bot_routes import _extract_dialog_id, _extract_files, _get_str, _insert_nested_form_value


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
