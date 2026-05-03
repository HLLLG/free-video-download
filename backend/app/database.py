from __future__ import annotations

from contextlib import asynccontextmanager

import aiosqlite

from .config import DATABASE_PATH


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    membership_key TEXT UNIQUE NOT NULL,
    pro_expires_at TEXT,
    password_hash TEXT,
    password_salt TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stripe_session_id TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    plan_type TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT DEFAULT 'cny',
    status TEXT DEFAULT 'completed',
    days_granted INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_email_created_at ON orders(email, created_at DESC);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    session_token TEXT UNIQUE NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at);
"""


async def _ensure_users_table_columns(db) -> None:
    cursor = await db.execute("PRAGMA table_info(users)")
    try:
        columns = {row[1] for row in await cursor.fetchall()}
    finally:
        await cursor.close()

    if "password_hash" not in columns:
        await db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    if "password_salt" not in columns:
        await db.execute("ALTER TABLE users ADD COLUMN password_salt TEXT")


async def init_database() -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        await _ensure_users_table_columns(db)
        await db.commit()


@asynccontextmanager
async def database_connection():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        yield db
