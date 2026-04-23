# Gotchas

## Deployment

Production server (`pis-vm`) pulls from GitHub via HTTPS (public repo, no credentials needed). Push to `origin main`, then pull and restart on the server:
```bash
git push origin main
ssh pis-vm "cd /opt/pis && git pull origin main && cd frontend && npx astro build && systemctl restart spd-antraege-app.service"
```

## Frontend build

The Astro frontend must be built on a machine with Node.js. The `frontend/dist/` directory is served as static files by the FastAPI backend. If the Vite `@/` alias doesn't resolve on the server, build locally and rsync:
```bash
cd frontend && npx astro build
rsync -avz dist/ pis-vm:/opt/pis/frontend/dist/
```
