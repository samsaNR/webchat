# tg-shop-bot

Telegram-бот для продажи цифровых ключей с **ручным подтверждением оплаты**.

Покупатель выбирает товар → бот показывает реквизиты → покупатель присылает скрин чека →
бот пересылает скрин админу с кнопками «Подтвердить» / «Отклонить» → при подтверждении
бот атомарно достаёт первый свободный ключ из пула и отправляет его покупателю.

## Стек

- Python 3.11+
- [aiogram 3](https://docs.aiogram.dev/) — long polling
- SQLite (через `aiosqlite`) — БД-файл рядом с ботом
- systemd — для запуска на VPS

## Установка локально (для разработки)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# отредактируй .env: BOT_TOKEN, ADMIN_IDS, PAYMENT_INSTRUCTIONS
python -m tg_shop_bot
```

## Конфигурация (.env)

| Переменная             | Что это                                                                    |
|------------------------|----------------------------------------------------------------------------|
| `BOT_TOKEN`            | Токен бота от [@BotFather](https://t.me/BotFather)                          |
| `ADMIN_IDS`            | Через запятую — Telegram user id админов (узнать у [@userinfobot](https://t.me/userinfobot)) |
| `DB_PATH`              | Путь к SQLite-файлу. Default: `data/shop.sqlite3`                           |
| `PROOFS_DIR`           | Папка для файлов скринов (на будущее). Default: `data/proofs`               |
| `SHOP_NAME`            | Название магазина в `/start`                                                |
| `PAYMENT_INSTRUCTIONS` | Текст с реквизитами оплаты (используй `\n` для переноса строки)             |
| `SUPPORT_CONTACT`      | Юзернейм поддержки, например `@your_username`                               |

## Команды бота

**Покупатель:**
- `/start` — главное меню
- `/help` — помощь

**Админ (только telegram-id из `ADMIN_IDS`):**
- `/admin` — открыть админ-панель (товары, ключи, заказы, статистика)
- `/pending` — показать все заказы, ожидающие подтверждения
- `/orderNNN` — посмотреть детали заказа NNN

В админ-панели можно:
- добавить товар (название, описание, цена в рублях),
- загрузить ключи под товар (текстом по одному в строке или `.txt` файлом),
- включать/выключать товары,
- видеть остатки ключей,
- подтверждать или отклонять чеки покупателей,
- смотреть статистику (продажи, выручка, остатки).

## Деплой на VPS (Ubuntu/Debian)

Готовый скрипт-установщик:

```bash
# на VPS, под root
git clone <ваш-репозиторий> /opt/tg-shop-bot
cd /opt/tg-shop-bot
bash deploy/install.sh

# заполни .env
nano /opt/tg-shop-bot/.env

systemctl start tg-shop-bot
systemctl status tg-shop-bot
journalctl -u tg-shop-bot -f   # логи в реальном времени
```

Что делает `install.sh`:
- ставит `python3-venv`, `git`,
- создаёт системного пользователя `tgbot`,
- создаёт venv в `/opt/tg-shop-bot/.venv`,
- ставит зависимости проекта,
- копирует systemd-юнит и регистрирует его на автозапуск.

Юнит-файл — `deploy/tg-shop-bot.service`. БД и скрины пишутся в `/opt/tg-shop-bot/data/`.

## Безопасность

- Не комментируй `BOT_TOKEN` в репозиторий — он в `.env`, который игнорируется git'ом.
- Файл `.env` имеет права `600` и принадлежит пользователю `tgbot`.
- Systemd-юнит запускает бота под непривилегированным пользователем с `ProtectSystem=strict`,
  `ProtectHome=true`, `NoNewPrivileges=true`.

## Линт / тесты

```bash
ruff check .
pytest
```
