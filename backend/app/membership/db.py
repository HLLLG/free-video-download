from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiosqlite import IntegrityError, Row

from ..database import database_connection
from .settings import AUTH_MIN_PASSWORD_LENGTH, AUTH_SESSION_TTL_DAYS


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


def generate_auth_token() -> str:
    return secrets.token_urlsafe(40)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    secret = (password or "").encode("utf-8")
    if salt:
        salt_bytes = bytes.fromhex(salt)
    else:
        salt_bytes = secrets.token_bytes(16)
        salt = salt_bytes.hex()
    digest = hashlib.pbkdf2_hmac("sha256", secret, salt_bytes, 120_000).hex()
    return digest, salt


def verify_password(password: str, expected_hash: str | None, salt: str | None) -> bool:
    if not expected_hash or not salt:
        return False
    actual_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(actual_hash, expected_hash)


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


@dataclass
class AuthSession:
    token: str
    expires_at: str


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
            (normalize_email(email),),
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
    email = normalize_email(email)
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


async def _get_user_auth_fields_by_email(email: str) -> tuple[Row | None, str | None, str | None]:
    async with database_connection() as db:
        row = await _fetchone(
            db,
            """
            SELECT id, email, membership_key, pro_expires_at, created_at, updated_at, password_hash, password_salt
            FROM users
            WHERE email = ?
            """,
            (normalize_email(email),),
        )
    if row is None:
        return None, None, None
    return row, row["password_hash"], row["password_salt"]


async def register_user_with_password(
    *,
    email: str,
    password: str,
    membership_key: str | None = None,
) -> MembershipUser:
    normalized_email = normalize_email(email)
    password = password or ""
    provided_key = (membership_key or "").strip()
    if not normalized_email:
        raise ValueError("请输入有效的邮箱地址。")
    if len(password) < AUTH_MIN_PASSWORD_LENGTH:
        raise ValueError(f"密码长度至少 {AUTH_MIN_PASSWORD_LENGTH} 位。")

    password_hash, password_salt = hash_password(password)
    created_at = format_datetime(utc_now())
    if not created_at:
        raise RuntimeError("生成注册时间失败，请稍后重试。")

    async with database_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        existing_user = await _fetchone(
            db,
            """
            SELECT id, email, membership_key, pro_expires_at, created_at, updated_at, password_hash, password_salt
            FROM users
            WHERE email = ?
            """,
            (normalized_email,),
        )

        if existing_user is not None:
            if existing_user["password_hash"]:
                await db.rollback()
                raise ValueError("该邮箱已注册，请直接登录。")
            existing_key = (existing_user["membership_key"] or "").strip()
            if existing_key and existing_key != provided_key:
                await db.rollback()
                raise ValueError("该邮箱已有会员记录，请填写正确的会员密钥完成绑定。")
            await db.execute(
                """
                UPDATE users
                SET password_hash = ?, password_salt = ?, updated_at = ?
                WHERE id = ?
                """,
                (password_hash, password_salt, created_at, existing_user["id"]),
            )
            await db.commit()
            user = await get_user_by_email(normalized_email)
            if not user:
                raise RuntimeError("账号绑定成功但查询失败，请稍后重试。")
            return user

        if provided_key:
            await db.rollback()
            raise ValueError("该会员密钥未匹配到历史账号，请清空会员密钥后重新注册。")

        membership = generate_membership_key()
        await db.execute(
            """
            INSERT INTO users (
                email,
                membership_key,
                pro_expires_at,
                password_hash,
                password_salt,
                created_at,
                updated_at
            )
            VALUES (?, ?, NULL, ?, ?, ?, ?)
            """,
            (normalized_email, membership, password_hash, password_salt, created_at, created_at),
        )
        await db.commit()

    user = await get_user_by_email(normalized_email)
    if not user:
        raise RuntimeError("注册成功但用户读取失败，请稍后重试。")
    return user


async def authenticate_user(email: str, password: str) -> MembershipUser | None:
    normalized_email = normalize_email(email)
    row, password_hash, password_salt = await _get_user_auth_fields_by_email(normalized_email)
    if row is None:
        return None
    if not password_hash:
        raise ValueError("该邮箱已存在会员记录，请先在注册页完成账号绑定。")
    if not verify_password(password, password_hash, password_salt):
        return None
    return _user_from_row(row)


async def create_auth_session(user_id: int) -> AuthSession:
    now = utc_now()
    created_at = format_datetime(now)
    expires_at = format_datetime(now + timedelta(days=AUTH_SESSION_TTL_DAYS))
    if not created_at or not expires_at:
        raise RuntimeError("生成登录会话失败，请稍后重试。")
    token = generate_auth_token()
    async with database_connection() as db:
        await db.execute(
            """
            INSERT INTO auth_sessions (user_id, session_token, expires_at, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, token, expires_at, created_at, created_at),
        )
        await db.commit()
    return AuthSession(token=token, expires_at=expires_at)


async def get_user_by_auth_token(session_token: str | None) -> MembershipUser | None:
    token = (session_token or "").strip()
    if not token:
        return None

    async with database_connection() as db:
        row = await _fetchone(
            db,
            """
            SELECT
                u.id,
                u.email,
                u.membership_key,
                u.pro_expires_at,
                u.created_at,
                u.updated_at,
                s.expires_at AS session_expires_at
            FROM auth_sessions s
            INNER JOIN users u ON u.id = s.user_id
            WHERE s.session_token = ?
            """,
            (token,),
        )
        if row is None:
            return None

        expires_at = parse_datetime(row["session_expires_at"])
        now = utc_now()
        if not expires_at or expires_at <= now:
            await db.execute("DELETE FROM auth_sessions WHERE session_token = ?", (token,))
            await db.commit()
            return None

        await db.execute(
            "UPDATE auth_sessions SET last_seen_at = ? WHERE session_token = ?",
            (format_datetime(now), token),
        )
        await db.commit()

    return _user_from_row(row)


async def delete_auth_session(session_token: str | None) -> bool:
    token = (session_token or "").strip()
    if not token:
        return False
    async with database_connection() as db:
        cursor = await db.execute("DELETE FROM auth_sessions WHERE session_token = ?", (token,))
        await db.commit()
        deleted = cursor.rowcount > 0
        await cursor.close()
    return deleted
