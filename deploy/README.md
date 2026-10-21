# Deploying to a server (Docker, no domain)

The app runs as one container, `bixi-app`, in its own compose project, `bixi`. Every command
below names that project (`-p bixi`) or that container, so nothing else on the server is
touched.

By default the container listens on `127.0.0.1:8501` only and serves the app under `/bixi/`, so
the server's existing reverse proxy (Caddy) can publish it at `http://<server-ip>/bixi/`, next
to the other apps. To expose the port directly instead, start it with
`BIXI_BIND=0.0.0.0 BIXI_BASE_PATH=` and open the port in the firewall.

What goes where:
- **Image**: the code, `reference/` (station lists) and `.streamlit/` (theme). Built on the server.
- **Mounted read-only**: `data/processed/hourly_station.parquet` (about 3 MB), copied from your
  Mac. Raw trip files are never needed on the server.

## 0. Look before changing anything (read-only)

```bash
docker --version
docker compose version
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
sudo ss -ltnp | grep -E ':(8501|8502|8503)\b' || echo "8501-8503 are free"
```

Pick a free port. The rest of this guide uses `8501`; replace it everywhere if it is taken.

## 1. Get the code on the server

```bash
git clone https://github.com/omarfaruqe/bixi-platform.git ~/bixi-platform
mkdir -p ~/bixi-platform/data/processed
```

If the repository is private, clone with a GitHub personal access token or deploy key.

## 2. Copy the data from your Mac (run this on the Mac, from the project folder)

```bash
scp data/processed/hourly_station.parquet USER@103.99.176.180:~/bixi-platform/data/processed/
```

## 3. Build and start (on the server)

```bash
cd ~/bixi-platform
docker compose -p bixi -f deploy/docker-compose.yml up -d --build
```

## 4. Check it

```bash
docker ps --filter name=bixi-app
curl -s http://localhost:8501/bixi/_stcore/health; echo
docker logs --tail 50 bixi-app
```

`ok` means the app is up (reachable from the server only, until step 5).

## 5. Publish it through the existing Caddy gateway

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

## Update after new commits

```bash
cd ~/bixi-platform
git pull
docker compose -p bixi -f deploy/docker-compose.yml up -d --build
```

After re-running the ingestion on the Mac, copy the new `hourly_station.parquet` again (step 2);
the app picks it up on the next page load, no rebuild needed.

## Stop or remove (only this app)

```bash
docker compose -p bixi -f deploy/docker-compose.yml down
```

## Do not run on a shared server

These affect every container, not just this one: `docker system prune`, `docker image prune -a`,
`docker volume prune`, `docker stop $(docker ps -q)`, and `docker compose down` without
`-p bixi -f deploy/docker-compose.yml`.

## Later

Plain HTTP on an IP address is fine for a portfolio demo. For HTTPS you need a domain name; then
put the app behind the server's existing reverse proxy (or Caddy) instead of publishing the port.
