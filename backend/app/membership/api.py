from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .db import activate_membership
from .dependencies import get_membership_key_from_request, get_membership_user_from_request
from .settings import (
    FREE_SUMMARY_MAX_DURATION_SECONDS,
    PRO_SUMMARY_MAX_DURATION_SECONDS,
    STRIPE_PUBLISHABLE_KEY,
)
from .stripe_service import MembershipError, create_checkout_session, process_webhook, verify_checkout_success


router = APIRouter(tags=["membership"])


class CheckoutRequest(BaseModel):
    plan_type: str = Field(..., min_length=1, max_length=32)


class ActivateMembershipRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(..., min_length=3, max_length=320)
    membership_key: str = Field(..., min_length=16, max_length=256)


def _http_error(exc: MembershipError) -> HTTPException:
    message = str(exc)
    status = 400
    if "签名校验失败" in message:
        status = 400
    elif "缺少 Stripe session_id" in message:
        status = 400
    elif "支付尚未完成" in message:
        status = 409
    elif "未配置" in message:
        status = 503
    return HTTPException(status_code=status, detail=message)


def _status_response(user, membership_key: str | None = None) -> dict:
    is_pro = bool(user and user.is_pro_active)
    return {
        "has_membership": bool(user),
        "is_pro": is_pro,
        "email": user.email if user else None,
        "membership_key": membership_key or (user.membership_key if user else None),
        "pro_expires_at": user.pro_expires_at if user else None,
        "summary_max_duration_seconds": (
            PRO_SUMMARY_MAX_DURATION_SECONDS if is_pro else FREE_SUMMARY_MAX_DURATION_SECONDS
        ),
        "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY or None,
    }


@router.post("/stripe/create-checkout")
async def create_checkout(payload: CheckoutRequest, request: Request) -> dict:
    current_user = await get_membership_user_from_request(request)
    try:
        session = await create_checkout_session(
            request,
            plan_type=payload.plan_type,
            idempotency_key=request.headers.get("x-checkout-intent-key", ""),
            customer_email=current_user.email if current_user else None,
        )
    except MembershipError as exc:
        raise _http_error(exc) from exc

    return {
        "checkout_url": session.url,
        "session_id": session.id,
    }


@router.get("/stripe/checkout-success")
async def checkout_success(session_id: str = Query(..., min_length=1, max_length=255)) -> dict:
    try:
        result = await verify_checkout_success(session_id)
    except MembershipError as exc:
        raise _http_error(exc) from exc

    return {
        "email": result.email,
        "membership_key": result.membership_key,
        "pro_expires_at": result.pro_expires_at,
        "plan_type": result.plan_type,
        "is_pro": True,
        "summary_max_duration_seconds": PRO_SUMMARY_MAX_DURATION_SECONDS,
        "processed": result.processed,
    }


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request) -> dict:
    payload = await request.body()
    try:
        result = await process_webhook(payload, request.headers.get("stripe-signature"))
    except MembershipError as exc:
        raise _http_error(exc) from exc
    return {
        "ok": True,
        "event_type": result.event_type,
        "processed": result.processed,
        "session_id": result.session_id,
    }


@router.post("/membership/activate")
async def membership_activate(payload: ActivateMembershipRequest) -> dict:
    user = await activate_membership(payload.email, payload.membership_key)
    if not user:
        raise HTTPException(status_code=404, detail="邮箱和会员密钥不匹配，请检查后重试。")
    return _status_response(user, membership_key=payload.membership_key)


@router.get("/membership/status")
async def membership_status(request: Request) -> dict:
    membership_key = get_membership_key_from_request(request)
    user = await get_membership_user_from_request(request)
    return _status_response(user, membership_key=membership_key or None)
