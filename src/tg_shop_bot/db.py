from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    created_at  TEXT NOT NULL,
    is_blocked  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price       INTEGER NOT NULL,                 -- in minor units (e.g. kopecks)
    currency    TEXT NOT NULL DEFAULT 'RUB',
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    value       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'available', -- available | sold
    sold_at     TEXT,
    sold_to     INTEGER,
    order_id    INTEGER,
    created_at  TEXT NOT NULL,
    UNIQUE (product_id, value)
);
CREATE INDEX IF NOT EXISTS idx_keys_pool ON keys(product_id, status);

CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    product_id   INTEGER NOT NULL REFERENCES products(id),
    status       TEXT NOT NULL,
        -- awaiting_proof | proof_sent | approved | rejected | delivered | failed
    proof_file_id TEXT,
    key_id       INTEGER REFERENCES keys(id),
    note         TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
"""


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class Product:
    id: int
    name: str
    description: str
    price: int
    currency: str
    is_active: bool

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> Product:
        return cls(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            price=row["price"],
            currency=row["currency"],
            is_active=bool(row["is_active"]),
        )

    @property
    def price_display(self) -> str:
        major = self.price / 100
        if self.currency == "RUB":
            return f"{major:.2f} ₽".replace(".", ",")
        return f"{major:.2f} {self.currency}"


@dataclass(slots=True)
class Order:
    id: int
    user_id: int
    product_id: int
    status: str
    proof_file_id: str | None
    key_id: int | None
    note: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> Order:
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            product_id=row["product_id"],
            status=row["status"],
            proof_file_id=row["proof_file_id"],
            key_id=row["key_id"],
            note=row["note"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class Database:
    def __init__(self, path: Path):
        self.path = path

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self._connect() as conn:
            await conn.executescript(SCHEMA)
            await conn.commit()

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        conn = await aiosqlite.connect(self.path)
        try:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute("PRAGMA journal_mode = WAL")
            yield conn
        finally:
            await conn.close()

    # ---------- users ----------

    async def upsert_user(self, user_id: int, username: str | None, full_name: str) -> None:
        async with self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO users(user_id, username, full_name, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name
                """,
                (user_id, username, full_name, utcnow_iso()),
            )
            await conn.commit()

    # ---------- products ----------

    async def add_product(
        self, name: str, description: str, price: int, currency: str = "RUB"
    ) -> int:
        async with self._connect() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO products(name, description, price, currency, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (name, description, price, currency, utcnow_iso()),
            )
            await conn.commit()
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    async def list_products(self, only_active: bool = True) -> list[Product]:
        sql = "SELECT * FROM products"
        params: tuple = ()
        if only_active:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY id"
        async with self._connect() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            return [Product.from_row(r) for r in rows]

    async def get_product(self, product_id: int) -> Product | None:
        async with self._connect() as conn:
            cursor = await conn.execute("SELECT * FROM products WHERE id = ?", (product_id,))
            row = await cursor.fetchone()
            return Product.from_row(row) if row else None

    async def set_product_active(self, product_id: int, is_active: bool) -> None:
        async with self._connect() as conn:
            await conn.execute(
                "UPDATE products SET is_active = ? WHERE id = ?",
                (1 if is_active else 0, product_id),
            )
            await conn.commit()

    async def delete_product(self, product_id: int) -> None:
        async with self._connect() as conn:
            await conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
            await conn.commit()

    # ---------- keys ----------

    async def add_keys(self, product_id: int, values: list[str]) -> tuple[int, int]:
        """Return (added, duplicates_skipped)."""
        added = 0
        skipped = 0
        async with self._connect() as conn:
            for v in values:
                v = v.strip()
                if not v:
                    continue
                try:
                    await conn.execute(
                        """
                        INSERT INTO keys(product_id, value, status, created_at)
                        VALUES (?, ?, 'available', ?)
                        """,
                        (product_id, v, utcnow_iso()),
                    )
                    added += 1
                except sqlite3.IntegrityError:
                    skipped += 1
            await conn.commit()
        return added, skipped

    async def count_available_keys(self, product_id: int) -> int:
        async with self._connect() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) AS c FROM keys WHERE product_id = ? AND status = 'available'",
                (product_id,),
            )
            row = await cursor.fetchone()
            return int(row["c"]) if row else 0

    async def reserve_and_deliver_key(self, order_id: int) -> str | None:
        """Atomically pick an available key for the order's product, mark it sold,
        and link it to the order. Returns the key value, or None if no keys left."""
        async with self._connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = await conn.execute(
                    "SELECT product_id, user_id, status FROM orders WHERE id = ?",
                    (order_id,),
                )
                order_row = await cursor.fetchone()
                if order_row is None:
                    await conn.rollback()
                    return None

                cursor = await conn.execute(
                    """
                    SELECT id, value FROM keys
                    WHERE product_id = ? AND status = 'available'
                    ORDER BY id
                    LIMIT 1
                    """,
                    (order_row["product_id"],),
                )
                key_row = await cursor.fetchone()
                if key_row is None:
                    await conn.execute(
                        "UPDATE orders SET status = 'failed', updated_at = ? WHERE id = ?",
                        (utcnow_iso(), order_id),
                    )
                    await conn.commit()
                    return None

                now = utcnow_iso()
                await conn.execute(
                    """
                    UPDATE keys
                    SET status = 'sold', sold_at = ?, sold_to = ?, order_id = ?
                    WHERE id = ?
                    """,
                    (now, order_row["user_id"], order_id, key_row["id"]),
                )
                await conn.execute(
                    """
                    UPDATE orders
                    SET status = 'delivered', key_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (key_row["id"], now, order_id),
                )
                await conn.commit()
                return str(key_row["value"])
            except Exception:
                await conn.rollback()
                raise

    # ---------- orders ----------

    async def create_order(self, user_id: int, product_id: int) -> int:
        async with self._connect() as conn:
            now = utcnow_iso()
            cursor = await conn.execute(
                """
                INSERT INTO orders(user_id, product_id, status, created_at, updated_at)
                VALUES (?, ?, 'awaiting_proof', ?, ?)
                """,
                (user_id, product_id, now, now),
            )
            await conn.commit()
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    async def get_order(self, order_id: int) -> Order | None:
        async with self._connect() as conn:
            cursor = await conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
            row = await cursor.fetchone()
            return Order.from_row(row) if row else None

    async def attach_proof(self, order_id: int, file_id: str) -> None:
        async with self._connect() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET status = 'proof_sent', proof_file_id = ?, updated_at = ?
                WHERE id = ? AND status IN ('awaiting_proof', 'rejected', 'proof_sent')
                """,
                (file_id, utcnow_iso(), order_id),
            )
            await conn.commit()

    async def reject_order(self, order_id: int, note: str | None = None) -> None:
        async with self._connect() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET status = 'rejected', note = ?, updated_at = ?
                WHERE id = ?
                """,
                (note, utcnow_iso(), order_id),
            )
            await conn.commit()

    async def find_user_active_order(self, user_id: int) -> Order | None:
        async with self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM orders
                WHERE user_id = ?
                  AND status IN ('awaiting_proof', 'proof_sent')
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = await cursor.fetchone()
            return Order.from_row(row) if row else None

    async def list_user_orders(self, user_id: int, limit: int = 20) -> list[Order]:
        async with self._connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            )
            rows = await cursor.fetchall()
            return [Order.from_row(r) for r in rows]

    async def list_pending_orders(self, limit: int = 20) -> list[Order]:
        async with self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM orders
                WHERE status = 'proof_sent'
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
            return [Order.from_row(r) for r in rows]

    async def get_order_key_value(self, order_id: int) -> str | None:
        async with self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT k.value FROM orders o
                JOIN keys k ON k.id = o.key_id
                WHERE o.id = ?
                """,
                (order_id,),
            )
            row = await cursor.fetchone()
            return str(row["value"]) if row else None

    # ---------- stats ----------

    async def stats(self) -> dict[str, int]:
        async with self._connect() as conn:
            stats: dict[str, int] = {}
            for label, sql in (
                ("users", "SELECT COUNT(*) c FROM users"),
                ("products", "SELECT COUNT(*) c FROM products WHERE is_active = 1"),
                ("orders_total", "SELECT COUNT(*) c FROM orders"),
                ("orders_delivered", "SELECT COUNT(*) c FROM orders WHERE status = 'delivered'"),
                (
                    "orders_pending",
                    "SELECT COUNT(*) c FROM orders WHERE status = 'proof_sent'",
                ),
                ("keys_available", "SELECT COUNT(*) c FROM keys WHERE status = 'available'"),
                ("keys_sold", "SELECT COUNT(*) c FROM keys WHERE status = 'sold'"),
            ):
                cursor = await conn.execute(sql)
                row = await cursor.fetchone()
                stats[label] = int(row["c"]) if row else 0

            cursor = await conn.execute(
                """
                SELECT COALESCE(SUM(p.price), 0) AS total
                FROM orders o JOIN products p ON p.id = o.product_id
                WHERE o.status = 'delivered'
                """
            )
            row = await cursor.fetchone()
            stats["revenue_minor"] = int(row["total"]) if row else 0

        return stats
