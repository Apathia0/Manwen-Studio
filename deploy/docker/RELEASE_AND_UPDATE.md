# LoreVista Docker 发布、首次安装与更新说明

本文档说明 Docker 发行模式下的三个流程：

- 我们发布新版本：构建并推送私有 Docker 镜像。
- 用户首次安装：用户服务器运行 Docker Compose，并通过浏览器安装向导初始化数据库、Redis 和管理员。
- 用户后续更新：管理员在系统后台手动触发更新。

核心原则：生产服务器不保存源码、Git 凭据、CI token 或构建缓存。生产服务器只运行 Docker Compose、私有镜像、运行时配置和内部 updater 服务。

## 私有仓库定义

本文档中的“私有仓库”指私有 Docker 镜像仓库，也就是 Docker Registry，不是 Git 源码仓库。

默认推荐使用 GHCR：

```text
Registry: ghcr.io
Image prefix: ghcr.io/<github-owner>/<github-repo>
```

如果 GitHub 仓库是 `your-org/lorevista`，镜像名称为：

```text
ghcr.io/your-org/lorevista/backend:v1.2.3
ghcr.io/your-org/lorevista/web:v1.2.3
ghcr.io/your-org/lorevista/updater:v1.2.3
```

服务器 `.env` 示例：

```env
REGISTRY_IMAGE_PREFIX=ghcr.io/your-org/lorevista
APP_VERSION=v1.2.3
```

权限边界：

- CI 需要 push 权限，用于构建并推送镜像。
- 用户服务器只需要只读 pull token。
- 用户服务器不需要 GitHub/GitLab 源码仓库访问权限。
- 不向用户提供 CI token、源码仓库 token 或可写 registry token。

GHCR 场景下，GitHub Actions 可以使用 `GITHUB_TOKEN` 推送 packages。用户服务器建议使用独立机器账号或细粒度 token，只授予当前镜像包的读取权限。镜像包必须设置为 private。

当前仓库已配置：推送 `v*` Git tag 后会自动构建并推送镜像到 GHCR。正式发布不需要人工执行 `docker build` 或 `docker push`。

## 一、我们发布版本的流程

### 1. 发布前准备

发布前确认：

- 已配置私有 Docker 镜像仓库，例如 GHCR、GitLab Registry、阿里云 ACR 或 Harbor。
- CI 具备镜像推送权限。
- 用户服务器使用只读 registry pull token。
- 版本号固定，例如 `v1.2.3`。
- 数据库迁移默认保持向后兼容。
- 破坏性迁移必须走人工维护窗口。
- 用户生成资源不进入镜像，继续使用持久化挂载保存。

### 2. 触发发布

正式发布使用 Git tag：

```bash
git tag v1.2.3
git push origin v1.2.3
```

tag 推送后，`.github/workflows/docker-images.yml` 会执行测试、构建镜像并推送到 GHCR。

发布 `v1.2.3` 时会生成：

```text
ghcr.io/<github-owner>/<github-repo>/backend:v1.2.3
ghcr.io/<github-owner>/<github-repo>/web:v1.2.3
ghcr.io/<github-owner>/<github-repo>/updater:v1.2.3
```

同时生成提交追踪标签：

```text
ghcr.io/<github-owner>/<github-repo>/backend:sha-<commit>
ghcr.io/<github-owner>/<github-repo>/web:sha-<commit>
ghcr.io/<github-owner>/<github-repo>/updater:sha-<commit>
```

推送到 `main` 或 `master` 也可以触发预发布镜像构建。分支构建会发布 `sha-<commit>` 并更新浮动标签 `stable`。

### 3. CI 执行内容

CI 会执行：

1. 安装后端依赖。
2. 执行后端语法检查和测试。
3. 安装前端依赖。
4. 执行 `npm run build`。
5. 构建并推送三个镜像：
   - `${REGISTRY_IMAGE_PREFIX}/backend:<version>`
   - `${REGISTRY_IMAGE_PREFIX}/web:<version>`
   - `${REGISTRY_IMAGE_PREFIX}/updater:<version>`

镜像职责：

