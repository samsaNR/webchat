from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..db import Database
from ..keyboards import (
    cancel_order,
    catalog,
    main_menu,
    product_card,
)
from ..states import BuyStates

router = Router(name="user")
log = logging.getLogger(__name__)


def _greet(settings: Settings, is_admin: bool) -> str:
    text = (
        f"<b>{html.escape(settings.shop_name)}</b>\n\n"
        "Здесь можно купить цифровые ключи. Оплата вручную: после выбора товара "
        "пришлите скриншот чека, продавец подтвердит — и бот сразу выдаст ключ.\n\n"
        "Выберите действие ниже."
    )
    if is_admin:
        text += "\n\n<i>Вы вошли как администратор.</i>"
    return text


@router.message(CommandStart())
async def cmd_start(message: Message, settings: Settings, db: Database, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    if user is None:
        return
    await db.upsert_user(user.id, user.username, user.full_name)
    await message.answer(
        _greet(settings, settings.is_admin(user.id)),
        reply_markup=main_menu(settings.is_admin(user.id)),
    )


@router.callback_query(F.data == "home")
async def cb_home(call: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    await state.clear()
    if call.from_user is None or call.message is None:
        await call.answer()
        return
    is_admin = settings.is_admin(call.from_user.id)
    if isinstance(call.message, Message):
        await call.message.edit_text(_greet(settings, is_admin), reply_markup=main_menu(is_admin))
    await call.answer()


@router.callback_query(F.data == "catalog")
async def cb_catalog(call: CallbackQuery, db: Database) -> None:
    products = await db.list_products(only_active=True)
    if call.message is None or not isinstance(call.message, Message):
        await call.answer()
        return
    if not products:
        await call.message.edit_text(
            "🛒 <b>Каталог пуст</b>\n\nТовары появятся скоро.",
            reply_markup=catalog([]),
        )
    else:
        await call.message.edit_text("🛒 <b>Каталог</b>\n\nВыберите товар:", reply_markup=catalog(products))
    await call.answer()


@router.callback_query(F.data.startswith("product:"))
async def cb_product(call: CallbackQuery, db: Database) -> None:
    if call.data is None or call.message is None or not isinstance(call.message, Message):
        await call.answer()
        return
    product_id = int(call.data.split(":", 1)[1])
    product = await db.get_product(product_id)
    if product is None or not product.is_active:
        await call.answer("Товар недоступен", show_alert=True)
        return
    available = await db.count_available_keys(product_id)
    text = (
        f"<b>{html.escape(product.name)}</b>\n\n"
        f"{html.escape(product.description) or '—'}\n\n"
        f"💰 Цена: <b>{product.price_display}</b>\n"
        f"📦 В наличии: <b>{available}</b> шт."
    )
    await call.message.edit_text(text, reply_markup=product_card(product, available))
    await call.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(
    call: CallbackQuery, db: Database, settings: Settings, state: FSMContext
) -> None:
    if call.data is None or call.from_user is None or call.message is None:
        await call.answer()
        return
    product_id = int(call.data.split(":", 1)[1])
    product = await db.get_product(product_id)
    if product is None or not product.is_active:
        await call.answer("Товар недоступен", show_alert=True)
        return
    if await db.count_available_keys(product_id) == 0:
        await call.answer("К сожалению, ключей в наличии нет", show_alert=True)
        return

    existing = await db.find_user_active_order(call.from_user.id)
    if existing is not None:
        await call.answer(
            f"У вас уже есть активный заказ #{existing.id}. Завершите или отмените его.",
            show_alert=True,
        )
        return

    order_id = await db.create_order(call.from_user.id, product_id)
    await state.set_state(BuyStates.waiting_for_proof)
    await state.update_data(order_id=order_id, product_id=product_id)

    text = (
        f"📝 <b>Заказ #{order_id}</b>\n"
        f"Товар: <b>{html.escape(product.name)}</b>\n"
        f"Сумма к оплате: <b>{product.price_display}</b>\n\n"
        "💳 <b>Реквизиты для оплаты:</b>\n"
        f"<pre>{html.escape(settings.payment_instructions)}</pre>\n\n"
        "После оплаты пришлите сюда <b>скриншот чека</b> одним фото. "
        "Как только продавец подтвердит оплату — бот мгновенно выдаст ключ.\n"
    )
    if settings.support_contact:
        text += f"\nЕсли возникли вопросы — {html.escape(settings.support_contact)}"

    if isinstance(call.message, Message):
        await call.message.edit_text(text, reply_markup=cancel_order(order_id))
    await call.answer()


@router.callback_query(F.data.startswith("cancel_order:"))
async def cb_cancel_order(
    call: CallbackQuery, db: Database, state: FSMContext, settings: Settings
) -> None:
    if call.data is None or call.from_user is None or call.message is None:
        await call.answer()
        return
    order_id = int(call.data.split(":", 1)[1])
    order = await db.get_order(order_id)
    if order is None or order.user_id != call.from_user.id:
        await call.answer("Заказ не найден", show_alert=True)
        return
    if order.status not in ("awaiting_proof", "rejected"):
        await call.answer("Этот заказ уже нельзя отменить", show_alert=True)
        return
    await db.reject_order(order_id, note="canceled_by_user")
    await state.clear()
    if isinstance(call.message, Message):
        await call.message.edit_text(
            f"❌ Заказ #{order_id} отменён.",
            reply_markup=main_menu(settings.is_admin(call.from_user.id)),
        )
    await call.answer()


@router.message(BuyStates.waiting_for_proof, F.photo)
async def on_proof_photo(
    message: Message,
    bot: Bot,
    db: Database,
    settings: Settings,
    state: FSMContext,
) -> None:
    if message.from_user is None or not message.photo:
        return
    data = await state.get_data()
    order_id = data.get("order_id")
    if not isinstance(order_id, int):
        await message.answer("Не нашёл активный заказ. Начните заново через /start.")
        await state.clear()
        return

    order = await db.get_order(order_id)
    if order is None or order.user_id != message.from_user.id:
        await message.answer("Заказ не найден.")
        await state.clear()
        return

    file_id = message.photo[-1].file_id
    await db.attach_proof(order_id, file_id)
    await state.clear()

    product = await db.get_product(order.product_id)
    product_name = product.name if product else f"#{order.product_id}"

    await message.answer(
        f"✅ Скриншот получен. Заказ #{order_id} отправлен на проверку продавцу.\n"
        "Как только оплата будет подтверждена — пришлю ключ сюда.",
        reply_markup=main_menu(settings.is_admin(message.from_user.id)),
    )

    user = message.from_user
    user_link = f"@{user.username}" if user.username else f"id:{user.id}"
    caption = (
        f"🆕 <b>Новый чек на проверку</b>\n"
        f"Заказ: <b>#{order_id}</b>\n"
        f"Товар: <b>{html.escape(product_name)}</b>"
        + (f" — <b>{product.price_display}</b>" if product else "")
        + f"\nПокупатель: {html.escape(user_link)} ({html.escape(user.full_name)})"
    )

    from ..keyboards import admin_review

    for admin_id in settings.admin_ids:
        try:
            await bot.send_photo(
                admin_id,
                photo=file_id,
                caption=caption,
                reply_markup=admin_review(order_id),
            )
        except Exception:
            log.exception("Failed to notify admin %s about order %s", admin_id, order_id)


@router.message(BuyStates.waiting_for_proof)
async def on_proof_wrong(message: Message) -> None:
    await message.answer(
        "Жду <b>фото</b> чека одним сообщением. Если передумали — нажмите «Отменить заказ» выше."
    )


@router.callback_query(F.data == "my_orders")
async def cb_my_orders(call: CallbackQuery, db: Database) -> None:
    if call.from_user is None or call.message is None or not isinstance(call.message, Message):
        await call.answer()
        return
    orders = await db.list_user_orders(call.from_user.id, limit=10)
    if not orders:
        await call.message.edit_text(
            "У вас пока нет заказов.", reply_markup=main_menu(False)
        )
        await call.answer()
        return
    lines: list[str] = ["<b>Ваши последние заказы:</b>", ""]
    for o in orders:
        product = await db.get_product(o.product_id)
        name = product.name if product else f"товар #{o.product_id}"
        status_human = {
            "awaiting_proof": "ожидает чек",
            "proof_sent": "на проверке",
            "approved": "подтверждён",
            "rejected": "отклонён",
            "delivered": "выдан",
            "failed": "ошибка",
        }.get(o.status, o.status)
        lines.append(f"#{o.id} — {html.escape(name)} — <i>{status_human}</i>")
        if o.status == "delivered":
            value = await db.get_order_key_value(o.id)
            if value:
                lines.append(f"   🔑 <code>{html.escape(value)}</code>")
    lines.append("")
    await call.message.edit_text("\n".join(lines), reply_markup=main_menu(False))
    await call.answer()


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings) -> None:
    await message.answer(
        "Используйте /start для меню. Если что-то пошло не так — напишите "
        + (settings.support_contact or "поддержке.")
    )
