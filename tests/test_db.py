from __future__ import annotations

from pathlib import Path

import pytest

from tg_shop_bot.db import Database


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.sqlite3")
    await d.init()
    return d


async def test_product_and_keys_lifecycle(db: Database) -> None:
    pid = await db.add_product("Test product", "desc", price=49900)
    assert pid > 0

    added, skipped = await db.add_keys(pid, ["KEY-1", "KEY-2", "KEY-2", " ", "KEY-3"])
    assert added == 3
    assert skipped == 1
    assert await db.count_available_keys(pid) == 3

    await db.upsert_user(111, "alice", "Alice")
    order_id = await db.create_order(111, pid)
    await db.attach_proof(order_id, "FILE_ID_123")

    pending = await db.list_pending_orders()
    assert len(pending) == 1
    assert pending[0].id == order_id

    key = await db.reserve_and_deliver_key(order_id)
    assert key in {"KEY-1", "KEY-2", "KEY-3"}
    assert await db.count_available_keys(pid) == 2

    delivered_key = await db.get_order_key_value(order_id)
    assert delivered_key == key

    order = await db.get_order(order_id)
    assert order is not None
    assert order.status == "delivered"


async def test_reserve_when_pool_empty(db: Database) -> None:
    pid = await db.add_product("Empty", "", price=100)
    await db.upsert_user(222, None, "Bob")
    oid = await db.create_order(222, pid)
    await db.attach_proof(oid, "FILE_ID")
    result = await db.reserve_and_deliver_key(oid)
    assert result is None
    order = await db.get_order(oid)
    assert order is not None
    assert order.status == "failed"


async def test_reject_order(db: Database) -> None:
    pid = await db.add_product("X", "", price=100)
    await db.upsert_user(333, None, "Eve")
    oid = await db.create_order(333, pid)
    await db.reject_order(oid, note="bad screenshot")
    order = await db.get_order(oid)
    assert order is not None
    assert order.status == "rejected"
    assert order.note == "bad screenshot"


async def test_stats(db: Database) -> None:
    pid = await db.add_product("S", "", price=200)
    await db.add_keys(pid, ["A", "B"])
    await db.upsert_user(1, None, "u")
    oid = await db.create_order(1, pid)
    await db.attach_proof(oid, "F")
    await db.reserve_and_deliver_key(oid)
    s = await db.stats()
    assert s["users"] == 1
    assert s["orders_delivered"] == 1
    assert s["keys_available"] == 1
    assert s["keys_sold"] == 1
    assert s["revenue_minor"] == 200
