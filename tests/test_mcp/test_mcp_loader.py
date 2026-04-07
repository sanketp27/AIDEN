"""
Tests for MCP Loader — verifies graceful fallback and dev-flag gating.
"""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


class _FakeSettings:
    WORKSPACE_MCP_PORT = 8001
    MONGO_MCP_PORT = 8002
    NOTION_MCP_PORT = 8003
    GITHUB_MCP_PORT = 8004
    WORKSPACE_MCP_ENABLED = True
    MONGO_MCP_ENABLED = True
    NOTION_MCP_ENABLED = True
    GITHUB_MCP_ENABLED = True
    NOTION_TOKEN = "secret_test_token"
    GITHUB_TOKEN = None


class _User:
    user_id = "u1"
    is_developer = False
    github_token = None


class _DevUser(_User):
    is_developer = True
    github_token = "enc_ghp"


FAKE_TOOLS = [MagicMock(), MagicMock()]


@pytest.mark.asyncio
async def test_workspace_and_mongo_loaded():
    with patch("src.core.mcp_loader._ADK_MCP_AVAILABLE", True), \
         patch("src.core.mcp_loader.MCPToolset") as m:
        m.from_server = AsyncMock(return_value=(FAKE_TOOLS, MagicMock()))
        from src.core.mcp_loader import MCPLoader
        r = await MCPLoader(_FakeSettings()).load_all(_User())
    assert len(r.workspace) == 2
    assert len(r.mongodb) == 2


@pytest.mark.asyncio
async def test_github_empty_for_non_dev():
    with patch("src.core.mcp_loader._ADK_MCP_AVAILABLE", True), \
         patch("src.core.mcp_loader.MCPToolset") as m:
        m.from_server = AsyncMock(return_value=(FAKE_TOOLS, MagicMock()))
        from src.core.mcp_loader import MCPLoader
        r = await MCPLoader(_FakeSettings()).load_all(_User())
    assert r.github == []


@pytest.mark.asyncio
async def test_github_loaded_for_dev():
    with patch("src.core.mcp_loader._ADK_MCP_AVAILABLE", True), \
         patch("src.core.mcp_loader.MCPToolset") as m:
        m.from_server = AsyncMock(return_value=(FAKE_TOOLS, MagicMock()))
        from src.core.mcp_loader import MCPLoader
        r = await MCPLoader(_FakeSettings()).load_all(_DevUser())
    assert len(r.github) == 2


@pytest.mark.asyncio
async def test_timeout_returns_empty():
    with patch("src.core.mcp_loader._ADK_MCP_AVAILABLE", True), \
         patch("src.core.mcp_loader.MCPToolset") as m:
        m.from_server = AsyncMock(side_effect=asyncio.TimeoutError())
        from src.core.mcp_loader import MCPLoader
        r = await MCPLoader(_FakeSettings()).load_all(_User())
    assert r.workspace == [] and r.mongodb == []


@pytest.mark.asyncio
async def test_notion_skipped_no_token():
    class _S(_FakeSettings):
        NOTION_TOKEN = None
    with patch("src.core.mcp_loader._ADK_MCP_AVAILABLE", True), \
         patch("src.core.mcp_loader.MCPToolset") as m:
        m.from_server = AsyncMock(return_value=(FAKE_TOOLS, MagicMock()))
        from src.core.mcp_loader import MCPLoader
        r = await MCPLoader(_S()).load_all(_User())
    assert r.notion == []


@pytest.mark.asyncio
async def test_adk_unavailable_all_empty():
    with patch("src.core.mcp_loader._ADK_MCP_AVAILABLE", False):
        from src.core.mcp_loader import MCPLoader
        r = await MCPLoader(_FakeSettings()).load_all(_DevUser())
    assert r.all_tools() == []
