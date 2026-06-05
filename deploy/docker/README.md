# LoreVista Docker Deployment

This deployment path keeps source code off the production server. CI builds
private images, the server pulls images, and a host-level systemd timer checks
for updates.

## Files

- `Dockerfile.backend`: FastAPI backend image.
- `Dockerfile.web`: built React app served by Nginx.
- `docker-compose.yml`: app, web, PostgreSQL, Redis, and persistent volumes.
- `deploy/docker/update-lorevista.sh`: host-level auto updater with locking,
  migrations, health checks, and rollback.
- `deploy/docker/systemd/*`: timer and service for automatic update checks.

## Server Setup

Create a runtime directory:

```bash
sudo mkdir -p /opt/lorevista/deploy/docker/runtime /opt/lorevista/data
sudo cp docker-compose.yml /opt/lorevista/
sudo cp -r deploy/docker /opt/lorevista/deploy/
sudo cp deploy/docker/.env.example /opt/lorevista/.env
sudo cp deploy/docker/runtime/backend.env.example /opt/lorevista/deploy/docker/runtime/backend.env
```

Edit `/opt/lorevista/.env` and `/opt/lorevista/deploy/docker/runtime/backend.env`.
Do not commit real secrets.

Login with a read-only registry token:

```bash
echo "$READ_ONLY_REGISTRY_TOKEN" | docker login ghcr.io -u "$REGISTRY_USER" --password-stdin
```

If the server cannot reach Docker Hub, configure a Docker registry mirror or
pre-pull the base images used by CI/build hosts. Do not replace the production
deployment flow with source-code pulls just to work around a registry network
issue.

Start:

```bash
cd /opt/lorevista
docker compose --env-file .env up -d
```

Install the updater:

```bash
sudo cp /opt/lorevista/deploy/docker/systemd/lorevista-update.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lorevista-update.timer
```

## Nginx TLS

Keep public TLS on the host Nginx and proxy to the web container:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

PostgreSQL and Redis are not published to the public network by default.

## Auto Update Behavior

The updater:

1. Uses `flock` so only one update runs.
2. Pulls `backend` and `web` images.
3. Exits if image IDs are unchanged.
4. Runs backend migrations in a one-shot container.
5. Starts backend and waits for `/api/health`.
6. Starts web and checks `/api/health` again.
7. Rolls back compose state if migration or health checks fail.

Logs are written to `/var/log/lorevista-update.log`.

## Data Safety

Generated files must stay outside container layers:

- `/opt/lorevista/data/manga_outputs`
- `/opt/lorevista/data/video_outputs`
- Docker volumes `lorevista_postgres_data` and `lorevista_redis_data`

Do not run `docker compose down -v` in production unless you intend to delete
database and Redis data.
