from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .db import (
    activate_membership,
    authenticate_user,
    create_auth_session,
    delete_auth_session,
    register_user_with_password,
)
from .dependencies import (
    get_auth_token_from_request,
    get_auth_user_from_request,
    get_membership_key_from_request,
    get_membership_user_from_request,
)
from .settings import (
    AUTH_MIN_PASSWORD_LENGTH,
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


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)
    membership_key: str | None = Field(default=None, max_length=256)


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)


def _http_error(exc: MembershipError) -> HTTPException:
    message = str(exc)
    status = 400
    if "签名校验失败" in message:
        status = 400
    elif "缺少 Stripe session_id" in message:
        status = 400
    elif "支付尚未完成" in message:
        status = 409
    elif "未配置" in message or "配置无效" in message or "密钥无效" in message:
        status = 503
    return HTTPException(status_code=status, detail=message)


def _status_response(user, membership_key: str | None = None) -> dict:
    has_membership = bool(user and user.pro_expires_at)
    is_pro = bool(user and user.is_pro_active)
    return {
        "has_membership": has_membership,
        "is_pro": is_pro,
        "email": user.email if user else None,
        "membership_key": (membership_key or (user.membership_key if user else None)) if has_membership else None,
        "pro_expires_at": user.pro_expires_at if has_membership else None,
        "summary_max_duration_seconds": (
            PRO_SUMMARY_MAX_DURATION_SECONDS if is_pro else FREE_SUMMARY_MAX_DURATION_SECONDS
        ),
        "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY or None,
    }


def _auth_response(user, *, auth_token: str | None = None, auth_expires_at: str | None = None) -> dict:
    payload = _status_response(user)
    payload.update(
        {
            "logged_in": bool(user),
            "auth_token": auth_token,
            "auth_expires_at": auth_expires_at,
        }
    )
    return payload


@router.post("/auth/register")
async def auth_register(payload: RegisterRequest) -> dict:
    if len(payload.password) < AUTH_MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"密码长度至少 {AUTH_MIN_PASSWORD_LENGTH} 位。")
    try:
        user = await register_user_with_password(
            email=payload.email,
            password=payload.password,
            membership_key=payload.membership_key,
        )
        session = await create_auth_session(user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _auth_response(user, auth_token=session.token, auth_expires_at=session.expires_at)


@router.post("/auth/login")
async def auth_login(payload: LoginRequest) -> dict:
    try:
        user = await authenticate_user(payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not user:
        raise HTTPException(status_code=401, detail="邮箱或密码错误，请重试。")
    session = await create_auth_session(user.id)
    return _auth_response(user, auth_token=session.token, auth_expires_at=session.expires_at)


@router.get("/auth/me")
async def auth_me(request: Request) -> dict:
    user = await get_auth_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录。")
    return _auth_response(user)


@router.post("/auth/logout")
async def auth_logout(request: Request) -> dict:
    await delete_auth_session(get_auth_token_from_request(request))
    return {"ok": True}


@router.post("/stripe/create-checkout")
async def create_checkout(payload: CheckoutRequest, request: Request) -> dict:
    current_user = await get_auth_user_from_request(request)
    if not current_user:
        raise HTTPException(status_code=401, detail="请先登录或注册账号，再购买会员。")
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
        auth_session = await create_auth_session(result.user.id)
    except MembershipError as exc:
        raise _http_error(exc) from exc

    payload = _auth_response(
        result.user,
        auth_token=auth_session.token,
        auth_expires_at=auth_session.expires_at,
    )
    payload.update(
        {
            "plan_type": result.plan_type,
            "processed": result.processed,
        }
    )
    return payload


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
