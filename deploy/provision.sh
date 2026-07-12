#!/usr/bin/env bash
# One-time (idempotent, safe to re-run) provisioning for a fresh GCE VM
# running The Cairn. No Docker — a plain uv-managed checkout, matching how
# the app already runs locally.
#
# Usage (on the VM, as root):
#   curl -fsSL https://raw.githubusercontent.com/torstees/the-cairn/main/deploy/provision.sh -o provision.sh
#   sudo bash provision.sh
#
# Assumes the VM firewall/DNS/static-IP setup from TODO.md 10.3 is already
# in place. Does not touch the firewall or DNS itself.

set -euo pipefail

REPO_URL="https://github.com/torstees/the-cairn.git"
APP_DIR="/opt/cairn"
APP_USER="cairn"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash provision.sh" >&2
  exit 1
fi

# --- app user -------------------------------------------------------------
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "/home/$APP_USER" --shell /usr/sbin/nologin "$APP_USER"
fi

# --- uv, installed system-wide so the cairn user's systemd unit can find it
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin sh
fi

# --- git (not present on the base Debian GCE image) -------------------------
if ! command -v git >/dev/null 2>&1; then
  apt-get update
  apt-get install -y git
fi

# --- app checkout -----------------------------------------------------------
# Only clones if missing — a re-run must not disturb whatever released tag
# the deploy workflow (10.4) last checked out.
if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO_URL" "$APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && uv sync --locked"

# --- environment overrides ---------------------------------------------------
# Created once; never overwritten by re-runs so manual edits survive.
mkdir -p /etc/cairn
if [[ ! -f /etc/cairn/cairn.env ]]; then
  cat > /etc/cairn/cairn.env <<'EOF'
# Overrides for The Cairn's systemd service (deploy/cairn.service).
# Provisioning creates this once and never overwrites it afterward.
CAIRN_LOG_LEVEL=INFO
# DATABASE_URL=sqlite+aiosqlite:///./cairn.db   # default; uncomment to override
EOF
fi
chown root:root /etc/cairn/cairn.env
chmod 644 /etc/cairn/cairn.env

# --- database migrations -----------------------------------------------------
sudo -u "$APP_USER" bash -c "
  set -a
  . /etc/cairn/cairn.env
  set +a
  cd '$APP_DIR' && uv run alembic upgrade head
"

# --- systemd service ----------------------------------------------------------
install -m 644 "$APP_DIR/deploy/cairn.service" /etc/systemd/system/cairn.service
systemctl daemon-reload
systemctl enable --now cairn

# --- Caddy (automatic TLS reverse proxy) ---------------------------------------
if ! command -v caddy >/dev/null 2>&1; then
  apt-get update
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gnupg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
  apt-get install -y caddy
fi

install -m 644 "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
systemctl enable caddy
systemctl restart caddy

echo "Provisioning complete. cairn: $(systemctl is-active cairn), caddy: $(systemctl is-active caddy)"
