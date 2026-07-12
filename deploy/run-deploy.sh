#!/usr/bin/env bash
# Deploys a specific released tag on the VM. Invoked by
# .github/workflows/deploy.yml over an IAP-tunneled SSH session (as root,
# via OS Login sudo). Also usable manually for a rollback: SSH in and
# re-run with an older tag — every step here is safe to repeat, including
# alembic upgrade (a no-op if that tag's migrations are already applied).
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: sudo $0 <git-tag>" >&2
  exit 1
fi

TAG="$1"
APP_DIR="/opt/cairn"
APP_USER="cairn"

cd "$APP_DIR"
sudo -u "$APP_USER" git fetch --tags
sudo -u "$APP_USER" git checkout "$TAG"
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && uv sync --locked"
sudo -u "$APP_USER" bash -c "
  set -a
  . /etc/cairn/cairn.env
  set +a
  cd '$APP_DIR' && uv run alembic upgrade head
"

systemctl restart cairn
sleep 2

if ! curl -fsS http://localhost:8000/ > /dev/null; then
  echo "Health check failed after deploying $TAG" >&2
  exit 1
fi

echo "Deployed $TAG successfully."
