from __future__ import annotations

from fastapi import Request

from .db import MembershipUser, get_user_by_membership_key
from .settings import FREE_SUMMARY_MAX_DURATION_SECONDS, PRO_SUMMARY_MAX_DURATION_SECONDS

MEMBERSHIP_HEADER_NAME = "x-membership-key"


def get_membership_key_from_request(request: Request) -> str:
    return (request.headers.get(MEMBERSHIP_HEADER_NAME) or "").strip()


async def get_membership_user_from_request(request: Request) -> MembershipUser | None:
    membership_key = get_membership_key_from_request(request)
    return await get_user_by_membership_key(membership_key)


async def get_active_membership_from_request(request: Request) -> MembershipUser | None:
    user = await get_membership_user_from_request(request)
    if user and user.is_pro_active:
        return user
    return None


def summary_max_duration_for_user(user: MembershipUser | None) -> int:
    if user and user.is_pro_active:
        return PRO_SUMMARY_MAX_DURATION_SECONDS
    return FREE_SUMMARY_MAX_DURATION_SECONDS
