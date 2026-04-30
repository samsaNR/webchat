from __future__ import annotations

import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Document, Message

from ..config import Settings
from ..db import Database
from ..keyboards import (
    admin_panel,
    admin_pick_product_for_keys,
    admin_product_card,
    admin_products,
    back_to_admin,
    main_menu,
)
from ..states import AddKeys, AddProduct, RejectOrder

router = Router(name="admin")
log = logging.getLogger(__name__)


def _is_admin(settings: Settings, user_id: int | None) -> bool:
    return user_id is not None and settings.is_admin(user_id)


@router.message(Command("admin"))
async def cmd_admin(message: Message, settings: Settings) -> None:
    if not _is_admin(settings, message.from_user.id if message.from_user else None):
        return
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_panel())


@router.callback_query(F.data == "admin")
async def cb_admin(call: CallbackQuery, settings: Settings) -> None:
    if not _is_admin(settings, call.from_user.id if call.from_user else None):
        await call.answer("Доступ только для админов", show_alert=True)
        return
    if call.message and isinstance(call.message, Message):
        await call.message.edit_text("🛠 <b>Админ-панель</b>", reply_markup=admin_panel())
    await call.answer()


# ---------- products list ----------

@router.callback_query(F.data == "adm:list_products")
async def cb_list_products(call: CallbackQuery, settings: Settings, db: Database) -> None:
    if not _is_admin(settings, call.from_user.id if call.from_user else None):
        await call.answer()
        return
    products = await db.list_products(only_active=False)
    if call.message and isinstance(call.message, Message):
        text = "<b>Товары</b>" if products else "Товаров пока нет."
        await call.message.edit_text(text, reply_markup=admin_products(products))
    await call.answer()


@router.callback_query(F.data.startswith("adm:prod:"))
async def cb_admin_product(call: CallbackQuery, settings: Settings, db: Database) -> None:
    if not _is_admin(settings, call.from_user.id if call.from_user else None):
        await call.answer()
        return
    if call.data is None:
        await call.answer()
        return
    product_id = int(call.data.split(":")[2])
    product = await db.get_product(product_id)
    if product is None:
        await call.answer("Товар не найден", show_alert=True)
        return
    available = await db.count_available_keys(product_id)
    text = (
        f"<b>{html.escape(product.name)}</b> "
        f"({'активен' if product.is_active else 'выключен'})\n\n"
        f"{html.escape(product.description) or '—'}\n\n"
        f"💰 Цена: <b>{product.price_display}</b>\n"
        f"📦 Ключей в наличии: <b>{available}</b>"
    )
    if call.message and isinstance(call.message, Message):
        await call.message.edit_text(text, reply_markup=admin_product_card(product))
    await call.answer()


@router.callback_query(F.data.startswith("adm:toggle:"))
async def cb_toggle_product(call: CallbackQuery, settings: Settings, db: Database) -> None:
    if not _is_admin(settings, call.from_user.id if call.from_user else None):
        await call.answer()
        return
    if call.data is None:
        await call.answer()
        return
    product_id = int(call.data.split(":")[2])
    product = await db.get_product(product_id)
    if product is None:
        await call.answer("Товар не найден", show_alert=True)
        return
    await db.set_product_active(product_id, not product.is_active)
    await call.answer("Готово")
    # Re-render the card.
    call.data = f"adm:prod:{product_id}"  # type: ignore[misc]
    await cb_admin_product(call, settings, db)


@router.callback_query(F.data.startswith("adm:del:"))
async def cb_delete_product(call: CallbackQuery, settings: Settings, db: Database) -> None:
    if not _is_admin(settings, call.from_user.id if call.from_user else None):
        await call.answer()
        return
    if call.data is None:
        await call.answer()
        return
    product_id = int(call.data.split(":")[2])
    await db.delete_product(product_id)
    await call.answer("Удалено")
    if call.message and isinstance(call.message, Message):
        products = await db.list_products(only_active=False)
        text = "<b>Товары</b>" if products else "Товаров пока нет."
        await call.message.edit_text(text, reply_markup=admin_products(products))


# ---------- add product flow ----------

