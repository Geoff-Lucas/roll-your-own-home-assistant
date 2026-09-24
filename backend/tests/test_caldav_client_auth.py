from app.models import Account
from app.security.crypto import encrypt
from app.sync import caldav_client


def test_is_configured_true_for_basic_auth_account():
    account = Account(
        provider="icloud",
        display_name="Test",
        person_name="Geoff",
        caldav_url="https://caldav.icloud.com",
        username="geoff@icloud.com",
        encrypted_credential=encrypt("app-specific-password"),
    )
    assert caldav_client._is_configured(account) is True


def test_is_configured_true_for_oauth_account_without_username():
    account = Account(
        provider="google",
        display_name="Test",
        person_name="Geoff",
        caldav_url="https://apidata.googleusercontent.com/caldav/v2/geoff@gmail.com/user",
        oauth_refresh_token=encrypt("refresh-token"),
    )
    assert caldav_client._is_configured(account) is True


def test_is_configured_false_when_nothing_set():
    account = Account(provider="caldav", display_name="Test", person_name="Geoff")
    assert caldav_client._is_configured(account) is False


def test_principal_uses_bearer_auth_for_oauth_account(monkeypatch):
    account = Account(
        provider="google",
        display_name="Test",
        person_name="Geoff",
        caldav_url="https://apidata.googleusercontent.com/caldav/v2/geoff@gmail.com/user",
        oauth_refresh_token=encrypt("refresh-token"),
    )

    monkeypatch.setattr(caldav_client, "get_valid_access_token", lambda refresh_token: "fresh-access-token")

    captured = {}

    class FakeDAVClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def principal(self):
            return "fake-principal"

    monkeypatch.setattr(caldav_client.caldav, "DAVClient", FakeDAVClient)

    result = caldav_client._principal(account)

    assert result == "fake-principal"
    assert captured["auth_type"] == "bearer"
    assert captured["password"] == "fresh-access-token"
    assert "username" not in captured
    # A sync holds the account lock while it waits on the server, so a hung
    # server must time out rather than block event edits forever.
    assert captured["timeout"] == caldav_client.settings.caldav_timeout_seconds


def test_principal_uses_basic_auth_for_password_account(monkeypatch):
    account = Account(
        provider="icloud",
        display_name="Test",
        person_name="Geoff",
        caldav_url="https://caldav.icloud.com",
        username="geoff@icloud.com",
        encrypted_credential=encrypt("app-specific-password"),
    )

    captured = {}

    class FakeDAVClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def principal(self):
            return "fake-principal"

    monkeypatch.setattr(caldav_client.caldav, "DAVClient", FakeDAVClient)

    result = caldav_client._principal(account)

    assert result == "fake-principal"
    assert captured["username"] == "geoff@icloud.com"
    assert captured["password"] == "app-specific-password"
    assert "auth_type" not in captured
    assert captured["timeout"] == caldav_client.settings.caldav_timeout_seconds
