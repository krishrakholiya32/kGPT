#!/bin/bash
# kGPT — EC2 Ubuntu 22.04 setup script
# Run as: bash setup.sh
# Replace YOUR_GITHUB_USERNAME before running.

set -e

REPO="https://github.com/krishrakholiya32/kGPT.git"
APP_DIR="/home/ubuntu/kgpt"
PYTHON="python3"

echo "=== [1/6] System packages ==="
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git

echo "=== [2/6] Clone repo ==="
if [ -d "$APP_DIR" ]; then
  echo "Directory exists — pulling latest..."
  cd "$APP_DIR" && git pull
else
  git clone "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"

echo "=== [3/6] Python virtual environment ==="
$PYTHON -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== [4/6] Environment file ==="
if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo ">>> .env created from .env.example"
  echo ">>> EDIT IT NOW: nano $APP_DIR/.env"
  echo ">>> Set: GROQ_API_KEY, JWT_SECRET_KEY, RESEND_API_KEY, APP_BASE_URL"
  echo ""
fi

echo "=== [5/6] Systemd service ==="
sudo cp "$APP_DIR/deploy/kgpt.service" /etc/systemd/system/kgpt.service
sudo systemctl daemon-reload
sudo systemctl enable kgpt
sudo systemctl restart kgpt
sudo systemctl status kgpt --no-pager

echo "=== [6/6] Nginx ==="
sudo cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/kgpt
sudo ln -sf /etc/nginx/sites-available/kgpt /etc/nginx/sites-enabled/kgpt
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

echo ""
echo "=== Done! ==="
echo "App running at: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)"
echo ""
echo "Next steps:"
echo "  1. Edit .env:         nano $APP_DIR/.env"
echo "  2. Restart app:       sudo systemctl restart kgpt"
echo "  3. View logs:         sudo journalctl -u kgpt -f"
echo "  4. Add SSL (optional): sudo certbot --nginx -d yourdomain.com"
