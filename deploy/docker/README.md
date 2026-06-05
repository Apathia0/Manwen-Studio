# LoreVista Docker Deployment

This deployment path keeps source code off the production server. CI builds
private images. Production servers run Docker Compose and let an administrator
trigger updates from inside the web admin panel. The host-level script remains a
fallback for emergency manual operations.

## Files

- `Dockerfile.backend`: FastAPI backend image.
- `Dockerfile.web`: built React app served by Nginx.
- `Dockerfile.updater`: internal updater service that owns Docker/Compose access.
- `docker-compose.yml`: app, web, PostgreSQL, Redis, and persistent volumes.
- `deploy/docker/update-lorevista.sh`: host-level manual updater with locking,
  migrations, health checks, and rollback.
- `deploy/docker/systemd/*`: optional service/timer for unattended update checks.

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

Set a long random `UPDATER_TOKEN` in `/opt/lorevista/.env`. Compose passes the
same token to both `backend` and `updater`. The backend uses it only to call the
internal updater API after admin authentication.

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

The `updater` service is not published to the public network. It is reachable
only from the Docker internal network, while it mounts `/var/run/docker.sock` and
the deployment directory so it can run Compose updates. Do not mount the Docker
socket into the business `backend` service.

## In-System Manual Updates

User-side updates are manual by default and are triggered from the application:

1. Login as an administrator.
2. Open the admin navigation item `系统更新`.
3. Leave the version empty to use `/opt/lorevista/.env` `APP_VERSION`, or enter
   a Docker tag such as `v1.2.3` or `sha-abcdef123456`.
4. Confirm the update.

The backend verifies admin permission and forwards the request to the updater
sidecar. The updater then updates `APP_VERSION` when a target tag is supplied,
pulls images, runs migrations, restarts backend first, checks `/api/health`, then
updates the web container. Logs are visible in the admin page with basic secret
redaction.

## CLI Fallback

If the admin UI is unavailable, run the same updater script from the host:

```bash
sudo APP_DIR=/opt/lorevista /usr/bin/env bash /opt/lorevista/deploy/docker/update-lorevista.sh
```

The script checks whether the configured images changed, runs migrations, starts
the backend first, waits for `/api/health`, then starts the web container. If a
health check fails, it attempts to restore the previous images.

For controlled releases, set a fixed version in `/opt/lorevista/.env`:

```env
APP_VERSION=v1.0.0
```

Then trigger the update in the admin panel or run the fallback script. Avoid
`APP_VERSION=stable` if you do not want a new CI build to be picked up when the
operator triggers an update.

## Optional Unattended Updates

Unattended checks are not enabled by default. Only install the timer if the
deployment explicitly wants periodic update checks:

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

## Update Behavior

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
