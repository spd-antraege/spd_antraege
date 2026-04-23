# Deployment

Production runs on `pis-vm` (Hetzner VPS).

## Stack

- **Server**: uvicorn serving FastAPI (API + static frontend + MCP)
- **Search**: Elasticsearch (Docker) on same host
- **Secrets**: Doppler (`andx_main/prd`)
- **Systemd**: `spd-antraege-app.service`

## Deploy

```bash
# Push code
git push origin main

# Pull and restart on server
ssh pis-vm "cd /opt/pis && git pull origin main && systemctl restart spd-antraege-app.service"

# If frontend changed — build locally and sync
cd frontend && npx astro build
rsync -avz dist/ pis-vm:/opt/pis/frontend/dist/
ssh pis-vm "systemctl restart spd-antraege-app.service"
```

## Service management

```bash
ssh pis-vm "systemctl status spd-antraege-app"     # check status
ssh pis-vm "journalctl -u spd-antraege-app -f"     # tail logs
ssh pis-vm "systemctl restart spd-antraege-app"     # restart
```

## Infrastructure

| Component | Location | Config |
|-----------|----------|--------|
| App | `/opt/pis` | `spd-antraege-app.service` |
| Elasticsearch | Docker | `docker-compose.dev.yaml` |
| Reverse proxy | Caddy | `/etc/caddy/Caddyfile` |
| Secrets | Doppler | `andx_main/prd` |
