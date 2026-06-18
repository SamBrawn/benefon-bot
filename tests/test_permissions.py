"""Tests for permissions module."""

import pytest
from models import UserRole, TaskStatus
from permissions import (
    check_permission,
    can_create_task,
    can_approve_task,
    can_view_task,
    can_manage_materials,
    can_manage_tools,
    can_manage_users,
    can_view_reports,
    get_allowed_transitions,
    Permission,
)


class TestPermissions:
    """Test permission checks for all roles."""

    def test_owner_has_all_permissions(self):
        """Owner should have all permissions."""
        assert can_create_task(UserRole.OWNER) is True
        assert can_manage_users(UserRole.OWNER) is True
        assert can_view_reports(UserRole.OWNER) is True
        assert can_manage_materials(UserRole.OWNER) == "full"
        assert can_manage_tools(UserRole.OWNER) == "full"

    def test_general_director_permissions(self):
        """General director should have most permissions."""
        assert can_create_task(UserRole.GENERAL_DIRECTOR) is True
        assert can_manage_users(UserRole.GENERAL_DIRECTOR) is False
        assert can_view_reports(UserRole.GENERAL_DIRECTOR) is True
        assert can_manage_materials(UserRole.GENERAL_DIRECTOR) == "full"

    def test_pto_permissions(self):
        """PTO should have limited permissions."""
        assert can_create_task(UserRole.PTO) is True
        assert can_manage_users(UserRole.PTO) is False
        assert can_manage_materials(UserRole.PTO) == "planning"
        assert can_manage_tools(UserRole.PTO) == "view"

    def test_foreman_permissions(self):
        """Foreman should have crew-level permissions."""
        assert can_create_task(UserRole.FOREMAN) is True
        assert can_manage_users(UserRole.FOREMAN) is False
        assert can_manage_materials(UserRole.FOREMAN) == "expense"
        assert can_manage_tools(UserRole.FOREMAN) == "assign"

    def test_electrician_permissions(self):
        """Electrician should have minimal permissions."""
        assert can_create_task(UserRole.ELECTRICIAN) is False
        assert can_manage_users(UserRole.ELECTRICIAN) is False
        assert can_manage_materials(UserRole.ELECTRICIAN) == "none"
        assert can_manage_tools(UserRole.ELECTRICIAN) == "none"

    def test_worker_permissions(self):
        """Worker should have minimal permissions."""
        assert can_create_task(UserRole.WORKER) is False
        assert can_manage_users(UserRole.WORKER) is False
        assert can_manage_materials(UserRole.WORKER) == "none"
        assert can_manage_tools(UserRole.WORKER) == "none"

    def test_approve_task_owner(self):
        """Owner can approve any task."""
        result = can_approve_task(UserRole.OWNER)
        assert result.allowed is True

    def test_approve_task_pto_same_object(self):
        """PTO can approve tasks on their object."""
        result = can_approve_task(
            UserRole.PTO,
            user_object_id=1,
            task_object_id=1,
        )
        assert result.allowed is True

    def test_approve_task_pto_different_object(self):
        """PTO cannot approve tasks on other objects."""
        result = can_approve_task(
            UserRole.PTO,
            user_object_id=1,
            task_object_id=2,
        )
        assert result.allowed is False

    def test_view_task_owner(self):
        """Owner can view any task."""
        assert can_view_task(
            UserRole.OWNER, 1, 2, 3
        ) is True

    def test_view_task_worker_own(self):
        """Worker can view own tasks."""
        assert can_view_task(
            UserRole.WORKER, 1, 1, 2
        ) is True

    def test_view_task_worker_other(self):
        """Worker cannot view others' tasks."""
        assert can_view_task(
            UserRole.WORKER, 1, 2, 3
        ) is False

    def test_view_task_foreman_own_crew(self):
        """Foreman can view own crew tasks."""
        assert can_view_task(
            UserRole.FOREMAN, 1, 2, 1
        ) is True


class TestTaskTransitions:
    """Test task status transitions."""

    def test_worker_can_start_task(self):
        """Worker can start assigned task."""
        actions = get_allowed_transitions(UserRole.WORKER, TaskStatus.ASSIGNED)
        assert "start" in actions

    def test_worker_can_submit_for_review(self):
        """Worker can submit in-progress task for review."""
        actions = get_allowed_transitions(UserRole.WORKER, TaskStatus.IN_PROGRESS)
        assert "submit_for_review" in actions

    def test_foreman_can_approve(self):
        """Foreman can approve under-review task."""
        actions = get_allowed_transitions(UserRole.FOREMAN, TaskStatus.UNDER_REVIEW)
        assert "approve" in actions
        assert "reject" in actions

    def test_director_can_pay(self):
        """Director can pay approved task."""
        actions = get_allowed_transitions(UserRole.GENERAL_DIRECTOR, TaskStatus.APPROVED_BY_FOREMAN)
        assert "pay" in actions

    def test_worker_cannot_approve(self):
        """Worker cannot approve tasks."""
        actions = get_allowed_transitions(UserRole.WORKER, TaskStatus.UNDER_REVIEW)
        assert "approve" not in actions

    def test_worker_cannot_pay(self):
        """Worker cannot pay tasks."""
        actions = get_allowed_transitions(UserRole.WORKER, TaskStatus.APPROVED_BY_FOREMAN)
        assert "pay" not in actions

    def test_electrician_can_start(self):
        """Electrician can start assigned task."""
        actions = get_allowed_transitions(UserRole.ELECTRICIAN, TaskStatus.ASSIGNED)
        assert "start" in actions

    def test_no_actions_for_paid_task(self):
        """No transitions available for paid task."""
        actions = get_allowed_transitions(UserRole.WORKER, TaskStatus.PAID_BY_DIRECTOR)
        assert len(actions) == 0


class TestCheckPermission:
    """Test check_permission function."""

    def test_check_permission_allowed(self):
        """Check permission returns allowed for valid action."""
        result = check_permission(UserRole.OWNER, "create_task")
        assert result.allowed is True
        assert result.reason == ""

    def test_check_permission_denied(self):
        """Check permission returns denied for invalid action."""
        result = check_permission(UserRole.WORKER, "create_task")
        assert result.allowed is False
        assert "не имеет права" in result.reason

    def test_check_permission_unknown_action(self):
        """Check permission returns denied for unknown action."""
        result = check_permission(UserRole.OWNER, "unknown_action")
        assert result.allowed is False