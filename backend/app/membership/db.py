from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiosqlite import IntegrityError, Row

from ..database import database_connection


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def generate_membership_key() -> str:
    return secrets.token_urlsafe(32)


@dataclass
class MembershipUser:
    id: int
    email: str
    membership_key: str
    pro_expires_at: str | None
    created_at: str | None
    updated_at: str | None

    @property
    def expires_at(self) -> datetime | None:
        return parse_datetime(self.pro_expires_at)

    @property
    def is_pro_active(self) -> bool:
        expires_at = self.expires_at
        return bool(expires_at and expires_at > utc_now())


@dataclass
class OrderRecord:
    id: int
    stripe_session_id: str
    email: str
    plan_type: str
    amount_cents: int
    currency: str
    status: str
    days_granted: int
    created_at: str | None


def _user_from_row(row: Row | None) -> MembershipUser | None:
    if row is None:
        return None
    return MembershipUser(
        id=row["id"],
        email=row["email"],
        membership_key=row["membership_key"],
        pro_expires_at=row["pro_expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _order_from_row(row: Row | None) -> OrderRecord | None:
    if row is None:
        return None
    return OrderRecord(
        id=row["id"],
        stripe_session_id=row["stripe_session_id"],
        email=row["email"],
        plan_type=row["plan_type"],
        amount_cents=row["amount_cents"],
        currency=row["currency"],
        status=row["status"],
        days_granted=row["days_granted"],
        created_at=row["created_at"],
    )


def extend_expiry(current_expires_at: str | None, days_granted: int) -> str:
    base = parse_datetime(current_expires_at)
    now = utc_now()
    if not base or base < now:
        base = now
    return format_datetime(base + timedelta(days=days_granted)) or format_datetime(now)


async def _fetchone(db, query: str, params: tuple = ()) -> Row | None:
    cursor = await db.execute(query, params)
    try:
        return await cursor.fetchone()
    finally:
        await cursor.close()


async def get_user_by_email(email: str) -> MembershipUser | None:
    async with database_connection() as db:
        row = await _fetchone(
            db,
            "SELECT id, email, membership_key, pro_expires_at, created_at, updated_at FROM users WHERE email = ?",
            (email.strip().lower(),),
        )
    return _user_from_row(row)


async def get_user_by_membership_key(membership_key: str | None) -> MembershipUser | None:
    key = (membership_key or "").strip()
    if not key:
        return None
    async with database_connection() as db:
        row = await _fetchone(
            db,
            "SELECT id, email, membership_key, pro_expires_at, created_at, updated_at FROM users WHERE membership_key = ?",
            (key,),
        )
    return _user_from_row(row)


async def get_order_by_session_id(session_id: str) -> OrderRecord | None:
    async with database_connection() as db:
        row = await _fetchone(
            db,
            """
            SELECT id, stripe_session_id, email, plan_type, amount_cents, currency, status, days_granted, created_at
            FROM orders
            WHERE stripe_session_id = ?
            """,
            (session_id,),
        )
    return _order_from_row(row)


async def activate_membership(email: str, membership_key: str) -> MembershipUser | None:
    email = email.strip().lower()
    key = membership_key.strip()
    if not email or not key:
        return None
    async with database_connection() as db:
        row = await _fetchone(
            db,
            """
            SELECT id, email, membership_key, pro_expires_at, created_at, updated_at
            FROM users
            WHERE email = ? AND membership_key = ?
            """,
            (email, key),
        )
    return _user_from_row(row)


async def record_membership_purchase(
    *,
    stripe_session_id: str,
    email: str,
    plan_type: str,
    amount_cents: int,
    currency: str,
    days_granted: int,
) -> tuple[MembershipUser, OrderRecord, bool]:
    normalized_email = email.strip().lower()
    created_at = format_datetime(utc_now())

    async with database_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        existing_order_row = await _fetchone(
            db,
            """
            SELECT id, stripe_session_id, email, plan_type, amount_cents, currency, status, days_granted, created_at
            FROM orders
            WHERE stripe_session_id = ?
            """,
            (stripe_session_id,),
        )
        if existing_order_row is not None:
            await db.commit()
            order = _order_from_row(existing_order_row)
            user_row = await _fetchone(
                db,
                """
                SELECT id, email, membership_key, pro_expires_at, created_at, updated_at
                FROM users
                WHERE email = ?
                """,
                (order.email,),
            )
            user = _user_from_row(user_row)
            if not user or not order:
                raise RuntimeError("已存在的订单缺少关联用户，请检查数据库状态")
            return user, order, False

        user_row = await _fetchone(
            db,
            """
            SELECT id, email, membership_key, pro_expires_at, created_at, updated_at
            FROM users
            WHERE email = ?
            """,
            (normalized_email,),
        )

        new_expiry = extend_expiry(
            user_row["pro_expires_at"] if user_row is not None else None,
            days_granted,
        )
        updated_at = created_at

        if user_row is None:
            membership_key = generate_membership_key()
            await db.execute(
                """
                INSERT INTO users (email, membership_key, pro_expires_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (normalized_email, membership_key, new_expiry, created_at, updated_at),
            )
        else:
            await db.execute(
                """
                UPDATE users
                SET pro_expires_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_expiry, updated_at, user_row["id"]),
            )

        try:
            await db.execute(
                """
                INSERT INTO orders (
                    stripe_session_id,
                    email,
                    plan_type,
                    amount_cents,
                    currency,
                    status,
                    days_granted,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, 'completed', ?, ?)
                """,
                (
                    stripe_session_id,
                    normalized_email,
                    plan_type,
                    amount_cents,
                    currency,
                    days_granted,
                    created_at,
                ),
            )
        except IntegrityError:
            await db.rollback()
            existing_order = await get_order_by_session_id(stripe_session_id)
            existing_user = await get_user_by_email(normalized_email)
            if not existing_order or not existing_user:
                raise
            return existing_user, existing_order, False

        await db.commit()

    user = await get_user_by_email(normalized_email)
    order = await get_order_by_session_id(stripe_session_id)
    if not user or not order:
        raise RuntimeError("订单写入成功但查询失败，请检查数据库状态")
    return user, order, True
