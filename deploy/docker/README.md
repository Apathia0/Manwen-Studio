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
- `deploy/docker/RELEASE_AND_UPDATE.md`: Docker 发布、首次安装与用户侧更新操作说明。
- `deploy/docker/FAQ.md`: Docker 首次安装和更新常见故障处理。
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

Set `UPDATE_MANIFEST_URL` to the vendor-published update manifest. The admin
`Check for updates` button reads this manifest and does not require operators to
type a Docker tag. If the manifest endpoint is private, also set a read-only
`UPDATE_MANIFEST_TOKEN`.

For this repository, use:

```env
REGISTRY_IMAGE_PREFIX=ghcr.io/dream619/manwen-studio
APP_VERSION=v1.0.0
```

Do not use `ghcr.io/dream619/lorevista`; the GHCR path is derived from the
GitHub repository `dream619/Manwen-Studio` and is lowercased to
`dream619/manwen-studio`.

Token locations:

- Registry pull token: do not put it in `.env`; run `docker login` on the host.
  Docker stores it in `DOCKER_CONFIG_DIR`, usually `/root/.docker/config.json`,
  and the updater mounts that directory read-only.
- `UPDATER_TOKEN`: put it in `/opt/lorevista/.env`; backend and updater both
  receive it from Compose.
- `UPDATE_MANIFEST_TOKEN`: put it in `/opt/lorevista/.env` only if the update
  manifest endpoint is private.

Login with a read-only registry token:

```bash
echo "$READ_ONLY_REGISTRY_TOKEN" | docker login ghcr.io -u "$REGISTRY_USER" --password-stdin
```

Verify image access:

```bash
docker pull ghcr.io/dream619/manwen-studio/backend:v1.0.0
docker pull ghcr.io/dream619/manwen-studio/web:v1.0.0
docker pull ghcr.io/dream619/manwen-studio/updater:v1.0.0
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
2. Open the admin navigation item `System Update`.
3. Click `Check for updates`.
4. If a newer version is available, click `Update to latest`.

The backend verifies admin permission and forwards the request to the updater
sidecar. The updater reads `UPDATE_MANIFEST_URL` to find the latest stable tag,
updates `APP_VERSION` when that tag is selected, pulls images, runs migrations,
restarts backend first, checks `/api/health`, then updates the web container.
Logs are visible in the admin page with basic secret redaction.

Manual version input remains available only as an advanced fallback for rollback,
gray release, or support-directed updates.

For each official release, publish images first, verify them on a test server,
then update the manifest, for example:

```json
{
  "channel": "stable",
  "latest_version": "v1.2.3",
  "min_supported_version": "v1.0.0",
  "release_notes": "Bug fixes and migration improvements.",
  "published_at": "2026-06-05T12:00:00Z"
}
```

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
UPDATE_MANIFEST_URL=https://example.com/lorevista/update-manifest.json
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

### Web 与移动端 H5 共用域名

`web` 镜像同时包含桌面 Web 和 uni-app H5 构建产物：

- 桌面浏览器访问域名根路径时继续使用 Web 页面。
- 手机和平板访问域名根路径时，由容器 Nginx 自动跳转到 `/h5/`。
- `/api/` 和 `/static/` 始终转发到后端，不参与设备识别。
- 宿主机 Nginx 继续把整个域名代理到 `127.0.0.1:8080`，无需单独绑定 H5 域名。
- H5 和 Web 使用同一个 `web:<APP_VERSION>` 镜像，在线更新、健康检查和失败回滚会同时覆盖两个页面。

可使用不同 User-Agent 验证分流：

```bash
curl -I -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" https://your-domain.example/
curl -I -A "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile" https://your-domain.example/
curl -I -A "Mozilla/5.0 (iPhone) Mobile" https://your-domain.example/api/health
```

桌面请求应返回 Web 页面；移动端根路径请求应返回 `302` 和 `Location: /h5/`；移动端 API 请求仍应直接返回后端响应。

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
