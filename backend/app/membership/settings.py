from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MembershipPlan:
    plan_type: str
    name: str
    price_id: str
    amount_cents: int
    days_granted: int


STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
STRIPE_APP_BASE_URL = os.getenv("STRIPE_APP_BASE_URL", os.getenv("APP_BASE_URL", "")).strip().rstrip("/")
STRIPE_CURRENCY = os.getenv("STRIPE_CURRENCY", "cny").strip().lower()
AUTH_SESSION_TTL_DAYS = int(os.getenv("AUTH_SESSION_TTL_DAYS", "30"))
AUTH_MIN_PASSWORD_LENGTH = int(os.getenv("AUTH_MIN_PASSWORD_LENGTH", "8"))

FREE_SUMMARY_MAX_DURATION_SECONDS = int(os.getenv("SUMMARY_MAX_DURATION_SECONDS", str(40 * 60)))
PRO_SUMMARY_MAX_DURATION_SECONDS = int(
    os.getenv("PRO_SUMMARY_MAX_DURATION_SECONDS", str(120 * 60))
)

MONTHLY_PLAN = MembershipPlan(
    plan_type="monthly",
    name="Pro 月卡",
    price_id=os.getenv("STRIPE_PRICE_MONTHLY", "").strip(),
    amount_cents=990,
    days_granted=30,
)
YEARLY_PLAN = MembershipPlan(
    plan_type="yearly",
    name="Pro 年卡",
    price_id=os.getenv("STRIPE_PRICE_YEARLY", "").strip(),
    amount_cents=9900,
    days_granted=365,
)

MEMBERSHIP_PLANS = {
    MONTHLY_PLAN.plan_type: MONTHLY_PLAN,
    YEARLY_PLAN.plan_type: YEARLY_PLAN,
}


def get_membership_plan(plan_type: str) -> MembershipPlan:
    plan = MEMBERSHIP_PLANS.get((plan_type or "").strip().lower())
    if not plan:
        raise ValueError("不支持的会员方案")
    return plan