- `backend`：FastAPI 后端，运行 `uvicorn main:app --host 0.0.0.0 --port 8000`。
- `web`：Nginx 托管 `frontend/dist`，并反代 `/api` 和 `/static` 到 backend。
- `updater`：内部更新服务，负责 Compose 拉镜像、迁移、重启、健康检查和回滚。

### 4. 镜像标签规则

推荐保留两类标签：

- 固定版本标签：`v1.2.3`，用于用户可控的手动更新。
- 提交标签：`sha-abcdef123456`，用于追踪具体构建来源。

`stable` 可以作为最新稳定版指针，但不建议生产用户默认使用。若用户使用 `APP_VERSION=stable`，每次手动更新实际拉取的版本取决于当时 registry 中 `stable` 的指向。

### 5. 发布后更新版本清单

用户后台的 `检测更新` 不直接枚举 GHCR tag，而是读取我们维护的更新清单。因此正式发布镜像后，发布方必须同步更新 `update-manifest.json`，否则用户侧不会检测到新版本。

推荐清单内容：

```json
{
  "channel": "stable",
  "latest_version": "v1.2.3",
  "min_supported_version": "v1.0.0",
  "release_notes": "修复安装校验，优化 Docker 更新流程。",
  "published_at": "2026-06-05T12:00:00Z"
}
```

发布顺序建议：

1. 推送 `v1.2.3` Git tag。
2. 等待 CI 测试、构建和 GHCR 镜像推送完成。
3. 在测试服务器用 `v1.2.3` 完成升级验证。
4. 更新 `update-manifest.json` 的 `latest_version` 和 `release_notes`。
5. 确认用户服务器后台 `系统更新 -> 检测更新` 能看到新版本。

清单可以托管在我们控制的 HTTPS 地址，例如对象存储、CDN、私有 API 或官网静态资源。若清单接口需要鉴权，只给用户服务器只读 `UPDATE_MANIFEST_TOKEN`，不要给源码、CI 或 registry 写权限。

### 6. 发布交付信息

给用户或交付人员提供：

- 新版本号，例如 `v1.2.3`。
- Docker 部署包，包含 `docker-compose.yml`、`deploy/docker/` 和示例配置文件；不包含应用源码。
- 更新清单地址 `UPDATE_MANIFEST_URL`，如需鉴权则提供只读 `UPDATE_MANIFEST_TOKEN`。
- 更新说明，以及是否包含数据库迁移。
- 是否需要维护窗口。
- 失败处理说明：保留更新日志并联系支持，不要执行 `docker compose down -v`。

不要提供源码仓库访问权限、CI token、构建缓存或可写 registry token。

## 二、用户首次部署与安装流程

### 1. 用户服务器前提

用户服务器需要：

- Linux 服务器，建议 Ubuntu 22.04+、Debian 12+ 或 CentOS/Rocky/AlmaLinux 9+。
- Docker Engine 和 Docker Compose plugin。
- 一个已解析到服务器的域名。
- 宿主机 Nginx 或其他反代服务负责 HTTPS/TLS。
- GHCR 或其他私有镜像仓库的只读 pull token。

生产服务器不需要 Git、源码仓库访问权限、Node.js、Python 构建工具或前后端构建依赖。

### 2. 放置部署文件

部署包只应包含运行部署所需文件：

```text
docker-compose.yml
deploy/docker/.env.example
deploy/docker/runtime/backend.env.example
deploy/docker/update-lorevista.sh
deploy/docker/updater/
deploy/docker/nginx/
deploy/docker/systemd/
deploy/docker/RELEASE_AND_UPDATE.md
```

将部署包放到 `/opt/lorevista`：

```bash
sudo mkdir -p /opt/lorevista
sudo tar -xzf lorevista-docker-deploy-v1.2.3.tar.gz -C /opt/lorevista
cd /opt/lorevista

sudo mkdir -p deploy/docker/runtime data
sudo cp deploy/docker/.env.example .env
sudo cp deploy/docker/runtime/backend.env.example deploy/docker/runtime/backend.env
sudo chmod 600 .env deploy/docker/runtime/backend.env
```

如果不是 tar 包交付，也可以手动复制 `docker-compose.yml` 和 `deploy/docker/` 到 `/opt/lorevista`。不要把 `.git` 或源码目录复制到生产服务器。

### 3. 配置 `/opt/lorevista/.env`

