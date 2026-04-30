from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    db_path: Path
    proofs_dir: Path
    shop_name: str
    payment_instructions: str
    support_contact: str

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


def _parse_admin_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError as exc:
            raise ValueError(f"ADMIN_IDS contains non-integer value: {part!r}") from exc
    if not ids:
        raise ValueError("ADMIN_IDS must contain at least one Telegram user id")
    return frozenset(ids)


def load_settings(env_file: str | os.PathLike[str] | None = None) -> Settings:
    if env_file is not None:
        load_dotenv(env_file)
    else:
        load_dotenv()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Put it in .env or environment.")

    admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

    db_path = Path(os.getenv("DB_PATH", "data/shop.sqlite3")).expanduser()
    proofs_dir = Path(os.getenv("PROOFS_DIR", "data/proofs")).expanduser()

    shop_name = os.getenv("SHOP_NAME", "Цифровой магазин")
    payment_instructions = os.getenv(
        "PAYMENT_INSTRUCTIONS",
        "Реквизиты оплаты не настроены. Свяжитесь с поддержкой.",
    ).replace("\\n", "\n")
    support_contact = os.getenv("SUPPORT_CONTACT", "")

    return Settings(
        bot_token=token,
        admin_ids=admin_ids,
        db_path=db_path,
        proofs_dir=proofs_dir,
        shop_name=shop_name,
        payment_instructions=payment_instructions,
        support_contact=support_contact,
    )
