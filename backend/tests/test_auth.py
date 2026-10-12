"""Hosted mode (COACH_AUTH=cognito): tokens are signed here with a throwaway RSA key."""

from __future__ import annotations

import dataclasses
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import coach.api as api_module
from coach.api import create_app
from coach.auth import AuthError, bearer, verify
from coach.config import Settings, get_settings
from coach.limits import DailyLimits
from tests.conftest import FakeChecker, FakeExtractor, FakeSearch, FakeStructuredModel, ScriptedChatModel
from tests.test_api import create_profile

POOL = "us-east-1_TestPool1"
CLIENT = "testclientid123"
ISSUER = f"https://cognito-idp.us-east-1.amazonaws.com/{POOL}"
SUB = "6f1c2d3e-0000-4abc-8def-123456789abc"
USER = f"u-{SUB}"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeKeys:
    """Stands in for the pool's JWKS endpoint."""

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=KEY.public_key())


def token(**overrides) -> str:
    claims = {"sub": SUB, "iss": ISSUER, "client_id": CLIENT, "token_use": "access",
              "username": SUB, "exp": int(time.time()) + 3600}
    claims.update(overrides)
    signer = claims.pop("_key", KEY)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, signer, algorithm="RS256")


def auth(tok: str | None = None) -> dict[str, str]:
    return {"X-Coach-Auth": f"Bearer {tok or token()}"}


@pytest.fixture
def hosted(settings) -> Settings:
    return dataclasses.replace(settings, auth="cognito", cognito_pool_id=POOL, cognito_client_id=CLIENT,
                               daily_builds=2, daily_chats=1)


@pytest.fixture
def client(hosted, store, monkeypatch):
    monkeypatch.setattr(api_module, "model_status",
                        lambda s: {"reachable": True, "model_ready": True, "detail": "ok"})
    models = {"synthesis": FakeStructuredModel(), "verify": FakeChecker(), "extract": FakeExtractor(),
              "chat": ScriptedChatModel()}
    return TestClient(create_app(settings=hosted, store=store, model_factory=models.__getitem__,
                                 search=FakeSearch(), keys=FakeKeys()))


def test_a_valid_access_token_names_its_user(hosted):
    assert verify(token(), hosted, FakeKeys()).user_id == USER


@pytest.mark.parametrize("bad", [
    token(exp=int(time.time()) - 10),          # expired
    token(iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Other"),
    token(client_id="someone-elses-app"),
    token(token_use="id"),                     # an ID token is not an access token
    token(_key=OTHER_KEY),                     # signed by another key
    token(token_use=None),                     # required claim missing
    "not-a-jwt",
])
def test_bad_tokens_are_refused(hosted, bad):
    with pytest.raises(AuthError):
        verify(bad, hosted, FakeKeys())


def test_the_token_is_read_from_either_header():
    assert bearer({"x-coach-auth": "Bearer abc"}) == "abc"
    assert bearer({"authorization": "bearer xyz"}) == "xyz"
    with pytest.raises(AuthError):
        bearer({})


def test_user_routes_need_a_sign_in(client):
    for response in (client.get(f"/api/users/{USER}/profile"), client.get(f"/api/users/{USER}/insights"),
                     client.post(f"/api/users/{USER}/chat", json={"message": "hi", "session_id": "s1"}),
                     create_profile(client, user=USER), client.get("/api/me")):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_nobody_can_open_someone_elses_coach(client):
    response = client.get("/api/users/u-someone-else/profile", headers=auth())
    assert response.status_code == 403 and response.json()["error"]["code"] == "FORBIDDEN"


def test_me_and_the_signed_in_flow(client):
    assert client.get("/api/me", headers=auth()).json() == {"user_id": USER}
    assert client.get(f"/api/users/{USER}/profile", headers=auth()).status_code == 404
    assert create_profile(client, user=USER, headers=auth()).status_code == 201
    assert client.get(f"/api/users/{USER}/profile", headers=auth()).json()["profile"]["user_id"] == USER


def test_health_is_open_and_tells_the_website_how_to_sign_in(client):
    body = client.get("/api/health").json()
    assert body["auth"] == {"mode": "cognito", "region": "us-east-1", "client_id": CLIENT}


def test_daily_caps_apply_per_user(client):
    assert create_profile(client, user=USER, headers=auth()).status_code == 201
    assert create_profile(client, user=USER, headers=auth()).status_code == 201
    third = create_profile(client, user=USER, headers=auth())
    assert third.status_code == 429 and third.json()["error"]["code"] == "DAILY_LIMIT"
    first_chat = client.post(f"/api/users/{USER}/chat", json={"message": "hi", "session_id": "s1"}, headers=auth())
    assert first_chat.status_code == 200
    second = client.post(f"/api/users/{USER}/chat", json={"message": "hi", "session_id": "s1"}, headers=auth())
    assert second.status_code == 429


def test_a_rejected_intake_does_not_use_up_a_build(client):
    for _ in range(3):
        response = client.post(f"/api/users/{USER}/profile", data={"goals": "too short"}, headers=auth())
        assert response.status_code == 422
    assert create_profile(client, user=USER, headers=auth()).status_code == 201


def test_caps_reset_each_day():
    day = [1]
    limits = DailyLimits({"chat": 1}, today=lambda: day[0])
    assert limits.take("chat", "a") and not limits.take("chat", "a") and limits.take("chat", "b")
    day[0] = 2
    assert limits.take("chat", "a")


def test_the_built_website_is_served_from_the_same_origin(hosted, store, tmp_path, monkeypatch):
    site = tmp_path / "dist"
    site.mkdir()
    (site / "index.html").write_text("<!doctype html><title>Career Coach</title>", encoding="utf-8")
    monkeypatch.setattr(api_module, "model_status", lambda s: {"reachable": True, "model_ready": True, "detail": "ok"})
    app = create_app(settings=dataclasses.replace(hosted, static_dir=site), store=store,
                     search=FakeSearch(), keys=FakeKeys())
    test = TestClient(app)
    assert "Career Coach" in test.get("/").text
    assert test.get("/api/health").json()["status"] == "ok"  # the API still wins over the site


def test_local_mode_is_unchanged(settings, store, monkeypatch):
    monkeypatch.setattr(api_module, "model_status", lambda s: {"reachable": True, "model_ready": True, "detail": "ok"})
    test = TestClient(create_app(settings=settings, store=store, search=FakeSearch()))
    assert test.get("/api/health").json()["auth"] == {"mode": "none"}
    assert test.get("/api/users/jordan-rivera/profile").status_code == 404  # no sign-in needed
    assert test.get("/api/me").status_code == 404


def test_half_configured_sign_in_is_refused(monkeypatch):
    monkeypatch.setattr("coach.config.load_env_file", lambda: None)
    monkeypatch.setenv("COACH_AUTH", "cognito")
    monkeypatch.delenv("COACH_COGNITO_POOL_ID", raising=False)
    with pytest.raises(ValueError, match="COACH_COGNITO_POOL_ID"):
        get_settings()
