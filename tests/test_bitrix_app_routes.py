from __future__ import annotations

from app.api.bitrix_app_routes import _extract_install_data, _insert_nested_form_value


def test_extract_install_data_from_legacy_install_payload() -> None:
    payload: dict[str, object] = {}
    for key, value in {
        "DOMAIN": "b24.example.ru",
        "member_id": "member-1",
        "AUTH_ID": "access-token",
        "REFRESH_ID": "refresh-token",
        "AUTH_EXPIRES": "3600",
        "APP_SID": "app-token",
    }.items():
        _insert_nested_form_value(payload, key, value)

    data = _extract_install_data(payload)

    assert data["domain"] == "b24.example.ru"
    assert data["member_id"] == "member-1"
    assert data["access_token"] == "access-token"
    assert data["refresh_token"] == "refresh-token"
    assert data["application_token"] == "app-token"
    assert data["expires_at"] is not None


def test_extract_install_data_from_nested_auth_payload() -> None:
    payload: dict[str, object] = {}
    for key, value in {
        "auth[domain]": "b24.example.ru",
        "auth[member_id]": "member-1",
        "auth[access_token]": "access-token",
        "auth[refresh_token]": "refresh-token",
        "auth[client_endpoint]": "https://b24.example.ru/rest/",
    }.items():
        _insert_nested_form_value(payload, key, value)

    data = _extract_install_data(payload)

    assert data["domain"] == "b24.example.ru"
    assert data["access_token"] == "access-token"
    assert data["client_endpoint"] == "https://b24.example.ru/rest/"