编辑 `/opt/lorevista/.env`：

```env
REGISTRY_IMAGE_PREFIX=ghcr.io/your-org/lorevista
APP_VERSION=v1.2.3

WEB_BIND_ADDR=127.0.0.1
WEB_PORT=8080
LOREVISTA_APP_DIR=/opt/lorevista
LOREVISTA_DATA_DIR=/opt/lorevista/data
DOCKER_CONFIG_DIR=/root/.docker

POSTGRES_DB=manga_novel
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<strong-postgres-password>

DATABASE_URL=postgresql://postgres:<strong-postgres-password>@postgres:5432/manga_novel
REDIS_URL=redis://redis:6379/0
REDIS_ENABLED=true
SYSTEM_INSTALLED=false
RUN_STARTUP_MIGRATIONS=false

UPDATER_URL=http://updater:8090
UPDATER_TOKEN=<long-random-token>
UPDATE_MANIFEST_URL=https://example.com/lorevista/update-manifest.json
UPDATE_MANIFEST_TOKEN=
```

生成 `UPDATER_TOKEN`：

```bash
openssl rand -hex 32
```

### 3.1 Token 配置位置总览

用户服务器会用到三类 token，配置位置不同：

| Token | 用途 | 配置位置 | 是否写入 `.env` |
|------|------|----------|----------------|
| Registry 只读 pull token | 拉取 GHCR/私有仓库镜像 | 宿主机执行 `docker login`，Docker 保存到 `DOCKER_CONFIG_DIR`，默认 `/root/.docker/config.json` | 不写入 `.env` |
| `UPDATER_TOKEN` | backend 调用内部 updater 的共享密钥 | `/opt/lorevista/.env` | 写入 |
| `UPDATE_MANIFEST_TOKEN` | 读取私有更新清单 | `/opt/lorevista/.env`，仅清单接口私有时填写 | 可选写入 |

Registry 只读 pull token 的配置方式：

```bash
echo "$READ_ONLY_REGISTRY_TOKEN" | docker login ghcr.io -u "$REGISTRY_USER" --password-stdin
```

登录成功后，Docker 会把认证信息保存到：

```text
/root/.docker/config.json
```

Compose 中的 `DOCKER_CONFIG_DIR=/root/.docker` 会把该目录只读挂载给 `updater`，用于更新时执行 `docker compose pull`。不要把 registry token 明文写入 `/opt/lorevista/.env`，也不要写入 `backend.env`。

如果用户使用 Compose 管理的 PostgreSQL 和 Redis，安装向导里的 host 应填写 `postgres` 和 `redis`，不要填写 `localhost`。

如果用户使用外部 PostgreSQL 或 Redis，需要在启动容器前把 `/opt/lorevista/.env` 中的 `DATABASE_URL` 和 `REDIS_URL` 改为外部服务地址。安装向导填写的值必须指向同一套服务，否则安装程序可能初始化一个数据库，而重启后的后端连接另一个数据库。

### 4. 配置后端运行时密钥

编辑 `/opt/lorevista/deploy/docker/runtime/backend.env`：

```env
DEEPSEEK_API_KEY=
IMAGE_API_KEY=
IMAGE_API_BASE_URL=https://api.xbyjs.top/v1
VIDEO_API_KEY=
VIDEO_API_BASE_URL=https://api.xbyjs.top/v1
VIDEO_MODEL=veo3.1-fast

SYSTEM_INSTALLED=false
REDIS_ENABLED=true
RUN_STARTUP_MIGRATIONS=false

CORS_ORIGINS=https://your-domain.example
MAX_UPLOAD_BYTES=10485760
API_TOKEN=
```

AI Key 可以首次安装时留空，后续由管理员补齐。

### 5. 登录私有镜像仓库

只使用只读 token 登录：

```bash
echo "$READ_ONLY_REGISTRY_TOKEN" | docker login ghcr.io -u "$REGISTRY_USER" --password-stdin
```

验证镜像可拉取：

```bash
docker pull ghcr.io/your-org/lorevista/backend:v1.2.3
docker pull ghcr.io/your-org/lorevista/web:v1.2.3
docker pull ghcr.io/your-org/lorevista/updater:v1.2.3
```

