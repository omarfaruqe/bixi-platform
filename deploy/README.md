# Deploying to a server (Docker, no domain)

The platform runs as one Docker Compose project, `bixi`, with three containers:

| Container | What it does | Listens on |
|---|---|---|
| `bixi-db` | PostgreSQL 16, the forecast store (volume `bixi_pgdata`) | nothing published |
| `bixi-api` | FastAPI, read-only forecast service | `127.0.0.1:8502` |
| `bixi-app` | Streamlit dashboard, served under `/bixi/` | `127.0.0.1:8501` |

Every command below names the project (`-p bixi -f deploy/docker-compose.yml`) or a `bixi-*`
container, so nothing else on the server is touched. Nothing listens publicly: the server's
existing reverse proxy (Caddy) publishes the dashboard at `http://<server-ip>/bixi/`.

What goes where:
- **Image** (built on the server): the code, `reference/` (station lists) and `.streamlit/`
  (theme). It contains neither LightGBM nor OR-Tools.
- **Mounted read-only** at `/data/processed`: about 5 MB of results copied from your Mac
  (`deploy/sync_data.sh`, step 2). Raw trips and model files never leave the Mac.
- **Database**: filled from a forecast run file (step 6). It can always be rebuilt from that file,
  so it needs no backup.

## 0. Look before changing anything (read-only)

```bash
docker --version
docker compose version
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
sudo ss -ltnp | grep -E ':(8501|8502)\b' || echo "8501 and 8502 are free"
```

If a port is taken, set `BIXI_PORT` or `BIXI_API_PORT` in `deploy/.env` (step 3).

## 1. Get the code on the server

```bash
git clone https://github.com/omarfaruqe/bixi-platform.git ~/bixi-platform
```

Clone over HTTPS: an SSH URL needs a key registered with GitHub, even for a public repository.

## 2. Copy the results from your Mac

On the Mac, from the project folder, after the pipeline has run:

```bash
deploy/sync_data.sh USER@103.99.176.180
```

It copies the hourly table, the model results, the forecast run and the rebalancing results to
`~/bixi-platform/data/processed/` in one ssh session, and makes them world-readable (the
containers run as an unprivileged user). Files not built yet are skipped and listed. Run it again
whenever the results change; the dashboard picks them up on the next page load, no rebuild needed.

## 3. Build and start (on the server)

Optional, before the first start only: choose a database password.

```bash
cd ~/bixi-platform
echo "BIXI_DB_PASSWORD=$(openssl rand -hex 24)" > deploy/.env
```

Then:

```bash
docker compose -p bixi -f deploy/docker-compose.yml up -d --build
```

## 4. Check it

```bash
docker ps --filter name=bixi-
curl -s http://localhost:8502/health; echo
curl -s http://localhost:8501/bixi/_stcore/health; echo
```

The API answers `{"status":"ok","active_run":null}` until step 6; the dashboard answers `ok`.

## 5. Publish the dashboard through the existing Caddy gateway

Add this block inside the server's site block in the Caddyfile, beside the other apps' routes:

```
redir /bixi /bixi/ permanent

handle /bixi/* {
    reverse_proxy 127.0.0.1:8501
}
```

Back up the Caddyfile first. If it is bind-mounted as a single file, overwrite it in place
(`cat > Caddyfile`); editors that save a new file break the mount and Caddy keeps the old one.

Use `handle`, not `handle_path`: Streamlit expects to see the `/bixi` prefix. Caddy proxies
Streamlit's websocket automatically. Validate and reload (a graceful reload; other routes keep
serving):

```bash
docker exec gateway-caddy-1 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker exec gateway-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Then open `http://103.99.176.180/bixi/` (French: `http://103.99.176.180/bixi/?lang=fr`).
This works because the gateway container uses the host network (`network: host`), so
`127.0.0.1` inside it is the server. Deployed this way on 2026-10-21 next to MapleMetrics and
HansardLens.

## 6. Load the forecasts into the database

The run file arrived with step 2. On the server:

```bash
cd ~/bixi-platform
docker compose -p bixi -f deploy/docker-compose.yml exec api \
  python -m bixi.forecast publish /data/processed/forecasts/holdout-2025.parquet
docker compose -p bixi -f deploy/docker-compose.yml exec api python -m bixi.forecast runs
```

`runs` marks the active run with `*`, and `curl -s http://localhost:8502/health` now names it.
Publishing the same run again replaces it. To switch back to an earlier run:
`... exec api python -m bixi.forecast activate <run_id>`.

The API's interactive documentation is at `http://localhost:8502/docs` on the server. To publish
it at `http://<server-ip>/bixi-api/docs`, set `BIXI_API_ROOT_PATH=/bixi-api` in `deploy/.env`,
run `up -d` again, and add to the Caddyfile (here the prefix *is* stripped, because the API
serves from `/`):

```
redir /bixi-api /bixi-api/ permanent

handle_path /bixi-api/* {
    reverse_proxy 127.0.0.1:8502
}
```

## Update after new commits

On the Mac: `git push`. On the server:

```bash
cd ~/bixi-platform
git pull
docker compose -p bixi -f deploy/docker-compose.yml up -d --build
```

Only containers whose image or settings changed are recreated; the database volume is kept, so
the published forecasts survive updates.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Page shows `PermissionError: Permission denied (os error 13)` | Files copied without read permission. `chmod -R a+rX ~/bixi-platform/data/processed` (the sync script does this). |
| Page says a data file was not found | That result was not copied yet: run `deploy/sync_data.sh` on the Mac. |
| Overview badge says "Forecast service offline" | The API is not reachable: `docker ps --filter name=bixi-api`, then `docker logs --tail 50 bixi-api`. |
| Badge says "no forecasts published yet" | The API is up but the database is empty: run step 6. |
| `publish` fails with `ForeignKeyViolation` | Fixed in commit 49c0202 (republishing a run). `git pull` and rebuild, then publish again. |
| `git clone git@github.com:...` fails with `Permission denied (publickey)` | Use the HTTPS URL (step 1). |
| A container keeps restarting | `docker logs --tail 100 bixi-app` (or `bixi-api`, `bixi-db`). |

## Stop or remove (only this app)

`down` keeps the database volume; add `-v` only if you also want to delete the forecasts (they can
be published again from the run file).

```bash
docker compose -p bixi -f deploy/docker-compose.yml down
```

## Do not run on a shared server

These affect every container, not just this one: `docker system prune`, `docker image prune -a`,
`docker volume prune`, `docker stop $(docker ps -q)`, and `docker compose down` without
`-p bixi -f deploy/docker-compose.yml`.

## Later

Plain HTTP on an IP address is fine for a portfolio demo. With a domain name, Caddy obtains a
certificate automatically: replace the site address in the Caddyfile with the domain, and the
same `/bixi/` routes serve over HTTPS.
