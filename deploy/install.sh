#!/usr/bin/env bash
# One-shot installer for the bot on a fresh Ubuntu/Debian VPS.
# Run as root (or with sudo): bash deploy/install.sh
set -euo pipefail

APP_DIR="/opt/tg-shop-bot"
SERVICE_USER="tgbot"
REPO_URL="${REPO_URL:-}"  # optional: git URL to clone if APP_DIR is empty

echo "==> Installing system packages"
apt-get update
apt-get install -y python3 python3-venv python3-pip git

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    echo "==> Creating service user $SERVICE_USER"
    useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$APP_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

if [[ -n "$REPO_URL" && ! -d "$APP_DIR/.git" ]]; then
    echo "==> Cloning $REPO_URL into $APP_DIR"
    sudo -u "$SERVICE_USER" git clone "$REPO_URL" "$APP_DIR"
fi

echo "==> Creating virtualenv"
sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install -e "$APP_DIR"

mkdir -p "$APP_DIR/data" "$APP_DIR/data/proofs"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/data"

if [[ ! -f "$APP_DIR/.env" ]]; then
    echo "==> .env not found — copy .env.example and fill in BOT_TOKEN/ADMIN_IDS"
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
fi

echo "==> Installing systemd unit"
install -m 644 "$APP_DIR/deploy/tg-shop-bot.service" /etc/systemd/system/tg-shop-bot.service
systemctl daemon-reload
systemctl enable tg-shop-bot.service

echo
echo "Done. Edit $APP_DIR/.env then run:"
echo "  systemctl start tg-shop-bot"
echo "  systemctl status tg-shop-bot"
echo "  journalctl -u tg-shop-bot -f"
