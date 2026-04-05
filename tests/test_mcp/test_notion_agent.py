"""
Tests for NotionAgent builder — verifies MCP connection and fallback.
"""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.mark.asyncio
async def test_notion_agent_returns_none_without_token():
    with patch("src.agents.notion_agent._NOTION_TOKEN", None):
        from src.agents.notion_agent import build_notion_agent
        result = await build_notion_agent()
    assert result is None


@pytest.mark.asyncio
async def test_notion_agent_returns_none_on_timeout():
    with patch("src.agents.notion_agent._NOTION_TOKEN", "secret_x"), \
         patch("src.agents.notion_agent._ADK_AVAILABLE", True), \
         patch("src.agents.notion_agent.MCPToolset") as m:
        m.from_server = AsyncMock(side_effect=asyncio.TimeoutError())
        from src.agents.notion_agent import build_notion_agent
        result = await build_notion_agent()
    assert result is None


@pytest.mark.asyncio
async def test_notion_agent_returns_none_without_adk():
    with patch("src.agents.notion_agent._ADK_AVAILABLE", False), \
         patch("src.agents.notion_agent._NOTION_TOKEN", "secret_x"):
        from src.agents.notion_agent import build_notion_agent
        result = await build_notion_agent()
    assert result is None