### 6. 启动容器

```bash
cd /opt/lorevista
docker compose --env-file .env pull
docker compose --env-file .env up -d
docker compose --env-file .env ps
```

检查本机 web 端点：

```bash
curl -fsS http://127.0.0.1:8080/api/health
```

首次未安装时，`installed=false` 或 `ready=false` 是正常的。只要 web 页面能打开，就可以继续安装向导。

### 7. 配置宿主机 Nginx

将公网流量反代到 Docker web 容器：

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

PostgreSQL 和 Redis 不要暴露到公网。

### 8. 完成浏览器安装向导

打开用户域名。系统未安装时会自动进入安装页。

如果使用 Compose 管理的 PostgreSQL：

```text
数据库 host: postgres
数据库 port: 5432
数据库名: manga_novel
用户名: postgres
密码: /opt/lorevista/.env 中的 POSTGRES_PASSWORD
sslmode: disable
```

如果使用 Compose 管理的 Redis：

```text
Redis host: redis
Redis port: 6379
Redis db: 0
Redis username: 留空
Redis password: 留空
Redis tls: false
```

创建用户自己的管理员账号。管理员邮箱必须是合法邮箱格式，密码至少 8 位。

目标数据库必须是空库。如果检测到已有用户或平台配置，安装程序会拒绝重复安装。

### 9. 安装完成后重启后端

安装完成后，当前后端进程不会热切换数据库连接。重启后端容器：

```bash
cd /opt/lorevista
docker compose --env-file .env restart backend
```

刷新页面，用安装向导创建的管理员账号登录。

如果页面上的“自动重启后端”按钮可用，也可以点击按钮。如果按钮失败，以宿主机命令为准。

### 10. 首次安装验收

确认：

- 管理员账号可以登录。
- `/api/health` 返回 `ok=true`、`installed=true`、`ready=true`。
- 默认平台配置、套餐和系统提示词已存在。
- `manga_outputs` 和 `video_outputs` 挂载到 `/opt/lorevista/data`。
- `docker compose --env-file .env ps` 显示 `backend`、`web`、`updater`、`postgres`、`redis` 都在运行。

## 三、用户站内手动更新流程

### 1. 用户服务器前提

用户服务器必须已完成首次部署和安装，并满足：

- `/opt/lorevista/docker-compose.yml` 存在。
- `/opt/lorevista/deploy/docker/update-lorevista.sh` 存在。
- `/opt/lorevista/.env` 包含 `REGISTRY_IMAGE_PREFIX`、`APP_VERSION`、`UPDATER_TOKEN`、`UPDATE_MANIFEST_URL` 等部署配置。
- `backend`、`web`、`updater`、`postgres`、`redis` 正常运行。
- 服务器已使用只读 token 登录私有镜像仓库。
- 宿主机 Nginx 只反代到 `web` 容器端口。
- PostgreSQL 和 Redis 不暴露到公网。

只读 registry 登录示例：

```bash
echo "$READ_ONLY_REGISTRY_TOKEN" | docker login ghcr.io -u "$REGISTRY_USER" --password-stdin
```

生产服务器只需要 Compose 文件、部署脚本、运行时配置和数据目录，不需要完整源码仓库。

### 2. 在后台启动更新

管理员操作步骤：

1. 使用管理员账号登录。
2. 打开管理后台。
3. 打开 `系统更新`。
4. 点击 `检测更新`。
5. 如果检测到新版本，确认版本号和更新说明。
6. 点击 `更新到最新版`。
7. 在页面等待更新状态和日志。

普通管理员不需要手动输入版本号。页面会通过 `UPDATE_MANIFEST_URL` 读取我们发布的最新稳定版本，并把检测到的版本传给 updater。

`指定镜像版本` 属于高级回退功能，只用于回滚、灰度或技术支持指定版本。例如 `v1.2.3` 或 `sha-abcdef123456`。

后端管理员 API：

- `GET /api/admin/system/update/check`
- `GET /api/admin/system/update/status`
- `POST /api/admin/system/update`

业务后端只负责管理员鉴权并调用内部 updater，不挂载 Docker socket。Docker 操作由 `updater` 容器执行。

### 2.1 更新清单

我们发布方需要维护一个更新清单，例如：

