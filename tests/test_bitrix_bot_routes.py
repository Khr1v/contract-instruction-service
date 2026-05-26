from __future__ import annotations

from app.api.bitrix_bot_routes import _extract_dialog_id, _extract_files, _insert_nested_form_value


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
