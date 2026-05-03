from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import Request
from stripe import SignatureVerificationError, StripeClient, Webhook

from .db import MembershipUser, record_membership_purchase
from .settings import (
    STRIPE_APP_BASE_URL,
    STRIPE_CURRENCY,
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    MembershipPlan,
    get_membership_plan,
)


class MembershipError(Exception):
    """Raised when membership or Stripe operations cannot be completed safely."""


@dataclass
class CheckoutFulfillmentResult:
    user: MembershipUser
    session_id: str
    email: str
    plan_type: str
    pro_expires_at: str | None
    membership_key: str
    processed: bool


@dataclass
class WebhookProcessResult:
    event_type: str
    processed: bool
    session_id: str | None = None


def _value(obj, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _get_stripe_client() -> StripeClient:
    if not STRIPE_SECRET_KEY:
        raise MembershipError("后端尚未配置 STRIPE_SECRET_KEY，暂时无法创建支付订单。")
    if not STRIPE_SECRET_KEY.startswith("sk_"):
        raise MembershipError("STRIPE_SECRET_KEY 配置无效：请使用 sk_ 开头的 Stripe 服务端密钥。")
    return StripeClient(STRIPE_SECRET_KEY)


def _resolve_frontend_base_url(request: Request) -> str:
    if STRIPE_APP_BASE_URL:
        return STRIPE_APP_BASE_URL
    origin = (request.headers.get("origin") or "").strip().rstrip("/")
    if origin:
        return origin
    referer = (request.headers.get("referer") or "").strip()
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return str(request.base_url).rstrip("/")


def _build_checkout_urls(request: Request) -> tuple[str, str]:
    base_url = _resolve_frontend_base_url(request)
    success_url = f"{base_url}/?checkout=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base_url}/?checkout=cancelled"
    return success_url, cancel_url


def _normalize_intent_key(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise MembershipError("缺少支付请求幂等键，请刷新页面后重试。")
    return cleaned[:255]


def _validate_plan(plan_type: str) -> MembershipPlan:
    try:
        plan = get_membership_plan(plan_type)
    except ValueError as exc:
        raise MembershipError(str(exc)) from exc
    if not plan.price_id:
        raise MembershipError(f"{plan.name}尚未配置 Stripe Price ID，暂时无法购买。")
    return plan


async def create_checkout_session(
    request: Request,
    *,
    plan_type: str,
    idempotency_key: str,
    customer_email: str | None = None,
):
    plan = _validate_plan(plan_type)
    success_url, cancel_url = _build_checkout_urls(request)
    client = _get_stripe_client()

    params = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "customer_creation": "always",
        "line_items": [{"price": plan.price_id, "quantity": 1}],
        "metadata": {
            "plan_type": plan.plan_type,
            "days_granted": str(plan.days_granted),
            "amount_cents": str(plan.amount_cents),
        },
    }
    if customer_email:
        params["customer_email"] = customer_email

    try:
        return client.v1.checkout.sessions.create(
            params=params,
            options={"idempotency_key": _normalize_intent_key(idempotency_key)},
        )
    except Exception as exc:
        message = str(exc)
        if "Invalid API Key provided" in message:
            raise MembershipError("Stripe 密钥无效：请检查 STRIPE_SECRET_KEY 是否填写正确。") from exc
        if "payment" in message and "recurring price" in message:
            raise MembershipError(
                "当前 Price 是订阅型（Recurring），但系统使用一次性支付（payment）模式。"
                "请在 Stripe 创建 one-time Price 后再填写 STRIPE_PRICE_MONTHLY / STRIPE_PRICE_YEARLY。"
            ) from exc
        raise MembershipError(f"创建支付订单失败：{str(exc)[:240]}") from exc


def _plan_from_session(session) -> MembershipPlan:
    metadata = _value(session, "metadata") or {}
    plan_type = _value(metadata, "plan_type") if not isinstance(metadata, dict) else metadata.get("plan_type")
    return _validate_plan(plan_type or "")


def _session_email(session) -> str:
    customer_details = _value(session, "customer_details") or {}
    email = _value(customer_details, "email") if not isinstance(customer_details, dict) else customer_details.get("email")
    email = email or _value(session, "customer_email")
    if not email:
        raise MembershipError("支付成功，但 Stripe 没有返回邮箱，请联系客服处理。")
    return str(email).strip().lower()


def _assert_paid_checkout_session(session) -> None:
    mode = _value(session, "mode")
    payment_status = _value(session, "payment_status")
    if mode != "payment":
        raise MembershipError("当前支付会话不是一次性购买订单，无法发放会员。")
    if payment_status != "paid":
        raise MembershipError("支付尚未完成，请稍后刷新订单状态。")


async def fulfill_checkout_session(session_id: str, session=None) -> CheckoutFulfillmentResult:
    client = _get_stripe_client()
    try:
        checkout_session = session or client.v1.checkout.sessions.retrieve(session_id)
    except Exception as exc:
        raise MembershipError(f"查询支付订单失败：{str(exc)[:240]}") from exc

    _assert_paid_checkout_session(checkout_session)
    plan = _plan_from_session(checkout_session)
    email = _session_email(checkout_session)
    amount_total = _value(checkout_session, "amount_total") or plan.amount_cents
    currency = (_value(checkout_session, "currency") or STRIPE_CURRENCY).lower()

    user, order, processed = await record_membership_purchase(
        stripe_session_id=session_id,
        email=email,
        plan_type=plan.plan_type,
        amount_cents=int(amount_total),
        currency=currency,
        days_granted=plan.days_granted,
    )
    return CheckoutFulfillmentResult(
        user=user,
        session_id=order.stripe_session_id,
        email=user.email,
        plan_type=order.plan_type,
        pro_expires_at=user.pro_expires_at,
        membership_key=user.membership_key,
        processed=processed,
    )


async def verify_checkout_success(session_id: str) -> CheckoutFulfillmentResult:
    if not session_id:
        raise MembershipError("缺少 Stripe session_id，无法确认支付结果。")
    return await fulfill_checkout_session(session_id)


async def process_webhook(payload: bytes, stripe_signature: str | None) -> WebhookProcessResult:
    if not STRIPE_WEBHOOK_SECRET:
        raise MembershipError("后端尚未配置 STRIPE_WEBHOOK_SECRET，无法校验支付回调。")
    if not stripe_signature:
        raise MembershipError("Stripe 回调缺少签名头，已拒绝处理。")

    try:
        event = Webhook.construct_event(payload, stripe_signature, STRIPE_WEBHOOK_SECRET)
    except ValueError as exc:
        raise MembershipError(f"Stripe 回调 payload 无效：{str(exc)[:200]}") from exc
    except SignatureVerificationError as exc:
        raise MembershipError(f"Stripe 回调签名校验失败：{str(exc)[:200]}") from exc

    if event.type != "checkout.session.completed":
        return WebhookProcessResult(event_type=event.type, processed=False)

    session = _value(event, "data")
    session_object = _value(session, "object")
    session_id = _value(session_object, "id")
    if not session_id:
        raise MembershipError("Stripe 回调缺少 Checkout Session ID。")
    result = await fulfill_checkout_session(session_id, session=session_object)
    return WebhookProcessResult(
        event_type=event.type,
        processed=result.processed,
        session_id=result.session_id,
    )