@router.callback_query(F.data == "adm:add_product")
async def cb_add_product(call: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not _is_admin(settings, call.from_user.id if call.from_user else None):
        await call.answer()
        return
    await state.set_state(AddProduct.name)
    if call.message and isinstance(call.message, Message):
        await call.message.edit_text(
            "Введите <b>название</b> товара:", reply_markup=back_to_admin()
        )
    await call.answer()


@router.message(AddProduct.name)
async def add_product_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым. Попробуйте ещё раз.")
        return
    await state.update_data(name=name)
    await state.set_state(AddProduct.description)
    await message.answer("Теперь введите <b>описание</b> товара (или «-», чтобы пропустить):")


@router.message(AddProduct.description)
async def add_product_description(message: Message, state: FSMContext) -> None:
    desc = (message.text or "").strip()
    if desc == "-":
        desc = ""
    await state.update_data(description=desc)
    await state.set_state(AddProduct.price)
    await message.answer(
        "Введите <b>цену в рублях</b> (целое или с копейками через точку), например: <code>499</code> или <code>499.50</code>"
    )


@router.message(AddProduct.price)
async def add_product_price(message: Message, db: Database, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    try:
        rubles = float(raw)
        if rubles <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Не похоже на сумму. Введите положительное число, например 499 или 499.50")
        return
    minor = round(rubles * 100)
    data = await state.get_data()
    product_id = await db.add_product(
        name=str(data["name"]),
        description=str(data.get("description", "")),
        price=minor,
        currency="RUB",
    )
    await state.clear()
    await message.answer(
        f"✅ Товар добавлен (id={product_id}). Теперь загрузите ключи через админ-панель.",
        reply_markup=admin_panel(),
    )


# ---------- add keys flow ----------

@router.callback_query(F.data == "adm:add_keys")
async def cb_add_keys_pick(call: CallbackQuery, settings: Settings, db: Database) -> None:
    if not _is_admin(settings, call.from_user.id if call.from_user else None):
        await call.answer()
        return
    products = await db.list_products(only_active=False)
    if not products:
        await call.answer("Сначала добавьте товар", show_alert=True)
        return
    if call.message and isinstance(call.message, Message):
        await call.message.edit_text(
            "Выберите товар, к которому добавить ключи:",
            reply_markup=admin_pick_product_for_keys(products),
        )
    await call.answer()


@router.callback_query(F.data.startswith("adm:keys:"))
async def cb_add_keys_for_product(
    call: CallbackQuery, settings: Settings, db: Database, state: FSMContext
) -> None:
    if not _is_admin(settings, call.from_user.id if call.from_user else None):
        await call.answer()
        return
    if call.data is None:
        await call.answer()
        return
    product_id = int(call.data.split(":")[2])
    product = await db.get_product(product_id)
    if product is None:
        await call.answer("Товар не найден", show_alert=True)
        return
    await state.set_state(AddKeys.waiting_for_keys)
    await state.update_data(product_id=product_id)
    if call.message and isinstance(call.message, Message):
        await call.message.edit_text(
            f"Пришлите ключи для товара <b>{html.escape(product.name)}</b>.\n\n"
            "Можно одним сообщением (по одному ключу в строке) или прикрепить .txt файл.\n"
            "Дубликаты будут пропущены.",
            reply_markup=back_to_admin(),
        )
    await call.answer()


def _parse_keys(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


@router.message(AddKeys.waiting_for_keys, F.document)
async def add_keys_document(
    message: Message, bot: Bot, db: Database, state: FSMContext
) -> None:
    doc: Document | None = message.document
    if doc is None:
        return
    if doc.file_size and doc.file_size > 1_000_000:
        await message.answer("Файл слишком большой (>1 МБ).")
        return
    file = await bot.get_file(doc.file_id)
    if file.file_path is None:
        await message.answer("Не удалось получить файл.")
        return
    data_io = await bot.download_file(file.file_path)
    if data_io is None:
        await message.answer("Не удалось скачать файл.")
        return
    raw = data_io.read().decode("utf-8", errors="replace")
    await _ingest_keys(message, db, state, raw)


@router.message(AddKeys.waiting_for_keys, F.text)
async def add_keys_text(message: Message, db: Database, state: FSMContext) -> None:
    await _ingest_keys(message, db, state, message.text or "")


async def _ingest_keys(
    message: Message, db: Database, state: FSMContext, raw: str
) -> None:
    data = await state.get_data()
    product_id = data.get("product_id")
    if not isinstance(product_id, int):
        await message.answer("Сессия истекла. Откройте админ-панель заново.")
        await state.clear()
        return
    keys = _parse_keys(raw)
    if not keys:
        await message.answer("Не нашёл ни одного ключа в сообщении.")
        return
    added, skipped = await db.add_keys(product_id, keys)
    available = await db.count_available_keys(product_id)
    await state.clear()
    await message.answer(
        f"✅ Готово.\nДобавлено: <b>{added}</b>, пропущено дубликатов: <b>{skipped}</b>.\n"
        f"Сейчас в наличии по этому товару: <b>{available}</b>.",
        reply_markup=admin_panel(),
    )


# ---------- pending list ----------

@router.callback_query(F.data == "adm:pending")
async def cb_pending(call: CallbackQuery, settings: Settings, db: Database, bot: Bot) -> None:
    if not _is_admin(settings, call.from_user.id if call.from_user else None):
        await call.answer()
        return
    orders = await db.list_pending_orders(limit=10)
    if not orders:
        if call.message and isinstance(call.message, Message):
            await call.message.edit_text(
                "Заказов на проверке нет.", reply_markup=back_to_admin()
            )
        await call.answer()
        return
    if call.message and isinstance(call.message, Message):
        await call.message.edit_text(
            f"Заказов на проверке: <b>{len(orders)}</b>. Сейчас отправлю их по одному.",
            reply_markup=back_to_admin(),
        )
    await call.answer()
    from ..keyboards import admin_review

    for order in orders:
        product = await db.get_product(order.product_id)
        product_name = product.name if product else f"#{order.product_id}"
        caption = (
            f"⏳ <b>Заказ #{order.id}</b>\n"
            f"Товар: <b>{html.escape(product_name)}</b>"
            + (f" — <b>{product.price_display}</b>" if product else "")
            + f"\nПокупатель id: <code>{order.user_id}</code>"
        )
        if call.from_user is None:
            continue
        try:
            if order.proof_file_id:
                await bot.send_photo(
                    call.from_user.id,
                    photo=order.proof_file_id,
                    caption=caption,
                    reply_markup=admin_review(order.id),
                )
            else:
                await bot.send_message(
                    call.from_user.id, caption, reply_markup=admin_review(order.id)
                )
        except Exception:
            log.exception("Failed to send pending order %s", order.id)


# ---------- approve / reject ----------

@router.callback_query(F.data.startswith("approve:"))
async def cb_approve(
    call: CallbackQuery, settings: Settings, db: Database, bot: Bot
) -> None:
    if not _is_admin(settings, call.from_user.id if call.from_user else None):
        await call.answer("Доступ только для админов", show_alert=True)
        return
    if call.data is None:
        await call.answer()
        return
    order_id = int(call.data.split(":", 1)[1])
    order = await db.get_order(order_id)
    if order is None:
        await call.answer("Заказ не найден", show_alert=True)
        return
    if order.status == "delivered":
        await call.answer("Уже выдан", show_alert=True)
        return
    if order.status not in ("proof_sent", "approved"):
        await call.answer(f"Нельзя подтвердить (статус: {order.status})", show_alert=True)
        return

    key_value = await db.reserve_and_deliver_key(order_id)
    if key_value is None:
        await call.answer("Закончились ключи!", show_alert=True)
        try:
            await bot.send_message(
                order.user_id,
                f"❗ Заказ #{order_id}: закончились ключи. Свяжитесь с продавцом для возврата.",
            )
        except Exception:
            log.exception("Failed to notify user %s about empty pool", order.user_id)
        return

    product = await db.get_product(order.product_id)
    name = product.name if product else f"#{order.product_id}"
    try:
        await bot.send_message(
            order.user_id,
            (
                f"✅ Оплата по заказу #{order_id} подтверждена!\n\n"
                f"Ваш ключ для <b>{html.escape(name)}</b>:\n"
                f"<code>{html.escape(key_value)}</code>\n\n"
                "Спасибо за покупку! 💚"
            ),
            reply_markup=main_menu(settings.is_admin(order.user_id)),
        )
    except Exception:
        log.exception("Failed to send key to user %s", order.user_id)

    if call.message and isinstance(call.message, Message):
        new_caption = (call.message.caption or call.message.text or "") + (
            f"\n\n✅ Подтверждено. Выдан ключ <code>{html.escape(key_value)}</code>"
        )
        try:
            if call.message.photo:
                await call.message.edit_caption(caption=new_caption)
            else:
                await call.message.edit_text(new_caption)
        except Exception:
            log.exception("Failed to edit admin message for order %s", order_id)
    await call.answer("Выдано")


@router.callback_query(F.data.startswith("reject:"))
async def cb_reject(call: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not _is_admin(settings, call.from_user.id if call.from_user else None):
        await call.answer("Доступ только для админов", show_alert=True)
        return
    if call.data is None or call.message is None:
        await call.answer()
        return
    order_id = int(call.data.split(":", 1)[1])
    await state.set_state(RejectOrder.waiting_for_reason)
    await state.update_data(order_id=order_id, admin_chat_id=call.message.chat.id)
    await call.answer()
    if isinstance(call.message, Message):
        await call.message.reply(
            f"Введите причину отклонения заказа #{order_id} одним сообщением "
            "(она будет отправлена покупателю)."
        )


@router.message(RejectOrder.waiting_for_reason)
async def reject_with_reason(
    message: Message, bot: Bot, db: Database, state: FSMContext, settings: Settings
) -> None:
    if message.from_user is None or not _is_admin(settings, message.from_user.id):
        return
    reason = (message.text or "").strip() or "Оплата не подтверждена"
    data = await state.get_data()
    order_id = data.get("order_id")
    if not isinstance(order_id, int):
        await state.clear()
        return
    order = await db.get_order(order_id)
    if order is None:
        await message.answer("Заказ не найден.")
        await state.clear()
        return
    await db.reject_order(order_id, note=reason)
    await state.clear()
    try:
        await bot.send_message(
            order.user_id,
            f"❌ Заказ #{order_id} отклонён.\nПричина: {html.escape(reason)}\n\n"
            "Если это ошибка — свяжитесь с поддержкой и попробуйте оплатить ещё раз.",
        )
    except Exception:
        log.exception("Failed to notify user %s about rejection", order.user_id)
    await message.answer(f"Заказ #{order_id} отклонён, покупатель уведомлён.")


# ---------- stats ----------

@router.callback_query(F.data == "adm:stats")
async def cb_stats(call: CallbackQuery, settings: Settings, db: Database) -> None:
    if not _is_admin(settings, call.from_user.id if call.from_user else None):
        await call.answer()
        return
    s = await db.stats()
    revenue = s.get("revenue_minor", 0) / 100
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"Пользователей: <b>{s['users']}</b>\n"
        f"Активных товаров: <b>{s['products']}</b>\n"
        f"Заказов всего: <b>{s['orders_total']}</b>\n"
        f"Выдано: <b>{s['orders_delivered']}</b>\n"
        f"Ожидают подтверждения: <b>{s['orders_pending']}</b>\n"
        f"Ключей в наличии: <b>{s['keys_available']}</b>\n"
        f"Ключей продано: <b>{s['keys_sold']}</b>\n"
        f"Выручка по выданным заказам: <b>{revenue:,.2f} ₽</b>".replace(",", " ").replace(
            ".", ","
        )
    )
    if call.message and isinstance(call.message, Message):
        await call.message.edit_text(text, reply_markup=back_to_admin())
    await call.answer()


# Plain admin shortcut: forwarded /pending
@router.message(Command("pending"))
async def cmd_pending(message: Message, settings: Settings, db: Database, bot: Bot) -> None:
    if not _is_admin(settings, message.from_user.id if message.from_user else None):
        return
    orders = await db.list_pending_orders(limit=20)
    if not orders:
        await message.answer("Заказов на проверке нет.")
        return
    from ..keyboards import admin_review

    for order in orders:
        product = await db.get_product(order.product_id)
        product_name = product.name if product else f"#{order.product_id}"
        caption = (
            f"⏳ <b>Заказ #{order.id}</b>\n"
            f"Товар: <b>{html.escape(product_name)}</b>\n"
            f"Покупатель id: <code>{order.user_id}</code>"
        )
        if order.proof_file_id:
            await bot.send_photo(
                message.chat.id,
                photo=order.proof_file_id,
                caption=caption,
                reply_markup=admin_review(order.id),
            )
        else:
            await message.answer(caption, reply_markup=admin_review(order.id))


# Convenience: typing "/orderXXX" gives the order details (admin only)
ORDER_REF_RE = re.compile(r"^/order(\d+)$")


@router.message(F.text.regexp(ORDER_REF_RE))
async def cmd_order_lookup(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(settings, message.from_user.id if message.from_user else None):
        return
    m = ORDER_REF_RE.match(message.text or "")
    if not m:
        return
    order_id = int(m.group(1))
    order = await db.get_order(order_id)
    if order is None:
        await message.answer("Не найден.")
        return
    product = await db.get_product(order.product_id)
    name = product.name if product else f"#{order.product_id}"
    text = (
        f"<b>Заказ #{order.id}</b>\n"
        f"Статус: {order.status}\n"
        f"Покупатель: <code>{order.user_id}</code>\n"
        f"Товар: {html.escape(name)}\n"
        f"Создан: {order.created_at}\n"
        f"Обновлён: {order.updated_at}"
    )
    if order.note:
        text += f"\nЗаметка: {html.escape(order.note)}"
    await message.answer(text)
