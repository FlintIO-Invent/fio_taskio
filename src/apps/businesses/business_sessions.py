from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core import signing
from django.db import connection, transaction

from .models import BusinessUser

SUPPORTED_DATABASE_SESSION_ENGINES = frozenset(
    {
        "django.contrib.sessions.backends.db",
        "django.contrib.sessions.backends.cached_db",
    }
)


class SelectiveSessionInvalidationUnavailable(RuntimeError):
    """Raised when the configured session backend cannot be inspected safely."""


@dataclass(frozen=True, slots=True)
class BusinessSessionInvalidationSummary:
    sessions_to_invalidate: int
    target_business_sessions: int
    sole_membership_user_sessions: int
    corrupted_sessions_skipped: int

    def to_record_counts(self) -> dict[str, int]:
        return {
            "sessions_invalidated": self.sessions_to_invalidate,
            "target_business_sessions": self.target_business_sessions,
            "sole_membership_user_sessions": self.sole_membership_user_sessions,
            "corrupted_sessions_skipped": self.corrupted_sessions_skipped,
        }


@dataclass(frozen=True, slots=True)
class _BusinessSessionSelection:
    session_keys: tuple[str, ...]
    summary: BusinessSessionInvalidationSummary


def decode_session_data_safely(session_data: str) -> dict[str, object] | None:
    """Decode a Django session without logging corrupt data or exposing contents."""
    session_store_class = import_module(settings.SESSION_ENGINE).SessionStore
    session_store = session_store_class()
    try:
        decoded = signing.loads(
            session_data,
            salt=session_store.key_salt,
            serializer=session_store.serializer,
        )
    except Exception:
        return None
    return decoded if isinstance(decoded, dict) else None


def plan_business_session_invalidation(
    business_id: int,
) -> BusinessSessionInvalidationSummary:
    return _select_business_sessions(business_id).summary


def invalidate_business_sessions(
    business_id: int,
) -> BusinessSessionInvalidationSummary:
    """Selectively remove sessions for a business inside the caller's transaction."""
    if not connection.in_atomic_block:
        raise RuntimeError("Business session invalidation requires an active transaction.")

    selection = _select_business_sessions(business_id)
    if not selection.session_keys:
        return selection.summary

    Session.objects.filter(session_key__in=selection.session_keys).delete()
    if settings.SESSION_ENGINE == "django.contrib.sessions.backends.cached_db":
        session_keys = selection.session_keys
        transaction.on_commit(
            lambda: _clear_cached_sessions(session_keys),
            robust=True,
        )
    return selection.summary


def _select_business_sessions(business_id: int) -> _BusinessSessionSelection:
    if settings.SESSION_ENGINE not in SUPPORTED_DATABASE_SESSION_ENGINES:
        raise SelectiveSessionInvalidationUnavailable(
            "The configured session backend does not support reliable selective invalidation."
        )

    member_user_ids = set(
        BusinessUser.objects.filter(business_id=business_id).values_list("user_id", flat=True)
    )
    users_with_other_valid_businesses = set(
        BusinessUser.objects.filter(
            user_id__in=member_user_ids,
            is_active=True,
            business__is_active=True,
        )
        .exclude(business_id=business_id)
        .values_list("user_id", flat=True)
    )
    sole_membership_user_ids = member_user_ids - users_with_other_valid_businesses

    selected_session_keys: list[str] = []
    target_business_sessions = 0
    sole_membership_user_sessions = 0
    corrupted_sessions_skipped = 0
    for session in (
        Session.objects.all().only("session_key", "session_data").iterator(chunk_size=500)
    ):
        decoded = decode_session_data_safely(session.session_data)
        if decoded is None:
            corrupted_sessions_skipped += 1
            continue

        session_business_id = _safe_positive_int(decoded.get("current_business_id"))
        session_user_id = _safe_positive_int(decoded.get("_auth_user_id"))
        points_to_business = session_business_id == business_id
        belongs_to_sole_member = session_user_id in sole_membership_user_ids
        if not points_to_business and not belongs_to_sole_member:
            continue

        selected_session_keys.append(session.session_key)
        target_business_sessions += int(points_to_business)
        sole_membership_user_sessions += int(belongs_to_sole_member)

    summary = BusinessSessionInvalidationSummary(
        sessions_to_invalidate=len(selected_session_keys),
        target_business_sessions=target_business_sessions,
        sole_membership_user_sessions=sole_membership_user_sessions,
        corrupted_sessions_skipped=corrupted_sessions_skipped,
    )
    return _BusinessSessionSelection(tuple(selected_session_keys), summary)


def _clear_cached_sessions(session_keys: tuple[str, ...]) -> None:
    session_store_class = import_module(settings.SESSION_ENGINE).SessionStore
    for session_key in session_keys:
        session_store_class(session_key=session_key).delete(session_key)


def _safe_positive_int(value: object) -> int | None:
    try:
        normalized = int(str(value))
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None
