"""Shared D1 policy validation for already-formed query revisions."""
from __future__ import annotations

from src.objectives import _validate_objectives, _validate_user_constraints
from src.platform_contracts import UserQueryRevision


def validate_query_revision(revision: UserQueryRevision) -> UserQueryRevision:
    """Validate objective registry pins and user/platform policy boundaries.

    Structural parsing alone intentionally cannot consult the objective registry.
    Every admission path for an existing revision must call this policy validator.
    """
    if not isinstance(revision, UserQueryRevision):
        raise TypeError("revision must be a UserQueryRevision")
    _validate_objectives(revision.objectives)
    _validate_user_constraints(revision.user_constraints)
    return revision


__all__ = ["validate_query_revision"]
