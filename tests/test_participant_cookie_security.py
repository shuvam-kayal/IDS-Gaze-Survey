from services.control_plane.router import participant_cookie_secure


def test_participant_cookie_is_secure_by_default_and_in_production(monkeypatch):
    monkeypatch.delenv("PARTICIPANT_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    assert participant_cookie_secure() is True
    monkeypatch.setenv("PARTICIPANT_COOKIE_SECURE", "false")
    assert participant_cookie_secure() is True


def test_participant_cookie_can_be_insecure_only_in_explicit_local_modes(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("PARTICIPANT_COOKIE_SECURE", "false")
    assert participant_cookie_secure() is False
    monkeypatch.setenv("PARTICIPANT_COOKIE_SECURE", "true")
    assert participant_cookie_secure() is True
