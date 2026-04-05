"""
tests/test_tools/test_drive_agent.py
=====================================
Unit tests for DriveAgent tools — search, read, list operations.
Google Drive API calls are fully mocked; no credentials required.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

USER_ID = "test_user_abc123"
FILE_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"


@pytest.fixture
def mock_drive_client():
    """A mock GoogleDriveClient with all async methods pre-wired."""
    client = MagicMock()
    client.search_files = AsyncMock(return_value=[
        {
            "id": FILE_ID,
            "name": "Q3 Revenue Report",
            "mimeType": "application/vnd.google-apps.document",
            "modifiedTime": "2026-03-15T10:30:00Z",
            "webViewLink": f"https://docs.google.com/document/d/{FILE_ID}/edit",
        },
        {
            "id": "2nd_file_id",
            "name": "Q3 Marketing Summary",
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "modifiedTime": "2026-03-10T09:00:00Z",
            "webViewLink": "https://docs.google.com/spreadsheets/d/2nd_file_id/edit",
        },
    ])
    client.get_file_content = AsyncMock(return_value=(
        "Q3 Revenue Report\n\n"
        "Total Revenue: $4.2M (↑12% vs Q2)\n"
        "Key highlights:\n"
        "- Enterprise deals closed: 8\n"
        "- Average deal size: $525K\n"
        "- Churn rate: 2.1%\n"
        "Action items: Present to board by April 15."
    ))
    client.list_recent_files = AsyncMock(return_value=[
        {
            "id": FILE_ID,
            "name": "Q3 Revenue Report",
            "mimeType": "application/vnd.google-apps.document",
            "modifiedTime": "2026-03-15T10:30:00Z",
            "webViewLink": f"https://docs.google.com/document/d/{FILE_ID}/edit",
        }
    ])
    return client


class TestSearchDriveFiles:
    @pytest.mark.asyncio
    async def test_returns_files_on_success(self, mock_drive_client):
        """search_drive_files must return simplified file list."""
        with patch(
            "src.agents.drive_agent.get_drive_client",
            new=AsyncMock(return_value=mock_drive_client),
        ):
            from src.agents.drive_agent import search_drive_files
            result = await search_drive_files(USER_ID, "Q3 report")

        assert result["count"] == 2
        assert result["query"] == "Q3 report"
        names = [f["name"] for f in result["files"]]
        assert "Q3 Revenue Report" in names

    @pytest.mark.asyncio
    async def test_not_connected_returns_error(self):
        """Returns error dict when Drive is not connected (client is None)."""
        with patch(
            "src.agents.drive_agent.get_drive_client",
            new=AsyncMock(return_value=None),
        ):
            from src.agents.drive_agent import search_drive_files
            result = await search_drive_files(USER_ID, "Q3 report")

        assert "error" in result
        assert result["count"] == 0
        assert "Connect Google Drive" in result["error"]

    @pytest.mark.asyncio
    async def test_max_results_capped_at_20(self, mock_drive_client):
        """max_results > 20 must be silently capped to 20."""
        with patch(
            "src.agents.drive_agent.get_drive_client",
            new=AsyncMock(return_value=mock_drive_client),
        ):
            from src.agents.drive_agent import search_drive_files
            await search_drive_files(USER_ID, "any query", max_results=999)

        call_kwargs = mock_drive_client.search_files.call_args.kwargs
        assert call_kwargs["max_results"] <= 20

    @pytest.mark.asyncio
    async def test_file_type_friendly_label(self, mock_drive_client):
        """mimeType must be converted to a human-readable type label."""
        with patch(
            "src.agents.drive_agent.get_drive_client",
            new=AsyncMock(return_value=mock_drive_client),
        ):
            from src.agents.drive_agent import search_drive_files
            result = await search_drive_files(USER_ID, "Q3")

        types = [f["type"] for f in result["files"]]
        assert "Google Doc"   in types
        assert "Google Sheet" in types


class TestReadDriveFile:
    @pytest.mark.asyncio
    async def test_returns_file_content(self, mock_drive_client):
        """read_drive_file must return non-empty content for valid file ID."""
        with patch(
            "src.agents.drive_agent.get_drive_client",
            new=AsyncMock(return_value=mock_drive_client),
        ):
            from src.agents.drive_agent import read_drive_file
            result = await read_drive_file(USER_ID, FILE_ID)

        assert result["file_id"] == FILE_ID
        assert len(result["content"]) > 0
        assert "Revenue" in result["content"]

    @pytest.mark.asyncio
    async def test_not_connected_returns_error(self):
        """Returns error dict when Drive client is None."""
        with patch(
            "src.agents.drive_agent.get_drive_client",
            new=AsyncMock(return_value=None),
        ):
            from src.agents.drive_agent import read_drive_file
            result = await read_drive_file(USER_ID, FILE_ID)

        assert "error" in result
        assert result["content"] == ""


class TestListRecentDriveFiles:
    @pytest.mark.asyncio
    async def test_returns_recent_files(self, mock_drive_client):
        """list_recent_drive_files must return count and file list."""
        with patch(
            "src.agents.drive_agent.get_drive_client",
            new=AsyncMock(return_value=mock_drive_client),
        ):
            from src.agents.drive_agent import list_recent_drive_files
            result = await list_recent_drive_files(USER_ID)

        assert result["count"] == 1
        assert result["files"][0]["name"] == "Q3 Revenue Report"

    @pytest.mark.asyncio
    async def test_not_connected_returns_error(self):
        """Returns error dict when Drive is not connected."""
        with patch(
            "src.agents.drive_agent.get_drive_client",
            new=AsyncMock(return_value=None),
        ):
            from src.agents.drive_agent import list_recent_drive_files
            result = await list_recent_drive_files(USER_ID)

        assert "error" in result
        assert result["count"] == 0