```json
{
  "channel": "stable",
  "latest_version": "v1.2.4",
  "min_supported_version": "v1.0.0",
  "release_notes": "修复安装校验，优化 Docker 更新流程。",
  "published_at": "2026-06-05T12:00:00Z"
}
```

用户服务器配置：

```env
UPDATE_MANIFEST_URL=https://example.com/lorevista/update-manifest.json
```

如果更新清单是私有接口，可以额外配置：

```env
UPDATE_MANIFEST_TOKEN=<read-only-manifest-token>
```

清单 token 只用于读取版本清单，不应具备 registry 写权限、源码访问权限或 CI 权限。

### 3. updater 执行顺序

管理员启动更新后，updater 会：

1. 如果提供了目标版本，更新 `/opt/lorevista/.env` 中的 `APP_VERSION` 并创建备份。
2. 执行 `docker compose pull backend web`。
3. 对比当前运行镜像和拉取后的镜像。
4. 如果镜像无变化，直接退出。
5. 使用新后端镜像执行数据库迁移。
6. 重启 `backend`。
7. 检查 backend `/api/health`。
8. 重启 `web`。
9. 检查 web `/api/health`。
10. 记录更新日志。

默认迁移命令：

```bash
python -c "from database import init_db; init_db(run_migrations=True, raise_errors=True)"
```

### 4. 失败和回滚

如果迁移或健康检查失败，updater 会尝试：

- 恢复 `.env` 中旧的 `APP_VERSION`。
- 将 `backend` 和 `web` 镜像 tag 回更新前的镜像 ID。
- 执行 `docker compose up -d` 恢复旧容器。

管理员应在 `系统更新` 页面查看日志。日志会做基础脱敏，不应暴露 `.env` 密钥、数据库密码或 registry token。

如果后台不可访问，可在宿主机执行兜底命令：

```bash
sudo APP_DIR=/opt/lorevista /usr/bin/env bash /opt/lorevista/deploy/docker/update-lorevista.sh
```

### 5. 用户侧配置建议

可控版本更新推荐：

```env
REGISTRY_IMAGE_PREFIX=ghcr.io/your-org/lorevista
APP_VERSION=v1.2.3
UPDATER_URL=http://updater:8090
UPDATER_TOKEN=<long-random-token>
UPDATE_MANIFEST_URL=https://example.com/lorevista/update-manifest.json
```

管理员点击 `检测更新` 后，updater 会读取 `UPDATE_MANIFEST_URL`，比较清单中的 `latest_version` 和当前 `/opt/lorevista/.env` 中的 `APP_VERSION`。如果有新版本，管理员点击 `更新到最新版` 即可。

如果管理员在 UI 高级区域输入目标版本，更新前 `APP_VERSION` 可以保持为当前已安装版本。updater 会在拉取镜像前更新它。

普通生产环境不建议默认使用：

```env
APP_VERSION=stable
```

`stable` 是浮动标签，实际拉取版本取决于管理员触发更新时 registry 中 `stable` 的指向。

### 6. 数据和安全红线

生产环境不要执行：

```bash
docker compose down -v
git clean -fdx
rm -rf backend
```

这些命令可能删除数据库 volume 或用户生成资源。

必须持久化保存：

- `/opt/lorevista/data/manga_outputs`
- `/opt/lorevista/data/video_outputs`
- Docker volume `lorevista_postgres_data`
- Docker volume `lorevista_redis_data`

安全要求：

- `backend` 不挂载 `/var/run/docker.sock`。
- `updater` 不暴露公网端口，只允许 Docker 内部网络访问。
- `UPDATER_TOKEN` 必须是长随机值，并同时配置给 `backend` 和 `updater`。
- 服务器 registry token 只能 pull 当前项目镜像。
- 生产服务器不保存 `.git`、源码、CI token、构建缓存或可写 registry token。

### 7. 推荐用户通知

```text
新版本已发布：v1.2.3。
请使用管理员账号登录，进入管理后台 -> 系统更新，点击“检测更新”，确认后点击“更新到最新版”。
系统会自动拉取镜像、执行数据库迁移、重启服务并进行健康检查。
如果更新失败，请保留更新日志并联系技术支持。不要执行 docker compose down -v。
```
