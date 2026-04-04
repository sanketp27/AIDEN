from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.task import Priority, Task, TaskStatus, TaskUpdate

USER_ID = "test_user_abc123"


@pytest.fixture
def task_repo(mock_mongo_col):
    from src.repositories.task_repo import TaskRepository
    repo = TaskRepository()
    # Patch _tasks() to return the mock collection for any user_id
    repo._tasks         = MagicMock(return_value=mock_mongo_col)
    repo.ensure_indexes = AsyncMock()
    return repo


@pytest.fixture
def sample_task():
    return Task(
        user_id     = USER_ID,
        title       = "Review Q2 product roadmap",
        description = "Align on priorities before board meeting.",
        priority    = Priority.P1,
        status      = TaskStatus.TODO,
        due_date    = datetime.now(timezone.utc) + timedelta(days=2),
        tags        = ["Q2", "strategy"],
    )


class TestCreateTask:
    async def test_insert_one_called(self, task_repo, mock_mongo_col, sample_task):
        """create_task should call insert_one with the task dict."""
        await task_repo.create_task(sample_task)
        mock_mongo_col.insert_one.assert_called_once()

    async def test_returns_task_dict(self, task_repo, sample_task):
        """create_task should return a dict with a task_id key."""
        result = await task_repo.create_task(sample_task)
        assert isinstance(result, dict)
        assert "task_id" in result

    async def test_ensure_indexes_called(self, task_repo, sample_task):
        """Indexes must be ensured on every create to support new users."""
        await task_repo.create_task(sample_task)
        task_repo.ensure_indexes.assert_called_once_with(USER_ID)


class TestGetTask:
    async def test_returns_none_when_not_found(self, task_repo, mock_mongo_col):
        """get_task returns None when MongoDB find_one returns None."""
        mock_mongo_col.find_one.return_value = None
        result = await task_repo.get_task(USER_ID, "nonexistent_id")
        assert result is None

    async def test_returns_task_when_found(self, task_repo, mock_mongo_col, sample_task):
        """get_task reconstructs a Task from the stored dict."""
        doc = sample_task.model_dump()
        doc["_id"] = "mongo_internal_id"
        mock_mongo_col.find_one.return_value = doc

        result = await task_repo.get_task(USER_ID, sample_task.task_id)
        assert result is not None
        assert result.title == sample_task.title
        assert result.priority == Priority.P1

    async def test_query_scoped_to_user(self, task_repo, mock_mongo_col, sample_task):
        """get_task must filter by both task_id AND user_id (security)."""
        mock_mongo_col.find_one.return_value = None
        await task_repo.get_task(USER_ID, "some_task_id")
        call_args = mock_mongo_col.find_one.call_args[0][0]
        assert call_args["user_id"] == USER_ID
        assert call_args["task_id"] == "some_task_id"


class TestUpdateTask:
    async def test_update_one_called_with_set(self, task_repo, mock_mongo_col, sample_task):
        """update_task should issue a $set update with the changed fields."""
        mock_mongo_col.find_one.return_value = sample_task.model_dump()
        update = TaskUpdate(status=TaskStatus.COMPLETED)
        await task_repo.update_task(USER_ID, sample_task.task_id, update)
        mock_mongo_col.update_one.assert_called_once()
        call_args = mock_mongo_col.update_one.call_args
        assert "$set" in call_args[0][1]
        assert "status" in call_args[0][1]["$set"]

    async def test_update_scoped_to_user(self, task_repo, mock_mongo_col, sample_task):
        """update_task filter must include user_id to prevent cross-user writes."""
        mock_mongo_col.find_one.return_value = sample_task.model_dump()
        await task_repo.update_task(USER_ID, sample_task.task_id, TaskUpdate(status=TaskStatus.IN_PROGRESS))
        filter_doc = mock_mongo_col.update_one.call_args[0][0]
        assert filter_doc["user_id"] == USER_ID

    async def test_returns_none_when_task_missing(self, task_repo, mock_mongo_col):
        """update_task returns None when modified_count is 0."""
        mock_mongo_col.update_one.return_value = MagicMock(modified_count=0)
        result = await task_repo.update_task(USER_ID, "ghost_id", TaskUpdate(status=TaskStatus.COMPLETED))
        assert result is None


class TestDeleteTask:
    async def test_delete_one_called(self, task_repo, mock_mongo_col):
        """delete_task must call delete_one."""
        result = await task_repo.delete_task(USER_ID, "task_id_1")
        mock_mongo_col.delete_one.assert_called_once()
        assert result is True

    async def test_returns_false_when_not_found(self, task_repo, mock_mongo_col):
        """delete_task returns False when deleted_count is 0."""
        mock_mongo_col.delete_one.return_value = MagicMock(deleted_count=0)
        result = await task_repo.delete_task(USER_ID, "ghost_id")
        assert result is False

    async def test_delete_scoped_to_user(self, task_repo, mock_mongo_col):
        """delete filter must include user_id."""
        await task_repo.delete_task(USER_ID, "some_task")
        filter_doc = mock_mongo_col.delete_one.call_args[0][0]
        assert filter_doc["user_id"] == USER_ID


class TestListTasks:
    async def test_returns_empty_list_for_empty_collection(self, task_repo, mock_mongo_col):
        """list_tasks returns [] when collection cursor is empty."""
        tasks = await task_repo.list_tasks(USER_ID)
        assert isinstance(tasks, list)
        assert len(tasks) == 0
