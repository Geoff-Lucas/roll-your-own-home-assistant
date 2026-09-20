from urllib.parse import parse_qs, urlparse

from app import config
from app.sync import google_oauth


def configure_fake_client(monkeypatch):
    monkeypatch.setattr(config.settings, "google_oauth_client_id", "fake-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(config.settings, "google_oauth_client_secret", "fake-secret")
    monkeypatch.setattr(config.settings, "google_oauth_redirect_uri", "http://localhost:8000/api/google-oauth/callback")


def test_build_authorization_url_includes_expected_params(monkeypatch):
    configure_fake_client(monkeypatch)

    url, code_verifier = google_oauth.build_authorization_url(state="abc123")

    parsed = urlparse(url)
    assert parsed.netloc == "accounts.google.com"
    params = parse_qs(parsed.query)
    assert params["client_id"] == ["fake-client-id.apps.googleusercontent.com"]
    assert params["redirect_uri"] == ["http://localhost:8000/api/google-oauth/callback"]
    assert params["state"] == ["abc123"]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert "https://www.googleapis.com/auth/calendar" in params["scope"][0]
    # PKCE: the challenge in the URL must be derived from the returned verifier
    assert params["code_challenge_method"] == ["S256"]
    assert code_verifier  # non-empty — this is what the earlier live test lost track of


def test_get_valid_access_token_refreshes_credentials(monkeypatch):
    configure_fake_client(monkeypatch)

    captured = {}

    def fake_refresh(self, request):
        captured["refresh_token"] = self.refresh_token
        self.token = "fresh-access-token"

    monkeypatch.setattr(google_oauth.Credentials, "refresh", fake_refresh)

    token = google_oauth.get_valid_access_token("stored-refresh-token")

    assert token == "fresh-access-token"
    assert captured["refresh_token"] == "stored-refresh-token"


def test_exchange_code_returns_refresh_token_and_email(monkeypatch):
    configure_fake_client(monkeypatch)

    class FakeCredentials:
        refresh_token = "new-refresh-token"
        token = "temp-access-token"

    def fake_fetch_token(self, **kwargs):
        self._credentials = FakeCredentials()

    monkeypatch.setattr(google_oauth.Flow, "fetch_token", fake_fetch_token)
    monkeypatch.setattr(google_oauth.Flow, "credentials", property(lambda self: self._credentials))

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"email": "someone@gmail.com"}

    monkeypatch.setattr(google_oauth.requests, "get", lambda *a, **k: FakeResponse())

    refresh_token, email = google_oauth.exchange_code("some-auth-code", code_verifier="the-verifier-from-start")

    assert refresh_token == "new-refresh-token"
    assert email == "someone@gmail.com"


def test_exchange_code_sets_verifier_on_the_flow_before_fetching(monkeypatch):
    # This is the exact bug hit against the real account: two independent
    # Flow instances (one at /start, one at /callback) each generate their
    # own code_verifier unless the caller explicitly carries it over.
    configure_fake_client(monkeypatch)

    captured = {}

    def fake_fetch_token(self, **kwargs):
        captured["verifier_at_fetch_time"] = self.code_verifier

        class FakeCredentials:
            refresh_token = "rt"
            token = "at"

        self._credentials = FakeCredentials()

    monkeypatch.setattr(google_oauth.Flow, "fetch_token", fake_fetch_token)
    monkeypatch.setattr(google_oauth.Flow, "credentials", property(lambda self: self._credentials))
    monkeypatch.setattr(google_oauth.requests, "get", lambda *a, **k: type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: {"email": "x@gmail.com"}})())

    google_oauth.exchange_code("some-code", code_verifier="verifier-from-the-start-step")

    assert captured["verifier_at_fetch_time"] == "verifier-from-the-start-step"
