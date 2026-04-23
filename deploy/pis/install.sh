#!/bin/bash
# Install PIS systemd timers and start docker compose
# Usage: sudo ./install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIS_DIR="/opt/pis"

TIMERS=(
    pis-sync
    pis-extract
    pis-graph
    pis-rss
    pis-seo
    pis-discover
    pis-gc
    pis-backup
    pis-report
)

echo "=== PIS Scheduler Installation ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo ./install.sh"
    exit 1
fi

# Copy systemd files
echo "Installing systemd units..."
for name in "${TIMERS[@]}"; do
    cp "$SCRIPT_DIR/systemd/${name}.service" /etc/systemd/system/
    cp "$SCRIPT_DIR/systemd/${name}.timer" /etc/systemd/system/
    echo "  Installed ${name}.{service,timer}"
done

# Reload systemd
echo ""
echo "Reloading systemd..."
systemctl daemon-reload

# Enable and start all timers
echo ""
echo "Enabling and starting timers..."
for name in "${TIMERS[@]}"; do
    systemctl enable "${name}.timer"
    systemctl start "${name}.timer"
    echo "  Started ${name}.timer"
done

# Start docker compose
echo ""
echo "Starting docker compose..."
cd "$PIS_DIR"
docker compose up -d

# Show status
echo ""
echo "=== Installation Complete ==="
echo ""
echo "Timer status:"
systemctl list-timers 'pis-*' --no-pager
echo ""
echo "Docker status:"
docker compose ps
echo ""
echo "To run a job manually:"
echo "  systemctl start pis-sync.service"
echo ""
echo "To view logs:"
echo "  journalctl -u pis-sync.service -f"
