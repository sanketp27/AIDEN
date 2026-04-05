"""
Tests for developer settings endpoint.
"""
from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.api.routers.developer_settings import router, encrypt_token, decrypt_token


def test_encrypt_decrypt_roundtrip():
    token = "ghp_testtoken12345"
    encrypted = encrypt_token(token)
    assert encrypted != token
    decrypted = decrypt_token(encrypted)
    assert decrypted == token


def test_decrypt_plain_without_cryptography():
    """If cryptography is missing, tokens pass through unchanged."""
    import importlib, sys
    with pytest.MonkeyPatch().context() as mp:
        mp.setitem(sys.modules, "cryptography.fernet", None)
        plain = "ghp_plain"
        # Should not raise
        result = decrypt_token(plain)
        assert isinstance(result, str)


def _build_test_app():
    app = FastAPI()
    app.include_router(router)
    return app


def test_get_developer_settings_returns_200():
    client = TestClient(_build_test_app())
    response = client.get("/settings/developer")
    assert response.status_code == 200
    data = response.json()
    assert "developer_mode" in data
    assert "github_connected" in data


def test_patch_enable_developer_mode():
    client = TestClient(_build_test_app())
    response = client.patch(
        "/settings/developer",
        json={"enabled": True, "github_token": "ghp_testtokenabc"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["developer_mode"] is True
    assert data["github_connected"] is True


def test_patch_disable_developer_mode():
    client = TestClient(_build_test_app())
    response = client.patch(
        "/settings/developer",
        json={"enabled": False}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["developer_mode"] is False
