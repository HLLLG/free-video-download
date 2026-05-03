from __future__ import annotations

from fastapi import Request

from .db import MembershipUser, get_user_by_auth_token, get_user_by_membership_key
from .settings import FREE_SUMMARY_MAX_DURATION_SECONDS, PRO_SUMMARY_MAX_DURATION_SECONDS

MEMBERSHIP_HEADER_NAME = "x-membership-key"
AUTH_HEADER_NAME = "x-auth-token"


def get_membership_key_from_request(request: Request) -> str:
    return (request.headers.get(MEMBERSHIP_HEADER_NAME) or "").strip()


def get_auth_token_from_request(request: Request) -> str:
    return (request.headers.get(AUTH_HEADER_NAME) or "").strip()


async def get_auth_user_from_request(request: Request) -> MembershipUser | None:
    auth_token = get_auth_token_from_request(request)
    return await get_user_by_auth_token(auth_token)


async def get_membership_user_from_request(request: Request) -> MembershipUser | None:
    auth_user = await get_auth_user_from_request(request)
    if auth_user:
        return auth_user
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
