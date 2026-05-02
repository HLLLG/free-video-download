from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import Request

from ..membership.dependencies import get_active_membership_from_request, summary_max_duration_for_user
from ..membership.db import MembershipUser
from .models import SummaryError
from .settings import SUMMARY_DAILY_LIMIT_PER_IP


@dataclass
class UsageCounter:
    day: str
    count: int = 0


@dataclass
class SummaryAccessContext:
    client_ip: str
    membership_user: MembershipUser | None = None

    @property
    def is_pro(self) -> bool:
        return bool(self.membership_user and self.membership_user.is_pro_active)

    @property
    def max_duration_seconds(self) -> int:
        return summary_max_duration_for_user(self.membership_user)


SUMMARY_USAGE: dict[str, UsageCounter] = {}


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def get_summary_access_context(request: Request) -> SummaryAccessContext:
    return SummaryAccessContext(
        client_ip=get_client_ip(request),
        membership_user=await get_active_membership_from_request(request),
    )


def assert_daily_limit(access: SummaryAccessContext) -> None:
    # SUMMARY_DAILY_LIMIT_PER_IP <= 0 表示不限制，方便 MVP / 测试期不开启额度。
    if access.is_pro:
        return
    if SUMMARY_DAILY_LIMIT_PER_IP <= 0:
        return
    client_ip = access.client_ip
    today = date.today().isoformat()
    counter = SUMMARY_USAGE.get(client_ip)
    if not counter or counter.day != today:
        SUMMARY_USAGE[client_ip] = UsageCounter(day=today, count=0)
        return
    if counter.count >= SUMMARY_DAILY_LIMIT_PER_IP:
        raise SummaryError(
            f"当前免费版每天最多总结 {SUMMARY_DAILY_LIMIT_PER_IP} 个视频，请明天再试或升级 Pro。"
        )


def increment_usage(access: SummaryAccessContext) -> None:
    if access.is_pro:
        return
    if SUMMARY_DAILY_LIMIT_PER_IP <= 0:
        return
    client_ip = access.client_ip
    today = date.today().isoformat()
    counter = SUMMARY_USAGE.get(client_ip)
    if not counter or counter.day != today:
        SUMMARY_USAGE[client_ip] = UsageCounter(day=today, count=1)
        return
    counter.count += 1

