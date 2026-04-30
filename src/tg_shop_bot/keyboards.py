from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .db import Product


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Каталог", callback_data="catalog")
    kb.button(text="📦 Мои покупки", callback_data="my_orders")
    if is_admin:
        kb.button(text="🛠 Админ-панель", callback_data="admin")
    kb.adjust(1)
    return kb.as_markup()


def catalog(products: list[Product]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(text=f"{p.name} — {p.price_display}", callback_data=f"product:{p.id}")
    kb.button(text="« Назад", callback_data="home")
    kb.adjust(1)
    return kb.as_markup()


def product_card(product: Product, available: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if available > 0:
        kb.button(text=f"💳 Купить за {product.price_display}", callback_data=f"buy:{product.id}")
    kb.button(text="« К каталогу", callback_data="catalog")
    kb.adjust(1)
    return kb.as_markup()


def cancel_order(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отменить заказ", callback_data=f"cancel_order:{order_id}")
    return kb.as_markup()


def admin_review(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data=f"approve:{order_id}")
    kb.button(text="❌ Отклонить", callback_data=f"reject:{order_id}")
    kb.adjust(2)
    return kb.as_markup()


def admin_panel() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить товар", callback_data="adm:add_product")
    kb.button(text="🔑 Загрузить ключи", callback_data="adm:add_keys")
    kb.button(text="📋 Список товаров", callback_data="adm:list_products")
    kb.button(text="⏳ Ожидают подтверждения", callback_data="adm:pending")
    kb.button(text="📊 Статистика", callback_data="adm:stats")
    kb.button(text="« В меню", callback_data="home")
    kb.adjust(1)
    return kb.as_markup()


def admin_products(products: list[Product]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in products:
        flag = "✅" if p.is_active else "🚫"
        kb.button(text=f"{flag} {p.name}", callback_data=f"adm:prod:{p.id}")
    kb.button(text="« Назад", callback_data="admin")
    kb.adjust(1)
    return kb.as_markup()


def admin_product_card(product: Product) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    toggle = "🚫 Выключить" if product.is_active else "✅ Включить"
    kb.button(text=toggle, callback_data=f"adm:toggle:{product.id}")
    kb.button(text="🔑 Загрузить ключи", callback_data=f"adm:keys:{product.id}")
    kb.button(text="🗑 Удалить", callback_data=f"adm:del:{product.id}")
    kb.button(text="« К списку", callback_data="adm:list_products")
    kb.adjust(1)
    return kb.as_markup()


def admin_pick_product_for_keys(products: list[Product]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(text=p.name, callback_data=f"adm:keys:{p.id}")
    kb.button(text="« Назад", callback_data="admin")
    kb.adjust(1)
    return kb.as_markup()


def back_to_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« В админ-панель", callback_data="admin")]]
    )
