from datetime import UTC, datetime, timedelta

from app.core.oauth import collect_scopes
from app.core.token_store import TokenSet, TokenStore


def test_collect_google_scopes_includes_drive_file():
    scopes = collect_scopes("google")
    assert "https://www.googleapis.com/auth/drive.file" in scopes
    assert all(reason for reason in scopes.values())


def test_collect_unknown_provider_is_empty():
    assert collect_scopes("nope") == {}


def test_token_set_keeps_previous_refresh_token_on_refresh():
    t = TokenSet.from_token_response(
        "google", {"access_token": "a2", "expires_in": 3599, "scope": "s1 s2"}, previous_refresh_token="r1"
    )
    assert t.refresh_token == "r1"
    assert t.scope == ["s1", "s2"]
    assert not t.is_expired()


def test_token_set_expiry():
    t = TokenSet.from_token_response("google", {"access_token": "a", "expires_in": 30})
    assert t.is_expired()  # leeway 60초 안
    t.expires_at = datetime.now(UTC) + timedelta(hours=1)
    assert not t.is_expired()


def test_token_store_roundtrip_overwrites_latest(tmp_path):
    store = TokenStore(tmp_path / "t.json")
    assert store.get("google") is None
    store.save(TokenSet.from_token_response("google", {"access_token": "a1", "refresh_token": "r1", "expires_in": 10}))
    store.save(TokenSet.from_token_response("google", {"access_token": "a2", "refresh_token": "r2", "expires_in": 10}))
    loaded = store.get("google")
    assert loaded and loaded.access_token == "a2" and loaded.refresh_token == "r2"
    store.delete("google")
    assert store.get("google") is None
