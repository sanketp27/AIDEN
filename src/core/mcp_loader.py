"""
AIDEN MCP Loader
================
Centralised manager that loads and caches MCP toolsets at session startup.

Four MCP servers are supported:
  - Google Workspace MCP  (port 8001)  — Calendar, Gmail, Drive, Docs
  - MongoDB MCP           (port 8002)  — Read-only task/notes queries
  - Notion MCP            (port 8003)  — Team wiki + collaboration
  - GitHub MCP            (port 8004)  — Dev-flag users only

Usage inside runner.py / orchestrator.py:
    from src.core.mcp_loader import MCPLoader
    loader = MCPLoader(settings)
    tools = await loader.load_all(user)
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
from dataclasses import dataclass, field
from typing import Any

import structlog
from cryptography.fernet import Fernet

log = structlog.get_logger()

try:
    from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseServerParams
    _ADK_MCP_AVAILABLE = True
except ImportError:
    _ADK_MCP_AVAILABLE = False
    log.warning("mcp_loader.adk_mcp_unavailable",
                msg="google-adk MCPToolset not found — MCP tools will be empty")


@dataclass
class MCPServerConfig:
    name: str
    url: str
    enabled: bool = True
    required: bool = False        # if True, failure raises; otherwise just warns


@dataclass
class LoadedMCPTools:
    workspace: list[Any] = field(default_factory=list)
    mongodb:   list[Any] = field(default_factory=list)
    notion:    list[Any] = field(default_factory=list)
    github:    list[Any] = field(default_factory=list)

    def all_tools(self) -> list[Any]:
        return self.workspace + self.mongodb + self.notion + self.github

    def __len__(self) -> int:
        return len(self.all_tools())


class MCPLoader:
    """
    Loads tools from all configured MCP servers.
    Caches workspace/mongodb/notion per process; github is per-user.
    """

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._cached_workspace: list[Any] | None = None
        self._cached_mongodb:   list[Any] | None = None
        self._cached_notion:    list[Any] | None = None

    async def load_all(self, user: Any | None = None) -> LoadedMCPTools:
        """
        Load all applicable MCP tool lists for the given user.
        GitHub tools only load when user.is_developer is True.
        """
        results = await asyncio.gather(
            self._get_workspace_tools(user),
            self._get_mongodb_tools(),
            self._get_notion_tools(user),
            self._get_github_tools(user),
            return_exceptions=True,
        )

        loaded = LoadedMCPTools()
        names  = ("workspace", "mongodb", "notion", "github")
        for name, result in zip(names, results):
            if isinstance(result, Exception):
                log.warning("mcp_loader.server_failed", server=name, error=str(result))
            elif result:
                setattr(loaded, name, result)

        log.info("mcp_loader.loaded",
                 workspace=len(loaded.workspace),
                 mongodb=len(loaded.mongodb),
                 notion=len(loaded.notion),
                 github=len(loaded.github))
        return loaded


    async def _get_workspace_tools(self, user: Any | None) -> list[Any]:
        cfg = MCPServerConfig(
            name="google-workspace-mcp",
            url=f"http://localhost:{getattr(self._settings, 'WORKSPACE_MCP_PORT', 8001)}/mcp",
            enabled=getattr(self._settings, 'WORKSPACE_MCP_ENABLED', True),
        )
        headers: dict[str, str] = {}
        if user is not None:
            access_token = self._safe_get(user, "google_access_token")
            user_id = self._safe_get(user, "user_id")
            if not access_token:
                log.info("mcp_loader.workspace_skipped", reason="google_access_token not set")
                return []
            headers["X-User-Access-Token"] = access_token
            if user_id:
                headers["X-User-Id"] = str(user_id)
        return await self._load_from_server(cfg, headers=headers)

    async def _get_mongodb_tools(self) -> list[Any]:
        if self._cached_mongodb is not None:
            return self._cached_mongodb

        cfg = MCPServerConfig(
            name="mongodb-mcp",
            url=f"http://localhost:{getattr(self._settings, 'MONGO_MCP_PORT', 8002)}/mcp",
            enabled=getattr(self._settings, 'MONGO_MCP_ENABLED', True),
        )
        tools = await self._load_from_server(cfg)
        self._cached_mongodb = tools
        return tools

    async def _get_notion_tools(self, user: Any | None) -> list[Any]:
        notion_token = getattr(self._settings, 'NOTION_TOKEN', None)
        encrypted_token = self._safe_get(user, "notion_token_encrypted") if user else None
        if encrypted_token:
            try:
                notion_token = self._decrypt_user_token(encrypted_token)
            except Exception as exc:
                log.warning("mcp_loader.notion_token_decrypt_failed", error=str(exc))
                return []
        if not notion_token:
            log.info("mcp_loader.notion_skipped", reason="no notion token available")
            return []

        cfg = MCPServerConfig(
            name="notion-mcp",
            url=f"http://localhost:{getattr(self._settings, 'NOTION_MCP_PORT', 8003)}/mcp",
            enabled=getattr(self._settings, 'NOTION_MCP_ENABLED', True),
        )
        return await self._load_from_server(cfg, headers={"Authorization": f"Bearer {notion_token}"})

    async def _get_github_tools(self, user: Any | None) -> list[Any]:
        """Only load for developer users who have a github_token configured."""
        if user is None:
            return []
        if not getattr(user, 'is_developer', False):
            return []
        if not getattr(user, 'github_token', None):
            log.info("mcp_loader.github_skipped",
                     user_id=getattr(user, 'user_id', 'unknown'),
                     reason="no github_token on user profile")
            return []

        cfg = MCPServerConfig(
            name="github-mcp",
            url=f"http://localhost:{getattr(self._settings, 'GITHUB_MCP_PORT', 8004)}/mcp",
            enabled=getattr(self._settings, 'GITHUB_MCP_ENABLED', True),
        )
        return await self._load_from_server(cfg)

    async def _load_from_server(self, cfg: MCPServerConfig, headers: dict[str, str] | None = None) -> list[Any]:
        if not cfg.enabled:
            log.info("mcp_loader.server_disabled", server=cfg.name)
            return []

        if not _ADK_MCP_AVAILABLE:
            return []

        try:
            kwargs: dict[str, Any] = {"connection_params": SseServerParams(url=cfg.url)}
            if headers:
                kwargs["headers"] = headers

            tools, _exit_stack = await asyncio.wait_for(MCPToolset.from_server(**kwargs), timeout=10.0)
            log.info("mcp_loader.server_connected",
                     server=cfg.name, tools=len(tools))
            return tools or []

        except asyncio.TimeoutError:
            log.warning("mcp_loader.server_timeout", server=cfg.name, url=cfg.url)
            if cfg.required:
                raise
            return []

        except Exception as exc:
            log.warning("mcp_loader.server_error",
                        server=cfg.name, url=cfg.url, error=str(exc))
            if cfg.required:
                raise
            return []

    @staticmethod
    def _safe_get(user: Any | None, key: str, default: Any = None) -> Any:
        if user is None:
            return default
        if isinstance(user, dict):
            return user.get(key, default)
        return getattr(user, key, default)

    def _decrypt_user_token(self, encrypted: str) -> str:
        key = base64.urlsafe_b64encode(self._settings.JWT_SECRET[:32].ljust(32).encode())
        return Fernet(key).decrypt(encrypted.encode()).decode()
