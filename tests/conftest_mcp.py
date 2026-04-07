"""
Shared fixtures for MCP tests.
Add these to your main tests/conftest.py.
"""
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def fake_mcp_tools():
    """Return a list of 3 mock MCP tool objects."""
    return [MagicMock(name=f"mcp_tool_{i}") for i in range(3)]


@pytest.fixture
def fake_dev_user():
    class User:
        user_id = "dev_user_1"
        is_developer = True
        github_token = "enc_ghp_abc123"
    return User()


@pytest.fixture
def fake_regular_user():
    class User:
        user_id = "user_1"
        is_developer = False
        github_token = None
    return User()
